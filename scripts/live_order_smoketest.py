#!/usr/bin/env python3
"""CLI: place one minimum-size real market buy+sell to verify the live order path
actually works, before ever letting a strategy trade real money.

This places REAL orders against a REAL Kraken account. It refuses to run unless
TRADING_MODE=live is already set in the process environment (never falls back to
paper), requires an explicit CLI flag, and asks for an interactive "yes" that echoes
back exactly what it's about to do before placing anything.

It calls OrderExecutor/KrakenClient directly - the same production code the live bot
uses - not a reimplementation, so this actually exercises the path being verified.

Usage:
    TRADING_MODE=live uv run python scripts/live_order_smoketest.py --symbol SOL/USD \\
        --yes-i-know-this-places-a-real-order

Recovery, if the sell leg fails after a confirmed buy (this script never auto-retries
a leg that may have already gone through - see _execute_live_market_order's docstring
for why retrying an accepted order is exactly the failure mode being avoided here):

    TRADING_MODE=live uv run python scripts/live_order_smoketest.py --symbol SOL/USD \\
        --yes-i-know-this-places-a-real-order --sell-only --amount 0.0612
"""

import argparse
import asyncio
import sys
from decimal import Decimal

from src.config import get_settings
from src.exchange.executor import Order, OrderExecutor, OrderSide, OrderStatus
from src.exchange.kraken import KrakenClient

SAFETY_MARGIN = Decimal("1.02")
SLIPPAGE_WARNING_BPS = Decimal("100")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("--symbol", default="SOL/USD", help="Trading pair to test.")
    parser.add_argument(
        "--yes-i-know-this-places-a-real-order",
        action="store_true",
        dest="confirmed_flag",
        help="Required. This script places real orders with real money against a real "
        "Kraken account. A second, interactive confirmation follows this flag - it does "
        "not skip that prompt.",
    )
    parser.add_argument(
        "--sell-only",
        action="store_true",
        help="Recovery mode: skip the buy leg and just sell --amount.",
    )
    parser.add_argument(
        "--amount",
        type=Decimal,
        default=None,
        help="Amount to sell in --sell-only mode. Required with --sell-only, ignored "
        "otherwise (the normal run sizes and sells its own buy).",
    )
    return parser.parse_args()


def bps(delta: Decimal, base: Decimal) -> Decimal:
    """Basis points of `delta` relative to `base`, 0 if `base` is 0."""
    if base == 0:
        return Decimal("0")
    return (delta / base) * Decimal("10000")


def report_leg(label: str, order: Order, pre_price: Decimal, requested_amount: Decimal) -> bool:
    """Print a verification report for one fill. Returns False if anything looks off."""
    ok = True
    print(f"\n--- {label} ---")
    print(f"status: {order.status.value}")
    print(f"exchange order id: {order.exchange_order_id}")
    print(f"requested amount: {requested_amount}")
    print(f"filled amount: {order.filled_amount}")

    if order.status != OrderStatus.FILLED:
        print(f"!! NOT FILLED - stopping here. error: {order.error_message}")
        return False

    if order.filled_amount < requested_amount:
        print(f"!! PARTIAL FILL: requested {requested_amount}, got {order.filled_amount}")
        ok = False

    if order.average_fill_price is not None and pre_price > 0:
        slip = bps(abs(order.average_fill_price - pre_price), pre_price)
        print(
            f"pre-order price: {pre_price}, avg fill price: {order.average_fill_price}, "
            f"slippage: {slip:.1f} bps"
        )
        if slip > SLIPPAGE_WARNING_BPS:
            print(f"!! slippage over {SLIPPAGE_WARNING_BPS} bps - check the order book depth")
            ok = False

    print(f"fee: {order.fee} {order.fee_currency or ''}")
    if order.fee == 0:
        print(
            "(fee reported as 0 - per _extract_fee's docstring this can mean "
            "'not reported', not 'no fee was charged')"
        )

    return ok


async def size_order(client: KrakenClient, symbol: str, price: Decimal) -> Decimal:
    """The larger of the exchange's amount and cost minimums, with a safety margin.

    ccxt rounds to exchange precision internally when placing the order, so sizing
    exactly at a minimum risks rounding below it and being rejected.
    """
    base = symbol.split("/")[0]
    min_amount = await client.get_minimum_order_amount(symbol) or Decimal("0")

    market = await client.get_market_info(symbol)
    min_cost = Decimal("0")
    if market:
        raw_min_cost = market.get("limits", {}).get("cost", {}).get("min")
        if raw_min_cost is not None:
            min_cost = Decimal(str(raw_min_cost))
    amount_from_cost_min = (min_cost / price) if price > 0 else Decimal("0")

    amount = max(min_amount, amount_from_cost_min) * SAFETY_MARGIN
    print(f"exchange amount minimum: {min_amount} {base}")
    print(f"exchange cost minimum: {min_cost} (~{amount_from_cost_min} {base})")
    print(f"sizing at {amount} {base} (~{amount * price:.2f}, includes {SAFETY_MARGIN}x margin)")
    return amount


