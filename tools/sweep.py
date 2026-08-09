#!/usr/bin/env python3
"""Replay many backtest configurations against locally cached candles.

`scripts/backtest.py` reloads and resamples the 1-minute cache on every
invocation, which is wasteful across a hundred-config sweep. This loads each
symbol's base candles once, derives every timeframe once, then replays all
configurations against those frames.

This is the harness that produced the tables in `docs/backtest-results.md`. It
lives here rather than in `scripts/` because it is an analysis tool rather than
part of the bot, and it is deliberately excluded from the mypy/coverage gate -
`ruff` still applies.

Usage:
    uv run python tools/sweep.py <output-name> <config.json>
    SWEEP_SYMBOLS="SOL/USD" uv run python tools/sweep.py sol_only cfg.json

Config is a JSON list of objects:

    [
      {"strategy": "rsi_m2", "timeframe": "4h",
       "windows": ["2022", "2023", "full"]},

      {"arm": "stop2", "strategy": "ema(10,30)", "timeframe": "4h",
       "windows": ["full"], "stops": {"stop": 2, "trigger": 2, "lock": 1}},

      {"arm": "no_mtf", "strategy": "rsi_m2", "timeframe": "1h",
       "windows": ["full"], "no_mtf": true},

      {"arm": "4h_only", "strategy": "rsi_m2", "timeframe": "1h",
       "windows": ["full"], "mtf": ["4h"]}
    ]

`arm` labels a variant in the output. `no_mtf` and `mtf` change the confirmation
ladder for a run *without* touching MTF_CONFIRMATION_MAP, so a hypothesis can be
tested while the shipped map stays as it is.

Always include a control arm that reproduces an existing logged baseline, and
check it matches before trusting the comparison - several results in this
project only held up because the control caught a changed assumption.
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
from src.bot.strategies.examples.ema_crossover import EMACrossoverStrategy  # noqa: E402
from src.bot.strategies.examples.heikin_ashi_confluence import (  # noqa: E402
    HeikinAshiConfluenceStrategy,
)
from src.bot.strategies.examples.macd_crossover import MACDCrossoverStrategy  # noqa: E402
from src.bot.strategies.examples.moving_average_crossover import (  # noqa: E402
    MovingAverageCrossoverStrategy,
)
from src.bot.strategies.examples.rsi_crossover import RSICrossoverStrategy  # noqa: E402
from src.config import get_settings  # noqa: E402

DATA = Path(os.environ.get("KRAKEN_DATA_DIR") or get_settings().kraken_data_dir).expanduser()
CACHE = Path(os.environ.get("CANDLE_CACHE") or REPO_ROOT / "data" / "candles")
OUT_DIR = Path(os.environ.get("SWEEP_OUT") or REPO_ROOT / "data" / "sweeps")
SYMBOLS = (os.environ.get("SWEEP_SYMBOLS") or "BTC/USD,ETH/USD,SOL/USD").split(",")

# Matches scripts/backtest.py's defaults, so sweep numbers and single runs agree.
FEE = Decimal("0.26")
SLIP = Decimal("0.05")

STRATEGIES = {
    "sma(10,30)": lambda: MovingAverageCrossoverStrategy(10, 30),
    "ema(10,30)": lambda: EMACrossoverStrategy(10, 30),
    "ema(9,26)": lambda: EMACrossoverStrategy(9, 26),
    "ema(5,10)": lambda: EMACrossoverStrategy(5, 10),
    "macd(12,26,9)": lambda: MACDCrossoverStrategy(12, 26, 9),
    "rsi(14,14)": lambda: RSICrossoverStrategy(14, 14),
    "rsi_m0": lambda: RSICrossoverStrategy(14, 14, exit_margin=0.0),
    "rsi_m0.5": lambda: RSICrossoverStrategy(14, 14, exit_margin=0.5),
    "rsi_m1": lambda: RSICrossoverStrategy(14, 14, exit_margin=1.0),
    "rsi_m2": lambda: RSICrossoverStrategy(14, 14, exit_margin=2.0),
    "rsi_m3": lambda: RSICrossoverStrategy(14, 14, exit_margin=3.0),
    "rsi_m5": lambda: RSICrossoverStrategy(14, 14, exit_margin=5.0),
    "confluence": lambda: HeikinAshiConfluenceStrategy(),
}

WINDOWS: dict[str, tuple[str | None, str | None]] = {
    "2021": ("2021-01-01", "2021-12-31"),
    "2022": ("2022-01-01", "2022-12-31"),
    "2023": ("2023-01-01", "2023-12-31"),
    "2024": ("2024-01-01", "2024-12-31"),
    "2025": ("2025-01-01", "2025-12-31"),
    "full": (None, None),
    # Start-date sensitivity. Four headline results in this project were
    # reversed by exactly this check, so long-window returns should never be
    # quoted without it.
    "2018+": ("2018-01-01", None),
    "2020+": ("2020-01-01", None),
    "2022+": ("2022-01-01", None),
}


def window_slice(frame: pd.DataFrame, start: str | None, end: str | None) -> pd.DataFrame:
    out = frame
    if start:
        out = out[out.index >= pd.Timestamp(start, tz="UTC")]
    if end:
        out = out[out.index <= pd.Timestamp(end, tz="UTC")]
    return out


def run_one(
    strategy_label: str,
    symbol: str,
    timeframe: str,
    frames: dict[str, pd.DataFrame],
    start: str | None,
    end: str | None,
    stops: dict[str, Any] | None = None,
    no_mtf: bool = False,
    mtf_override: list[str] | None = None,
) -> dict[str, Any] | None:
    entry = window_slice(frames[timeframe], start, end)
    if len(entry) < 60:
        return None

    if no_mtf:
        mtf: tuple[str, ...] | None = None
    elif mtf_override is not None:
        mtf = tuple(mtf_override)
    else:
        mtf = MTF_CONFIRMATION_MAP.get(timeframe)

    higher = None
    if mtf:
        # Only the end is bounded. Confirmation timeframes need warmup bars from
        # before the window opens - a calendar year holds ~25 of Kraken's 15-day
        # "2w" candles, fewer than an EMA(30) needs, which once produced a whole
        # sweep of silent zero-trade rows. Backtester.run() re-slices these to
        # the current bar on every step, so this cannot leak lookahead.
        higher = {tf: window_slice(frames[tf], None, end) for tf in mtf}

    stops = stops or {}
    result = Backtester(
        STRATEGIES[strategy_label](),
        symbol,
        starting_balance=Decimal("10000"),
        fee_pct=FEE,
        slippage_pct=SLIP,
        stop_loss_pct=Decimal(str(stops.get("stop", 0))),
        take_profit_pct=Decimal(str(stops.get("target", 0))),
        trailing_trigger_pct=Decimal(str(stops.get("trigger", 0))),
        trailing_lock_pct=Decimal(str(stops.get("lock", 0))),
    ).run(entry, higher_tf_candles=higher)

    win = result.win_rate_pct
    return {
        "strategy": strategy_label,
        "symbol": symbol,
        "timeframe": timeframe,
        "window": f"{entry.index[0].date()}..{entry.index[-1].date()}",
        "candles": len(entry),
        "return_pct": float(result.total_return_pct),
        "buy_hold_pct": float(buy_and_hold_return_pct(entry)),
        "trades": len(result.trades),
        "closed": len(result.closed_trades),
        "win_rate_pct": None if win is None else float(win),
        "max_dd_pct": float(result.max_drawdown_pct),
        "fees": float(result.total_fees_paid),
    }


def main() -> int:
    if len(sys.argv) < 3:
        print(__doc__)
        return 2
    sweep_name, config_path = sys.argv[1], sys.argv[2]
    configs = json.loads(Path(config_path).read_text())

    needed_tfs: set[str] = set()
    for c in configs:
        needed_tfs.add(c["timeframe"])
        if not c.get("no_mtf"):
            needed_tfs.update(c.get("mtf") or MTF_CONFIRMATION_MAP.get(c["timeframe"], ()))

    rows = []
    for symbol in SYMBOLS:
        base = load_base_candles(DATA, symbol, cache_dir=CACHE)
        frames = {tf: (base if tf == "1m" else resample_candles(base, tf)) for tf in needed_tfs}
        print(f"{symbol}: base={len(base):,} candles", file=sys.stderr)
        for c in configs:
            for wname in c.get("windows", ["full"]):
                start, end = WINDOWS[wname]
                row = run_one(
                    c["strategy"], symbol, c["timeframe"], frames, start, end,
                    c.get("stops"), c.get("no_mtf", False), c.get("mtf"),
                )
                if row:
                    row["window_name"] = wname
                    row["arm"] = c.get("arm", "baseline")
                    rows.append(row)
                    print(
                        f"  {row['arm']:12} {c['strategy']:14} {c['timeframe']:4} "
                        f"{wname:6} ret={row['return_pct']:9.2f}% "
                        f"bh={row['buy_hold_pct']:10.2f}% closed={row['closed']:5}",
                        file=sys.stderr,
                    )
        del base, frames

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    out = OUT_DIR / f"{sweep_name}.json"
    out.write_text(json.dumps(rows, indent=1))
    print(f"\nwrote {len(rows)} rows -> {out}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
