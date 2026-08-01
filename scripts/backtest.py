#!/usr/bin/env python3
"""CLI: backtest a strategy against historical Kraken candles.

Uses only Kraken's public market-data endpoint (no API credentials needed).

Usage:
    uv run python scripts/backtest.py --symbol BTC/USD --timeframe 1h --limit 500
    uv run python scripts/backtest.py --symbol ETH/USD --fast 5 --slow 20 --balance 5000
    uv run python scripts/backtest.py --symbol BTC/USD --timeframe 1d --limit 720 --fee-pct 0.4
    uv run python scripts/backtest.py --strategy ema --symbol BTC/USD --timeframe 1d --limit 720

Valid --timeframe values: 1m, 5m, 15m, 30m, 1h, 4h, 1d, 1w, 2w (Kraken has no
arbitrary intervals). Kraken's public OHLC endpoint also caps history at ~720
candles regardless of --limit — for a longer lookback, use a coarser
--timeframe (e.g. 1d or 1w), not a bigger --limit.

--timeframe 15m, 1h, 4h, and 1d automatically add multi-timeframe entry
confirmation against two higher timeframes (15m -> 1h+4h, 1h -> 4h+1d,
4h -> 1d+1w, 1d -> 1w+2w) — the strategy's crossover still triggers on
--timeframe candles; the higher timeframes only gate whether a BUY goes
through. See docs/trading-bot-design.md ("Multi-Timeframe Entry Confirmation").

See docs/trading-bot-design.md ("Backtesting Guide") for how to interpret the results.
"""

import argparse
import asyncio
from decimal import Decimal

import pandas as pd

from src.backtest.engine import Backtester, buy_and_hold_return_pct
from src.bot.strategies.base import MTF_CONFIRMATION_MAP, ohlcv_to_dataframe
from src.bot.strategies.examples.ema_crossover import EMACrossoverStrategy
from src.bot.strategies.examples.heikin_ashi_confluence import HeikinAshiConfluenceStrategy
from src.bot.strategies.examples.moving_average_crossover import MovingAverageCrossoverStrategy
from src.exchange.kraken import KrakenClient

STRATEGIES = {
    "sma": MovingAverageCrossoverStrategy,
    "ema": EMACrossoverStrategy,
    "confluence": HeikinAshiConfluenceStrategy,
}


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
        "--limit",
        type=int,
        default=500,
        help="Number of historical candles to request. Kraken's public OHLC endpoint "
        "caps the response at ~720 candles regardless of this value — for a longer "
        "lookback, use a coarser --timeframe instead of raising --limit.",
    )
    parser.add_argument(
        "--strategy",
        default="sma",
        choices=sorted(STRATEGIES),
        help="Which strategy to backtest: sma (simple moving average, smoother/slower "
        "to confirm), ema (exponential, reacts faster but noisier), or confluence "
        "(EMA crossover on Heikin Ashi candles, confirmed by MACD/RSI/Bollinger Bands "
        "- MACD/RSI/BB periods use their standard defaults, not configurable here).",
    )
    parser.add_argument(
        "--fast",
        type=int,
        default=None,
        help="Fast moving-average period. Defaults to each strategy's own default "
        "(10 for sma/ema, 5 for confluence) if omitted.",
    )
    parser.add_argument(
        "--slow",
        type=int,
        default=None,
        help="Slow moving-average period. Defaults to each strategy's own default "
        "(30 for sma/ema, 10 for confluence) if omitted.",
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


async def main() -> None:
    args = parse_args()

    higher_tf_candles: dict[str, pd.DataFrame] | None = None
    mtf_timeframes = MTF_CONFIRMATION_MAP.get(args.timeframe)

    async with KrakenClient() as client:
        ohlcv = await client.fetch_ohlcv(args.symbol, timeframe=args.timeframe, limit=args.limit)

        if mtf_timeframes is not None:
            higher_tf_candles = {}
            print(f"Multi-timeframe confirmation: {args.timeframe} -> {', '.join(mtf_timeframes)}")
            for tf in mtf_timeframes:
                higher_ohlcv = await client.fetch_ohlcv(args.symbol, timeframe=tf, limit=args.limit)
                higher_df = ohlcv_to_dataframe(higher_ohlcv)
                higher_tf_candles[tf] = higher_df
                if len(higher_df) > 0:
                    print(
                        f"  {tf}: {len(higher_df)} candles, "
                        f"{higher_df.index[0]} to {higher_df.index[-1]}"
                    )
                else:
                    print(f"  {tf}: no candles available")

    candles = ohlcv_to_dataframe(ohlcv)
    strategy_cls = STRATEGIES[args.strategy]
    period_kwargs = {}
    if args.fast is not None:
        period_kwargs["fast_period"] = args.fast
    if args.slow is not None:
        period_kwargs["slow_period"] = args.slow
    strategy = strategy_cls(**period_kwargs)
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
