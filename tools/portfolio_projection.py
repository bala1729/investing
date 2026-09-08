"""Bootstrap a year-end portfolio outcome distribution from real historical trade sequences.

Building block: `Backtester` already replays a strategy bar-by-bar with no lookahead
and gives the exact (timestamp, side, price) of every trade it would have made in
isolation, at 100% position sizing - that 100% figure is irrelevant here, only the
*timing and price* of each trade is reused. This script pulls that trade sequence
independently for each of the five live symbols (same strategy config as what's
actually live: rsi_m2, 4h, confirmed against 1d), then replays all five streams
together in chronological order against ONE shared cash balance, sizing each entry
at that symbol's real live position-size cap (15% for BTC/ETH/SOL/ADA, 5% for DOGE)
of whatever cash is free at that moment - exactly how TradingEngine actually sizes a
live entry (empirically confirmed: the cap-of-balance figure, not the risk-based
one, is what binds for this account).

This produces one realistic multi-symbol equity curve - the closest thing to "what
would this exact live setup's account balance have done" that the available history
allows. From that single curve, every historical window of the requested length
(default: today through calendar year end) is sampled - a standard historical
bootstrap. The resulting distribution is applied to the account's real current
balance to produce a percentile spread, not a point guess.

Known simplifications, stated plainly rather than hidden in the number:
  - A held position is marked at its own entry price between its own entry and exit,
    not continuously to market - realized P&L (what actually drives compounding) is
    exact, but intra-trade unrealized swings are not reflected in the equity curve.
  - Overlapping windows are not independent draws - a multi-year trend appears in
    many consecutive windows, so this describes the *historical spread actually
    observed*, not a formal confidence interval.
  - Assumes the next N days resemble some day in the archive's history (per-symbol,
    from whenever that symbol's data begins, through 2025-12-31). It cannot know
    about conditions with no historical precedent.

Usage:
    uv run python tools/portfolio_projection.py [--days N]
"""

import argparse
import os
import sys
from decimal import Decimal
from pathlib import Path

import pandas as pd

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

from src.backtest.data import load_base_candles, resample_candles  # noqa: E402
from src.backtest.engine import Backtester  # noqa: E402
from src.bot.strategies.examples.rsi_crossover import RSICrossoverStrategy  # noqa: E402
from src.config import get_settings  # noqa: E402
from src.exchange.executor import OrderSide  # noqa: E402

DATA = Path(os.environ.get("KRAKEN_DATA_DIR") or get_settings().kraken_data_dir).expanduser()
CACHE = Path(os.environ.get("CANDLE_CACHE") or REPO_ROOT / "data" / "candles")

FEE = Decimal("0.26")
SLIP = Decimal("0.05")

SYMBOL_CAPS = {
    "BTC/USD": Decimal("15"),
    "ETH/USD": Decimal("15"),
    "SOL/USD": Decimal("15"),
    "ADA/USD": Decimal("15"),
    "DOGE/USD": Decimal("5"),
}


def symbol_trade_events(symbol: str) -> list[tuple[pd.Timestamp, OrderSide, Decimal]]:
    """The exact (timestamp, side, price) of every trade this symbol's live strategy
    would have made in isolation - reusing Backtester purely for its no-lookahead
    signal-and-fill mechanics, not its (here irrelevant) 100%-sizing dollar amounts."""
    base = load_base_candles(DATA, symbol, cache_dir=CACHE)
    candles_4h = resample_candles(base, "4h")
    candles_1d = resample_candles(base, "1d")
    strategy = RSICrossoverStrategy(14, 14, exit_margin=2.0)
    result = Backtester(
        strategy, symbol, position_size_pct=Decimal("100"), fee_pct=FEE, slippage_pct=SLIP
    ).run(candles_4h, higher_tf_candles={"1d": candles_1d})
    print(f"{symbol}: {len(result.trades)} trade events", file=sys.stderr)
    return [(t.timestamp, t.side, t.price) for t in result.trades]