async def main() -> int:
    args = parse_args()
    settings = get_settings()

    if settings.is_paper_trading:
        print("REFUSING TO RUN: TRADING_MODE is not 'live' in this process's environment.")
        print("This script only runs against a real account - set TRADING_MODE=live explicitly.")
        return 1

    if not args.confirmed_flag:
        print("Refusing to run without --yes-i-know-this-places-a-real-order.")
        return 1

    if args.sell_only and args.amount is None:
        print("--sell-only requires --amount")
        return 1

    base, quote = args.symbol.split("/")
    client = KrakenClient(settings)
    await client.initialize()
    executor = OrderExecutor(client, settings)

    try:
        print(f"\n=== LIVE order-path smoke test: {args.symbol} ===")
        print("Step 0: checking account access...")
        try:
            balance = await client.fetch_balance()
        except Exception as e:
            print(f"FAIL: could not fetch account balance - check API key/permissions. {e}")
            return 1
        start_quote = Decimal(str(balance.get("free", {}).get(quote, 0)))
        start_base = Decimal(str(balance.get("free", {}).get(base, 0)))
        print(f"PASS: authenticated. free {quote}={start_quote}, free {base}={start_base}")

        ticker = await client.fetch_ticker(args.symbol)
        price = Decimal(str(ticker["last"]))
        print(f"current price: {price}")

        buy_order: Order | None = None
        if args.sell_only:
            amount = args.amount
            assert amount is not None  # checked above
            print(f"\n--sell-only: will sell {amount} {base}, no buy leg.")
        else:
            print("\nStep 1: sizing the order...")
            amount = await size_order(client, args.symbol, price)
            if start_quote < amount * price:
                print(f"FAIL: free {quote} balance ({start_quote}) is below the estimated cost")
                return 1

        print(
            f"\nAbout to place a REAL market {'SELL' if args.sell_only else 'BUY, then SELL'} "
            f"of ~{amount} {base} (~${amount * price:.2f}) on {args.symbol}."
        )
        if input("Type 'yes' to proceed: ").strip().lower() != "yes":
            print("Aborted - no order placed.")
            return 1

        if not args.sell_only:
            print("\nStep 3: BUY leg...")
            buy_order = await executor.execute_market_order(args.symbol, OrderSide.BUY, amount)
            if not report_leg("BUY", buy_order, price, amount):
                print(
                    "\nFAIL: buy leg did not look clean. Stopping - nothing further will be "
                    "attempted automatically. Reconcile manually before retrying."
                )
                return 1
            amount = buy_order.filled_amount  # sell exactly what was actually received

        print(f"\nStep 4: SELL leg (selling {amount} {base})...")
        sell_pre_price = Decimal(str((await client.fetch_ticker(args.symbol))["last"]))
        sell_order = await executor.execute_market_order(args.symbol, OrderSide.SELL, amount)
        sell_ok = report_leg("SELL", sell_order, sell_pre_price, amount)

        print("\nStep 5: final report...")
        final_balance = await client.fetch_balance()
        end_quote = Decimal(str(final_balance.get("free", {}).get(quote, 0)))
        end_base = Decimal(str(final_balance.get("free", {}).get(base, 0)))
        print(f"{quote}: {start_quote} -> {end_quote} (delta {end_quote - start_quote:+.4f})")
        print(f"{base}: {start_base} -> {end_base} (delta {end_base - start_base:+.8f})")

        total_fees = sell_order.fee + (buy_order.fee if buy_order is not None else Decimal("0"))
        round_trip_cost = start_quote - end_quote
        cost_bps = bps(abs(round_trip_cost), start_quote) if start_quote else Decimal("0")
        print(f"total fees reported: {total_fees} {quote}")
        print(f"round-trip cost: {round_trip_cost:+.4f} {quote} ({cost_bps:.1f} bps)")

        verdict = sell_ok
        print(
            f"\n{'PASS' if verdict else 'FAIL'} - "
            + (
                "the live order path looks correct. Safe to proceed toward running the "
                "strategy live."
                if verdict
                else "something above looked wrong. Do not run the strategy live yet - "
                "investigate first."
            )
        )
        return 0 if verdict else 1
    finally:
        await client.close()


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
