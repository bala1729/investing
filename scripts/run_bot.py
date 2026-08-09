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
from src.bot.strategies.registry import STRATEGIES, create_strategy
from src.config import get_settings
from src.database.models import init_database
from src.exchange.executor import OrderExecutor
from src.exchange.kraken import KrakenClient
from src.risk.manager import RiskManager


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
        help="Which strategy to run: sma, ema, macd (MACD signal-line crossover), "
        "rsi (RSI crossing its own SMA), or confluence (EMA crossover on Heikin Ashi "
        "candles, confirmed by MACD/RSI/Bollinger Bands).",
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
        "--exit-margin",
        type=float,
        default=None,
        help="How far RSI must close below its SMA before selling, in RSI points "
        "(--strategy rsi only). 0 (the default) exits on any bearish cross, however "
        "shallow. A non-zero margin makes the exit a state check rather than a cross, "
        "since a margined cross would be unreachable once RSI slips below by less than "
        "the margin.",
    )
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

    try:
        strategy = create_strategy(
            args.strategy,
            fast=args.fast,
            slow=args.slow,
            signal=args.signal,
            rsi_period=args.rsi_period,
            ma_period=args.ma_period,
            exit_margin=args.exit_margin,
        )
    except ValueError as exc:
        raise SystemExit(str(exc)) from exc

    client = KrakenClient(settings)
    await client.initialize()
    await init_database()
    try:
        executor = OrderExecutor(client, settings)
        # Before the first cycle: without this a restart would come back with
        # the starting cash and no base currency, orphaning any open position
        # the database still records.
        if await executor.restore_paper_state():
            logger.info("Resumed paper balances from the database")
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