def build_portfolio_equity_curve() -> list[tuple[pd.Timestamp, Decimal]]:
    """Replay all five symbols' independent trade streams against one shared cash
    balance, sizing each entry at that symbol's real live cap of current free cash."""
    all_events: list[tuple[pd.Timestamp, str, OrderSide, Decimal]] = []
    for symbol in SYMBOL_CAPS:
        for ts, side, price in symbol_trade_events(symbol):
            all_events.append((ts, symbol, side, price))
    all_events.sort(key=lambda e: e[0])

    cash = Decimal("10000")  # arbitrary base for the curve; real balance applied later
    holdings: dict[str, tuple[Decimal, Decimal]] = {}  # symbol -> (units, entry_price)
    curve: list[tuple[pd.Timestamp, Decimal]] = []

    for ts, symbol, side, price in all_events:
        if side == OrderSide.BUY:
            if symbol in holdings or cash <= 0:
                continue
            spend = cash * (SYMBOL_CAPS[symbol] / 100)
            fee_amt = spend * (FEE / 100)
            units = (spend - fee_amt) / price
            cash -= spend
            holdings[symbol] = (units, price)
        else:
            if symbol not in holdings:
                continue
            units, _entry_price = holdings.pop(symbol)
            gross = units * price
            fee_amt = gross * (FEE / 100)
            cash += gross - fee_amt

        equity = cash + sum(units * entry_price for units, entry_price in holdings.values())
        curve.append((ts, equity))

    return curve


def bootstrap_window_ratios(
    curve: list[tuple[pd.Timestamp, Decimal]], window_days: int
) -> list[float]:
    """Every historical window of `window_days` length found in the curve, as a
    multiplicative ratio (ending equity / starting equity)."""
    if not curve:
        return []
    times = [c[0] for c in curve]
    values = [float(c[1]) for c in curve]
    window = pd.Timedelta(days=window_days)
    ratios = []
    j = 0
    n = len(curve)
    for i in range(n):
        start_t, start_v = times[i], values[i]
        if start_v <= 0:
            continue
        target = start_t + window
        if target > times[-1]:
            break
        j = max(j, i)
        while j + 1 < n and times[j + 1] <= target:
            j += 1
        ratios.append(values[j] / start_v)
    return ratios


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--days", type=int, default=None, help="Window length in days")
    parser.add_argument("--balance", type=float, default=None, help="Starting balance to project")
    args = parser.parse_args()

    if args.days is None:
        today = pd.Timestamp.now(tz="UTC").normalize()
        year_end = pd.Timestamp(year=today.year, month=12, day=31, tz="UTC")
        args.days = (year_end - today).days
    print(f"Window length: {args.days} days", file=sys.stderr)

    curve = build_portfolio_equity_curve()
    print(f"Equity curve: {len(curve)} events, {curve[0][0].date()} -> {curve[-1][0].date()}",
          file=sys.stderr)

    ratios = bootstrap_window_ratios(curve, args.days)
    print(f"{len(ratios)} historical {args.days}-day windows found", file=sys.stderr)

    ratios.sort()
    balance = args.balance if args.balance is not None else 3135.33
    pct_labels = [5, 10, 25, 50, 75, 90, 95]
    print()
    print(f"Starting balance: ${balance:,.2f}")
    print(f"Percentile outcomes over the next {args.days} days "
          f"(from {len(ratios)} historical windows):")
    for p in pct_labels:
        idx = min(len(ratios) - 1, max(0, int(len(ratios) * p / 100)))
        ratio = ratios[idx]
        print(f"  p{p:>2}: {ratio:6.3f}x  ->  ${balance * ratio:,.2f}  ({(ratio - 1) * 100:+.1f}%)")

    frac_negative = sum(1 for r in ratios if r < 1.0) / len(ratios) if ratios else 0.0
    print()
    print(f"Fraction of historical windows that lost money: {frac_negative * 100:.1f}%")


if __name__ == "__main__":
    main()
