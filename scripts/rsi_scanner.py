#!/usr/bin/env python3
"""CLI: scan Kraken USD pairs for symbols currently satisfying the RSI entry
condition, and SMS-alert on symbols that newly qualify since the last scan.

Reuses RSICrossoverStrategy directly rather than reimplementing its logic, so
a symbol this reports as "would enter" is guaranteed to match what the live
bots' own strategy would actually decide - no drift between the scanner and
the bots it's scanning alongside.

Kraken lists 600+ active USD pairs, most too illiquid to trust a momentum
signal on, and fetching candles for all of them would take ~20 minutes per
scan at this client's rate limit. Pre-filters with a single fetch_tickers()
call to symbols with at least --min-volume in 24h quote volume (default
$500,000) before fetching any candles, and excludes stablecoin/fiat pairs
(USDT, USDC, EUR, etc.) - meaningless for a momentum strategy on an asset
pegged to the dollar.

Tracks which symbols were bullish on the previous run in a small JSON state
file (--state-file) and only alerts on symbols that are newly bullish, so a
symbol that stays bullish across several scans doesn't re-alert every cycle.

Usage:
    uv run python scripts/rsi_scanner.py
    uv run python scripts/rsi_scanner.py --min-volume 100000 --timeframe 4h \\
        --state-file ~/kraken-bot-state/rsi_scanner_state.json

Designed to run from cron, like scripts/watchdog.py - checks once and exits.
"""

import argparse
import asyncio
import json
import sys
from datetime import UTC, datetime
from pathlib import Path

from loguru import logger

from src.bot.strategies.base import MTF_CONFIRMATION_MAP, Signal, ohlcv_to_dataframe
from src.bot.strategies.examples.rsi_crossover import RSICrossoverStrategy
from src.config import get_settings
from src.exchange.executor import OrderSide
from src.exchange.kraken import KrakenClient
from src.notifications import SmsNotifier

# Stablecoins and fiat currencies traded against USD on Kraken - an RSI momentum
# signal on an asset pegged to the dollar is noise, not signal.
EXCLUDED_BASE_CURRENCIES = {
    "USDT", "USDC", "DAI", "TUSD", "USDP", "PYUSD", "USDG", "USDS",
    "EUR", "GBP", "CHF", "AUD", "CAD", "JPY",
}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument(
        "--timeframe",
        default="4h",
        choices=KrakenClient.TIMEFRAMES,
        help="Entry timeframe to scan.",
    )
    parser.add_argument(
        "--min-volume",
        type=float,
        default=500_000.0,
        help="Minimum 24h quote volume (USD) required to scan a symbol.",
    )
    parser.add_argument("--rsi-period", type=int, default=14)
    parser.add_argument("--ma-period", type=int, default=14)
    parser.add_argument(
        "--limit",
        type=int,
        default=100,
        help="Candles fetched per timeframe (matches run_bot.py's default).",
    )
    parser.add_argument(
        "--state-file",
        default="rsi_scanner_state.json",
        help="Where the previous scan's bullish set is stored, for new-signal dedup.",
    )
    return parser.parse_args()


async def select_symbols(client: KrakenClient, min_volume: float) -> list[str]:
    """Active USD spot pairs, excluding stablecoins/fiat, above the volume floor."""
    markets = await client.fetch_markets()
    candidates = {
        m["symbol"]
        for m in markets
        if m.get("quote") == "USD"
        and m.get("spot")
        and m.get("active")
        and m["symbol"].split("/")[0] not in EXCLUDED_BASE_CURRENCIES
    }
    tickers = await client.fetch_tickers()
    liquid = [
        symbol
        for symbol in candidates
        if symbol in tickers and (tickers[symbol].get("quoteVolume") or 0) >= min_volume
    ]
    return sorted(liquid)


async def check_symbol(
    client: KrakenClient,
    strategy: RSICrossoverStrategy,
    symbol: str,
    timeframe: str,
    mtf_timeframes: tuple[str, ...],
    limit: int,
) -> Signal | None:
    """Fetch candles the same way TradingEngine.run_strategy_once() does (one
    extra candle fetched and dropped, since the most recent is still forming)
    and ask the strategy for a signal - so a result here matches exactly what
    the live bot would decide given the same data.
    """
    ohlcv = await client.fetch_ohlcv(symbol, timeframe=timeframe, limit=limit + 1)
    candles = ohlcv_to_dataframe(ohlcv[:-1])

    higher_tf_candles = None
    if mtf_timeframes:
        higher_tf_candles = {}
        for tf in mtf_timeframes:
            higher_ohlcv = await client.fetch_ohlcv(symbol, timeframe=tf, limit=limit + 1)
            higher_tf_candles[tf] = ohlcv_to_dataframe(higher_ohlcv[:-1])

    return strategy.generate_signal(symbol, candles, higher_tf_candles)


def load_previous_bullish(state_file: str) -> set[str]:
    try:
        data = json.loads(Path(state_file).read_text())
        return set(data.get("bullish", []))
    except (OSError, json.JSONDecodeError):
        return set()


def save_state(state_file: str, bullish: set[str]) -> None:
    payload = {"bullish": sorted(bullish), "updated_at": datetime.now(UTC).isoformat()}
    Path(state_file).write_text(json.dumps(payload, indent=2))


def format_alert(newly_bullish: dict[str, str], timeframe: str) -> str:
    symbols = ", ".join(sorted(newly_bullish))
    return f"RSI scanner: {len(newly_bullish)} newly bullish on {timeframe}: {symbols}"


async def main() -> int:
    args = parse_args()
    settings = get_settings()
    client = KrakenClient(settings)
    await client.initialize()

    try:
        symbols = await select_symbols(client, args.min_volume)
        print(f"Scanning {len(symbols)} symbols (>= ${args.min_volume:,.0f} 24h volume)...")

        strategy = RSICrossoverStrategy(args.rsi_period, args.ma_period)
        mtf_timeframes = MTF_CONFIRMATION_MAP.get(args.timeframe) or ()

        bullish: dict[str, str] = {}
        errors: list[str] = []
        for symbol in symbols:
            try:
                signal = await check_symbol(
                    client, strategy, symbol, args.timeframe, mtf_timeframes, args.limit
                )
            except Exception as e:
                errors.append(symbol)
                logger.debug(f"Skipping {symbol}: {e}")
                continue
            if signal is not None and signal.side == OrderSide.BUY:
                bullish[symbol] = signal.reason

        previous = load_previous_bullish(args.state_file)
        newly_bullish = {s: r for s, r in bullish.items() if s not in previous}

        print(f"\nCurrently bullish on {args.timeframe} ({len(bullish)}):")
        for symbol in sorted(bullish):
            marker = " (NEW)" if symbol in newly_bullish else ""
            print(f"  {symbol}{marker}: {bullish[symbol]}")
        if errors:
            print(f"\n{len(errors)} symbols skipped (fetch error): {', '.join(errors)}")

        save_state(args.state_file, set(bullish))

        if newly_bullish:
            message = format_alert(newly_bullish, args.timeframe)
            sent = await SmsNotifier(settings).send(message)
            print(f"\nSMS {'sent' if sent else 'not sent (not configured or failed)'}: {message}")
        else:
            print("\nNo newly-bullish symbols since the last scan - no alert sent.")

        return 0
    finally:
        await client.close()


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
