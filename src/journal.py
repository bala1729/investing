"""Shared trade journal, written to once per filled signal.

Every bot has its own per-symbol database (trades/orders/positions), but
those are siloed - answering "did these coins move together" or "what did
RSI look like at entry" means opening N SQLite files by hand. This writes
one row per filled BUY/SELL, in one shared file, carrying the strategy's
`reason` string (which embeds the RSI/SMA values at signal time for
rsi_crossover) plus hold duration and return% on exits.

Deliberately synchronous plain sqlite3, not the app's async SQLAlchemy
stack: a single small INSERT here doesn't need a connection pool or ORM,
and staying dependency-free keeps this easy to also use from one-off
backfill/report scripts outside the bot process.
"""

import sqlite3
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path

_SCHEMA = """
CREATE TABLE IF NOT EXISTS journal (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    symbol TEXT NOT NULL,
    side TEXT NOT NULL,
    strategy TEXT NOT NULL,
    reason TEXT NOT NULL,
    amount TEXT NOT NULL,
    price TEXT NOT NULL,
    fee TEXT NOT NULL,
    is_paper INTEGER NOT NULL,
    hold_seconds REAL,
    return_pct REAL,
    realized_pnl TEXT,
    created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS ix_journal_symbol_created ON journal (symbol, created_at);
CREATE INDEX IF NOT EXISTS ix_journal_created ON journal (created_at);
"""


def record_execution(
    db_path: str,
    *,
    symbol: str,
    side: str,
    strategy: str,
    reason: str,
    amount: Decimal,
    price: Decimal,
    fee: Decimal,
    is_paper: bool,
    hold_seconds: float | None = None,
    return_pct: float | None = None,
    realized_pnl: Decimal | None = None,
    created_at: datetime | None = None,
) -> None:
    """Append one row. Raises on failure - callers decide how to handle that.

    (Live callers should never let this block a trade; see
    TradingEngine._record_journal for the swallow-and-log wrapper.)

    `created_at` defaults to now, for the live path recording a fill as it
    happens. A backfill script populating history from an old fill must pass
    the original trade's timestamp explicitly - defaulting to "now" there
    would stamp every backfilled row with the backfill's run time instead of
    when the trade actually happened, silently breaking chronological
    ordering and any time-window clustering downstream.
    """
    path = Path(db_path).expanduser()
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(path))
    try:
        conn.executescript(_SCHEMA)
        conn.execute(
            "INSERT INTO journal (symbol, side, strategy, reason, amount, price, fee, "
            "is_paper, hold_seconds, return_pct, realized_pnl, created_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                symbol,
                side,
                strategy,
                reason,
                str(amount),
                str(price),
                str(fee),
                int(is_paper),
                hold_seconds,
                return_pct,
                str(realized_pnl) if realized_pnl is not None else None,
                (created_at or datetime.now(UTC)).isoformat(),
            ),
        )
        conn.commit()
    finally:
        conn.close()
