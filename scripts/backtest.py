#!/usr/bin/env python3
"""CLI: backtest a strategy against historical Kraken candles.

Two data sources:

  --data-source csv (default)  Build candles from Kraken's downloadable tick
      CSVs in --data-dir (KRAKEN_DATA_DIR). Full history, deterministic and
      reproducible: the same command always covers the same window.

  --data-source rest           Fetch candles from Kraken's public OHLC endpoint.
      No credentials needed, but capped at ~720 candles per request regardless
      of --limit, and always relative to *now* - so results shift over time and
      cannot be reproduced later.

Usage:
    uv run python scripts/backtest.py --symbol BTC/USD --timeframe 1h
    uv run python scripts/backtest.py --symbol BTC/USD --start 2024-01-01 --end 2024-12-31
    uv run python scripts/backtest.py --strategy macd --symbol ETH/USD --timeframe 4h
    uv run python scripts/backtest.py --data-source rest --symbol BTC/USD --limit 720

Valid --timeframe values: 1m, 5m, 15m, 30m, 1h, 4h, 1d, 1w, 2w (Kraken has no
arbitrary intervals; note its "2w" is really a 15-day interval).

--timeframe 5m, 15m, 1h, 4h, and 1d automatically add multi-timeframe entry
confirmation against higher timeframes (5m -> 15m+1h, 15m -> 1h+4h,
1h -> 4h+1d, 4h -> 1d, 1d -> 1w+2w) — the strategy's crossover still triggers on
--timeframe candles; the higher timeframes only gate whether a BUY goes
through. See docs/trading-bot-design.md ("Multi-Timeframe Entry Confirmation").

See docs/trading-bot-design.md ("Backtesting Guide") for how to interpret the results.
"""

import argparse
import asyncio
from datetime import datetime
from decimal import Decimal
from pathlib import Path

import pandas as pd

