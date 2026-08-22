"""Backfill the shared trade journal (src/journal.py) from a live bot's own trades table.

The journal only started capturing new fills once TradingEngine._record_journal()
landed (2026-08-22). Everything traded before that - including the SOL/BTC/ETH/DOGE
round trips from 2026-08-18 through 2026-08-22 - exists only as raw fills in each
bot's own per-symbol database, with no `reason` string: Signal.reason (the RSI/SMA
values at signal time) was computed and immediately discarded every cycle before
the journal existed to catch it. That part of the history is genuinely gone; this
backfill is price/timing/return% only, and says so explicitly in each row's reason
field rather than leaving it blank or guessing a value.

Pairs BUY/SELL fills FIFO per symbol to reconstruct hold_seconds and return_pct,
same shape as what the live engine records going forward. Safe to re-run against
the same source db - the journal has no uniqueness constraint keyed on source
trade id, so re-running WILL duplicate rows; this is a one-shot backfill tool, not
a sync job.

Usage:
    uv run python tools/backfill_journal.py ~/kraken-bot-state/trading_bot_sol_4h_rsi_m2_live.db
"""

import sqlite3
import sys
from datetime import datetime
from decimal import Decimal
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from src.config import get_settings  # noqa: E402
from src.journal import record_execution  # noqa: E402

BACKFILL_REASON = (
    "(backfilled from raw trade history - RSI/SMA at signal time was never "
    "persisted for trades before the journal existed, so it's not recoverable)"
)


def main(source_db: str) -> None:
    conn = sqlite3.connect(source_db)
    conn.row_factory = sqlite3.Row
    rows = conn.execute(
        "SELECT created_at, symbol, side, amount, price, fee, strategy, is_paper "
        "FROM trades ORDER BY created_at ASC"
    ).fetchall()
    conn.close()

    open_buys: list[sqlite3.Row] = []
    journal_path = get_settings().journal_db_path
    written = 0
    for row in rows:
        created_at = datetime.fromisoformat(row["created_at"])
        if row["side"] == "buy":
            open_buys.append(row)
            record_execution(
                journal_path,
                symbol=row["symbol"],
                side="buy",
                strategy=row["strategy"] or "unknown",
                reason=BACKFILL_REASON,
                amount=Decimal(str(row["amount"])),
                price=Decimal(str(row["price"])),
                fee=Decimal(str(row["fee"])),
                is_paper=bool(row["is_paper"]),
                created_at=created_at,
            )
            written += 1
        else:
            entry = open_buys.pop(0) if open_buys else None
            hold_seconds = None
            return_pct = None
            realized_pnl = None
            if entry is not None:
                entry_time = datetime.fromisoformat(entry["created_at"])
                hold_seconds = (created_at - entry_time).total_seconds()
                entry_price = Decimal(str(entry["price"]))
                exit_price = Decimal(str(row["price"]))
                if entry_price:
                    return_pct = float((exit_price - entry_price) / entry_price * 100)
                realized_pnl = (exit_price - entry_price) * Decimal(str(row["amount"]))
            record_execution(
                journal_path,
                symbol=row["symbol"],
                side="sell",
                strategy=row["strategy"] or "unknown",
                reason=BACKFILL_REASON,
                amount=Decimal(str(row["amount"])),
                price=Decimal(str(row["price"])),
                fee=Decimal(str(row["fee"])),
                is_paper=bool(row["is_paper"]),
                hold_seconds=hold_seconds,
                return_pct=return_pct,
                realized_pnl=realized_pnl,
                created_at=created_at,
            )
            written += 1

    print(f"Backfilled {written} trades from {source_db} -> {journal_path}")


if __name__ == "__main__":
    if len(sys.argv) != 2:
        print("Usage: uv run python tools/backfill_journal.py <path-to-bot-db>")
        sys.exit(1)
    main(sys.argv[1])
