"""Reconstruct paper balances for databases written before they were persisted.

Paper balances only began persisting on 2026-08-08. A database written before
that has trades and positions but no balances, so a restarted bot would resume
with the starting cash and no base currency - orphaning any open position, since
process_signal() clamps a sell to min(position.amount, executor balance).

Replays the trade log from the $10,000 starting balance. Safe to re-run: it
recomputes from scratch rather than adjusting whatever is already stored.

Usage:
    DATABASE_URL="sqlite+aiosqlite:///path/to/bot.db" \
        uv run python tools/backfill_paper_balances.py
"""
import asyncio
import sys
from decimal import Decimal
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from src.database.models import init_database  # noqa: E402
from src.database.repository import UnitOfWork  # noqa: E402

START_USD = Decimal("10000")

async def main() -> None:
    await init_database()
    async with UnitOfWork() as uow:
        trades = sorted(await uow.trades.get_recent(limit=10_000),
                        key=lambda t: t.created_at)
        balances = {"USD": START_USD}
        for t in trades:
            base = t.symbol.split("/")[0]
            gross = t.amount * t.price
            if t.side == "buy":
                balances["USD"] -= gross + t.fee
                balances[base] = balances.get(base, Decimal("0")) + t.amount
            else:
                balances["USD"] += gross - t.fee
                balances[base] = balances.get(base, Decimal("0")) - t.amount
        await uow.paper_balances.save_all(balances)
        await uow.commit()
    print("  replayed", len(trades), "trades ->",
          ", ".join(f"{c}={a:.6f}" for c, a in sorted(balances.items())))

asyncio.run(main())