from src.backtest.data import load_candles
from src.backtest.engine import Backtester, buy_and_hold_return_pct
from src.bot.strategies.base import MTF_CONFIRMATION_MAP, ohlcv_to_dataframe
from src.bot.strategies.registry import STRATEGIES, create_strategy
from src.config import get_settings
from src.exchange.kraken import KrakenClient


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--symbol", default="BTC/USD", help="Trading pair, e.g. BTC/USD")
    parser.add_argument(
        "--timeframe",
        default="1h",
        choices=KrakenClient.TIMEFRAMES,
        help="Candle timeframe. Kraken has no arbitrary intervals (e.g. no '10d') — "
        "to cover more history, pick a coarser one of these, not a bigger --limit.",
    )
    parser.add_argument(
        "--data-source",
        default="csv",
        choices=("csv", "rest"),
        help="Where candles come from: csv (default) builds them from local Kraken tick "
        "data for full, reproducible history; rest fetches from the public OHLC endpoint, "
        "which is capped at ~720 candles and always relative to now.",
    )
    parser.add_argument(
        "--data-dir",
        default=None,
        help="Directory of Kraken tick CSVs (--data-source csv). Defaults to "
        "KRAKEN_DATA_DIR from the environment/.env.",
    )
    parser.add_argument(
        "--cache-dir",
        default="data/candles",
        help="Where to cache resampled 1-minute candles so each tick file is only "
        "read once. Set to an empty string to disable caching.",
    )
    parser.add_argument(
        "--start",
        default=None,
        help="Only use candles at or after this UTC date/time, e.g. 2024-01-01 "
        "(--data-source csv only).",
    )
    parser.add_argument(
        "--end",
        default=None,
        help="Only use candles at or before this UTC date/time, e.g. 2024-12-31 "
        "(--data-source csv only).",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=500,
        help="Number of historical candles to request (--data-source rest only). "
        "Kraken's public OHLC endpoint caps the response at ~720 regardless of this "
        "value; use --data-source csv with --start/--end for longer windows.",
    )
    parser.add_argument(
        "--strategy",
        default="sma",
        choices=sorted(STRATEGIES),
        help="Which strategy to backtest: sma (simple moving average, smoother/slower "
        "to confirm), ema (exponential, reacts faster but noisier), macd (MACD "
        "signal-line crossover - a momentum trigger that tends to fire earlier than "
        "the underlying EMA cross), rsi (RSI crossing the SMA drawn over it - "
        "threshold-free, so it does not fight a trend the way overbought/oversold "
        "levels do), or confluence (EMA crossover on Heikin Ashi "
        "candles, confirmed by MACD/RSI/Bollinger Bands - RSI/BB periods use their "
        "standard defaults, not configurable here).",
    )
    parser.add_argument(
        "--fast",
        type=int,
        default=None,
        help="Fast moving-average period. Defaults to each strategy's own default "
        "(10 for sma/ema, 12 for macd, 5 for confluence) if omitted.",
    )
    parser.add_argument(
        "--slow",
        type=int,
        default=None,
        help="Slow moving-average period. Defaults to each strategy's own default "
        "(30 for sma/ema, 26 for macd, 10 for confluence) if omitted.",
    )
    parser.add_argument(
        "--signal",
        type=int,
        default=None,
        help="MACD signal-line period (--strategy macd only). Defaults to 9 if omitted.",
    )
    parser.add_argument(
        "--rsi-period",
        type=int,
        default=None,
        help="RSI lookback length (--strategy rsi only). Defaults to 14 if omitted.",
    )
    parser.add_argument(
        "--ma-period",
        type=int,
        default=None,
        help="Length of the SMA drawn over the RSI (--strategy rsi only). Defaults "
        "to 14 if omitted.",
    )
    parser.add_argument(
        "--balance", type=Decimal, default=Decimal("10000"), help="Starting balance"
    )
    parser.add_argument(
        "--position-size-pct",
        type=Decimal,
        default=Decimal("100"),
        help="Percent of available balance to spend per BUY signal",
    )
    parser.add_argument(
        "--fee-pct",
        type=Decimal,
        default=Decimal("0.26"),
        help="Trading fee per fill, as a percent of trade value. Defaults to a typical "
        "taker fee ballpark — check Kraken's current fee schedule for your account's "
        "actual tier and pass it explicitly (0 to disable).",
    )
    parser.add_argument(
        "--slippage-pct",
        type=Decimal,
        default=Decimal("0.05"),
        help="Adverse price movement applied to each fill versus the bar's raw open, "
        "as a percent. A rough estimate for a liquid pair; widen it for illiquid "
        "pairs or large order sizes (0 to disable).",
    )
    return parser.parse_args()


def _parse_moment(value: str | None, flag: str) -> datetime | None:
    if value is None:
        return None
    try:
        return datetime.fromisoformat(value)
    except ValueError as exc:
        raise SystemExit(f"{flag} must be an ISO date/time like 2024-01-01: {exc}") from exc


def _resolve_data_dir(args: argparse.Namespace) -> Path:
    configured = args.data_dir or get_settings().kraken_data_dir
    if not configured:
        raise SystemExit(
            "No Kraken tick-data directory configured. Set KRAKEN_DATA_DIR in .env, "
            "pass --data-dir, or use --data-source rest to fetch from the API instead."
        )
    data_dir = Path(configured).expanduser()
    if not data_dir.is_dir():
        raise SystemExit(
            f"Kraken tick-data directory not found: {data_dir}. "
            f"Fix --data-dir/KRAKEN_DATA_DIR, or use --data-source rest."
        )
    return data_dir


def _describe(label: str, frame: pd.DataFrame) -> None:
    if len(frame) > 0:
        print(f"  {label}: {len(frame)} candles, {frame.index[0]} to {frame.index[-1]}")
    else:
        print(f"  {label}: no candles available")


