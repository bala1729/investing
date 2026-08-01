#!/usr/bin/env python3
"""CLI: run the autonomous trading loop against live Kraken market data.

Fetches recent candles on an interval, asks a strategy for a signal, and
routes any signal through TradingEngine.process_signal() - the same
risk-gated path the TradingView webhook uses. Trading mode (paper/live) and
risk limits come from Settings/.env, not from flags here - double-check
TRADING_MODE before running this against a live account.

Usage:
    uv run python scripts/run_bot.py --symbol BTC/USD --timeframe 1h
    uv run python scripts/run_bot.py --strategy ema --fast 5 --slow 20 --poll-interval 300

Stop with Ctrl+C; the Kraken client connection is closed cleanly on exit.
"""

import argparse
import asyncio
from contextlib import suppress

from loguru import logger

from src.bot.engine import TradingEngine
from src.bot.strategies.examples.ema_crossover import EMACrossoverStrategy
from src.bot.strategies.examples.moving_average_crossover import MovingAverageCrossoverStrategy
from src.config import get_settings
from src.database.models import init_database
from src.exchange.executor import OrderExecutor
from src.exchange.kraken import KrakenClient
from src.risk.manager import RiskManager

STRATEGIES = {
    "sma": MovingAverageCrossoverStrategy,
    "ema": EMACrossoverStrategy,
}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--symbol", default="BTC/USD", help="Trading pair, e.g. BTC/USD")
    parser.add_argument(
        "--timeframe",
        default="1h",
        choices=KrakenClient.TIMEFRAMES,
        help="Candle timeframe used to generate signals.",
    )
    parser.add_argument(
        "--strategy",
        default="sma",
        choices=sorted(STRATEGIES),
        help="Which crossover strategy to run: sma or ema.",
    )
    parser.add_argument("--fast", type=int, default=10, help="Fast moving-average period")
    parser.add_argument("--slow", type=int, default=30, help="Slow moving-average period")
    parser.add_argument(
        "--limit",
        type=int,
        default=100,
        help="Closed candles used per cycle (must exceed --slow). One extra candle is "
        "always fetched and dropped, since the most recent one from the exchange is "
        "still forming.",
    )
    parser.add_argument(
        "--poll-interval",
        type=float,
        default=60,
        help="Seconds between cycles",
    )
    return parser.parse_args()


async def main() -> None:
    args = parse_args()
    settings = get_settings()

    mode_banner = "PAPER" if settings.is_paper_trading else "LIVE"
    logger.warning(f"Starting bot in {mode_banner} trading mode for {args.symbol}")

    strategy_cls = STRATEGIES[args.strategy]
    strategy = strategy_cls(fast_period=args.fast, slow_period=args.slow)

    client = KrakenClient(settings)
    await client.initialize()
    await init_database()
    try:
        executor = OrderExecutor(client, settings)
        risk_manager = RiskManager(settings)
        engine = TradingEngine(client, executor, risk_manager, settings)

        await engine.run_forever(
            strategy,
            args.symbol,
            timeframe=args.timeframe,
            limit=args.limit,
            poll_interval_seconds=args.poll_interval,
        )
    finally:
        await client.close()


if __name__ == "__main__":
    with suppress(KeyboardInterrupt):
        asyncio.run(main())
