#!/usr/bin/env python3
"""CLI: backtest a strategy against historical Kraken candles.

Uses only Kraken's public market-data endpoint (no API credentials needed).

Usage:
    uv run python scripts/backtest.py --symbol BTC/USD --timeframe 1h --limit 500
    uv run python scripts/backtest.py --symbol ETH/USD --fast 5 --slow 20 --balance 5000
    uv run python scripts/backtest.py --symbol BTC/USD --timeframe 1d --limit 720 --fee-pct 0.4

See docs/trading-bot-design.md ("Backtesting Guide") for how to interpret the results.
"""

import argparse
import asyncio
from decimal import Decimal

from src.backtest.engine import Backtester, buy_and_hold_return_pct
from src.bot.strategies.base import ohlcv_to_dataframe
from src.bot.strategies.examples.moving_average_crossover import MovingAverageCrossoverStrategy
from src.exchange.kraken import KrakenClient


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--symbol", default="BTC/USD", help="Trading pair, e.g. BTC/USD")
    parser.add_argument("--timeframe", default="1h", help="Candle timeframe, e.g. 1h, 4h, 1d")
    parser.add_argument("--limit", type=int, default=500, help="Number of historical candles")
    parser.add_argument("--fast", type=int, default=10, help="Fast SMA period")
    parser.add_argument("--slow", type=int, default=30, help="Slow SMA period")
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

    async with KrakenClient() as client:
        ohlcv = await client.fetch_ohlcv(args.symbol, timeframe=args.timeframe, limit=args.limit)

    candles = ohlcv_to_dataframe(ohlcv)
    strategy = MovingAverageCrossoverStrategy(fast_period=args.fast, slow_period=args.slow)
    backtester = Backtester(
        strategy,
        args.symbol,
        starting_balance=args.balance,
        position_size_pct=args.position_size_pct,
        fee_pct=args.fee_pct,
        slippage_pct=args.slippage_pct,
    )
    result = backtester.run(candles)

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