def _load_from_csv(
    args: argparse.Namespace, entry_timeframe: str, higher_timeframes: tuple[str, ...]
) -> dict[str, pd.DataFrame]:
    """Load the entry timeframe plus any confirmation timeframes.

    --start bounds the *entry* timeframe only. The confirmation timeframes
    deliberately keep their earlier history: their indicators need warmup bars
    from before the window opens, and a coarse timeframe has very few candles
    inside a short window (a year holds only ~25 of Kraken's 15-day "2w"
    candles, fewer than an EMA(30) needs). Truncating them there would leave
    confirmation permanently unsatisfiable and silently produce zero trades.
    Lookahead is not a concern - Backtester.run() slices every confirmation
    frame to the current bar's timestamp on each step.
    """
    data_dir = _resolve_data_dir(args)
    cache_dir = Path(args.cache_dir).expanduser() if args.cache_dir else None
    start = _parse_moment(args.start, "--start")
    end = _parse_moment(args.end, "--end")

    frames = {
        entry_timeframe: load_candles(
            data_dir, args.symbol, entry_timeframe, start=start, end=end, cache_dir=cache_dir
        )
    }
    for tf in higher_timeframes:
        frames[tf] = load_candles(
            data_dir, args.symbol, tf, start=None, end=end, cache_dir=cache_dir
        )
    return frames


async def _load_from_rest(
    args: argparse.Namespace, timeframes: list[str]
) -> dict[str, pd.DataFrame]:
    async with KrakenClient() as client:
        return {
            tf: ohlcv_to_dataframe(
                await client.fetch_ohlcv(args.symbol, timeframe=tf, limit=args.limit)
            )
            for tf in timeframes
        }


async def main() -> None:
    args = parse_args()

    if args.data_source == "rest" and (args.start or args.end):
        raise SystemExit(
            "--start/--end only apply to --data-source csv; the REST endpoint always "
            "returns the most recent candles."
        )

    mtf_timeframes = MTF_CONFIRMATION_MAP.get(args.timeframe)
    higher_timeframes = mtf_timeframes or ()

    if args.data_source == "csv":
        frames = _load_from_csv(args, args.timeframe, higher_timeframes)
    else:
        frames = await _load_from_rest(args, [args.timeframe, *higher_timeframes])

    candles = frames[args.timeframe]
    higher_tf_candles: dict[str, pd.DataFrame] | None = None
    if mtf_timeframes is not None:
        higher_tf_candles = {tf: frames[tf] for tf in mtf_timeframes}

    print(f"Data source:      {args.data_source}")
    _describe(f"{args.timeframe} (entry)", candles)
    if mtf_timeframes is not None:
        print(f"Multi-timeframe confirmation: {args.timeframe} -> {', '.join(mtf_timeframes)}")
        for tf in mtf_timeframes:
            _describe(tf, frames[tf])

    if candles.empty:
        raise SystemExit(
            f"No {args.timeframe} candles for {args.symbol} in the requested window. "
            f"Check --start/--end."
        )

    try:
        strategy = create_strategy(
            args.strategy,
            fast=args.fast,
            slow=args.slow,
            signal=args.signal,
            rsi_period=args.rsi_period,
            ma_period=args.ma_period,
        )
    except ValueError as exc:
        raise SystemExit(str(exc)) from exc
    backtester = Backtester(
        strategy,
        args.symbol,
        starting_balance=args.balance,
        position_size_pct=args.position_size_pct,
        fee_pct=args.fee_pct,
        slippage_pct=args.slippage_pct,
    )
    result = backtester.run(candles, higher_tf_candles=higher_tf_candles)

    win_rate = result.win_rate_pct
    win_rate_display = "n/a" if win_rate is None else f"{win_rate:.2f}%"

    print(f"Strategy:         {result.strategy}")
    print(f"Symbol:           {result.symbol}")
    print(f"Candles:          {len(candles)} ({args.timeframe})")
    print(f"Starting balance: {result.starting_balance:.2f}")
    print(f"Ending balance:   {result.ending_balance:.2f}")
    print(f"Total return:     {result.total_return_pct:.2f}%")
    print(f"Trades:           {len(result.trades)} ({len(result.closed_trades)} closed)")
    print(f"Win rate:         {win_rate_display}")
    print(f"Max drawdown:     {result.max_drawdown_pct:.2f}%")
    print(f"Fees paid:        {result.total_fees_paid:.2f} ({args.fee_pct}% per fill)")
    print(f"Buy & hold:       {buy_and_hold_return_pct(candles):.2f}%  (baseline for comparison)")


if __name__ == "__main__":
    asyncio.run(main())
