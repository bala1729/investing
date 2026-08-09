"""Assess strategies against a day/swing-trading *income* objective.

Every sweep so far reported total return, which says nothing about whether the
money arrives regularly. For someone trying to draw income weekly, the things
that matter are how often it trades, how long capital is tied up, and how
consistent week-to-week results are - including how long the worst dry spell
runs.
"""

import json
import os
import sys
from decimal import Decimal
from pathlib import Path
from typing import Any

import pandas as pd

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

from src.backtest.data import load_base_candles, resample_candles  # noqa: E402
from src.backtest.engine import Backtester, buy_and_hold_return_pct  # noqa: E402
from src.bot.strategies.base import MTF_CONFIRMATION_MAP  # noqa: E402
from src.bot.strategies.examples.rsi_crossover import RSICrossoverStrategy  # noqa: E402
from src.config import get_settings  # noqa: E402

DATA = Path(os.environ.get("KRAKEN_DATA_DIR") or get_settings().kraken_data_dir).expanduser()
CACHE = Path(os.environ.get("CANDLE_CACHE") or REPO_ROOT / "data" / "candles")
OUT_DIR = Path(os.environ.get("SWEEP_OUT") or REPO_ROOT / "data" / "sweeps")
FEE, SLIP = Decimal("0.26"), Decimal("0.05")


def weekly_stats(equity_curve: list[Decimal], index: pd.Index) -> dict[str, Any] | None:
    """Weekly return series derived from the mark-to-market equity curve."""
    equity = pd.Series([float(e) for e in equity_curve], index=index)
    weekly = equity.resample("W").last().dropna()
    returns = weekly.pct_change().dropna() * 100
    if returns.empty:
        return None

    green = (returns > 0).sum()
    # Longest run of consecutive non-positive weeks: the dry spell someone
    # drawing an income actually has to survive.
    worst_streak = streak = 0
    for r in returns:
        streak = streak + 1 if r <= 0 else 0
        worst_streak = max(worst_streak, streak)

    return {
        "weeks": int(len(returns)),
        "green_pct": float(green / len(returns) * 100),
        "median_week_pct": float(returns.median()),
        "mean_week_pct": float(returns.mean()),
        "best_week_pct": float(returns.max()),
        "worst_week_pct": float(returns.min()),
        "week_stdev_pct": float(returns.std()),
        "longest_losing_streak_weeks": int(worst_streak),
    }


def holding_stats(trades: list[Any], total_bars: int, bar_hours: float) -> dict[str, Any]:
    """Trade cadence and how long positions are actually held."""
    holds = []
    entry = None
    for t in trades:
        if t.pnl is None:
            entry = t.timestamp
        elif entry is not None:
            holds.append((t.timestamp - entry).total_seconds() / 3600)
            entry = None
    span_weeks = total_bars * bar_hours / 24 / 7
    closed = len(holds)
    return {
        "closed_trades": closed,
        "trades_per_week": closed / span_weeks if span_weeks else 0.0,
        "median_hold_hours": float(pd.Series(holds).median()) if holds else 0.0,
        "mean_hold_hours": float(pd.Series(holds).mean()) if holds else 0.0,
        "max_hold_hours": float(max(holds)) if holds else 0.0,
    }


BAR_HOURS = {"5m": 1/12, "15m": 0.25, "1h": 1, "4h": 4, "1d": 24}


def run(symbol: str, timeframe: str, margin: float, start: str | None,
        end: str | None, frames: dict[str, pd.DataFrame]) -> dict[str, Any]:
    entry = frames[timeframe]
    if start:
        entry = entry[entry.index >= pd.Timestamp(start, tz="UTC")]
    if end:
        entry = entry[entry.index <= pd.Timestamp(end, tz="UTC")]

    higher = None
    mtf = MTF_CONFIRMATION_MAP.get(timeframe)
    if mtf:
        higher = {}
        for tf in mtf:
            f = frames[tf]
            higher[tf] = f[f.index <= pd.Timestamp(end, tz="UTC")] if end else f

    result = Backtester(
        RSICrossoverStrategy(14, 14, exit_margin=margin),
        symbol,
        starting_balance=Decimal("10000"),
        fee_pct=FEE,
        slippage_pct=SLIP,
    ).run(entry, higher_tf_candles=higher)

    row = {
        "symbol": symbol,
        "timeframe": timeframe,
        "margin": margin,
        "window": f"{entry.index[0].date()}..{entry.index[-1].date()}",
        "return_pct": float(result.total_return_pct),
        "buy_hold_pct": float(buy_and_hold_return_pct(entry)),
        "max_dd_pct": float(result.max_drawdown_pct),
        "fees_paid": float(result.total_fees_paid),
        "bars": len(entry),
    }
    row.update(holding_stats(result.trades, len(entry), BAR_HOURS[timeframe]))
    ws = weekly_stats(result.equity_curve, entry.index)
    if ws:
        row.update(ws)

    # Buy-and-hold weekly profile, for a like-for-like consistency comparison.
    bh_equity = [Decimal(str(c)) / Decimal(str(entry.iloc[0]["open"])) * 10000
                 for c in entry["close"]]
    bh = weekly_stats(bh_equity, entry.index)
    if bh:
        row.update({f"bh_{k}": v for k, v in bh.items()})
    return row


def main() -> None:
    symbol = os.environ.get("SYMBOL", "SOL/USD")
    start = os.environ.get("START") or None
    end = os.environ.get("END") or None

    needed = {"5m", "15m", "1h", "4h", "1d", "1w", "2w"}
    base = load_base_candles(DATA, symbol, cache_dir=CACHE)
    frames = {tf: resample_candles(base, tf) for tf in needed}
    print(f"{symbol}: base={len(base):,} candles", file=sys.stderr)

    rows = []
    timeframes = (os.environ.get("TFS") or "1h,4h").split(",")
    margins = [float(m) for m in (os.environ.get("MARGINS") or "0,2").split(",")]
    for timeframe in timeframes:
        for margin in margins:
            row = run(symbol, timeframe, margin, start, end, frames)
            rows.append(row)
            print(f"  {timeframe} m{margin:g}: {row['closed_trades']} trades, "
                  f"{row['trades_per_week']:.2f}/wk, "
                  f"green {row.get('green_pct', 0):.0f}%", file=sys.stderr)

    name = os.environ.get("OUT", "income")
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    out = OUT_DIR / f"{name}.json"
    out.write_text(json.dumps(rows, indent=1))
    print(f"wrote {len(rows)} rows -> {out}", file=sys.stderr)


if __name__ == "__main__":
    main()
