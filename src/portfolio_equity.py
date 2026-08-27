"""Shared cross-bot portfolio equity, tracked in one file separate from each
bot's own per-symbol database.

Every live bot shares one Kraken account, but each bot only ever sees its own
symbol's position - the drawdown check used to compute "current equity" as
this bot's own balance + this bot's own position only, and compared that
against a peak *also* recorded per-symbol. That meant each bot's peak froze
at whatever the shared free-USD balance happened to be the moment IT last
went flat - stale the instant any *other* bot then drew capital out of that
same shared USD balance into a new position. A bot sitting flat for a while
would look like it had suffered a real drawdown that never happened, purely
because other bots were doing their job (see kraken-bot-state/RESTART.md,
2026-08-17 and 2026-08-27 entries for two real instances this blocked).

This tracks one number instead of N: every bot upserts its own latest
position value here on each cycle, so "current equity" for the drawdown
check is always balance (the one real shared value) + the sum of every
bot's last-known position value - the true account total, not one bot's
sliver of it. The single high-water mark this is compared against only
ever ratchets up, same as the per-symbol table it replaces.

Deliberately synchronous plain sqlite3, matching src/journal.py - a few
small reads/writes don't need the app's async SQLAlchemy stack, and staying
dependency-free keeps this usable from scripts outside the bot process too.
"""

import sqlite3
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path

_SCHEMA = """
CREATE TABLE IF NOT EXISTS bot_snapshots (
    symbol TEXT PRIMARY KEY,
    position_value TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS portfolio_peak_equity (
    id INTEGER PRIMARY KEY CHECK (id = 1),
    peak_equity TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
"""


def record_and_get_portfolio_equity(
    db_path: str,
    symbol: str,
    position_value: Decimal,
    balance: Decimal,
) -> tuple[Decimal, Decimal]:
    """Upsert this bot's position value, and return (current_equity, peak_equity)
    computed across every bot's latest known snapshot.

    Raises on failure - callers must decide the safe fallback (see
    TradingEngine.process_signal, which falls back to this bot's own
    balance+position alone: strictly a subset of the true total, so it can
    only make the drawdown check MORE cautious that cycle, never mask a
    real drawdown by undercounting).
    """
    path = Path(db_path).expanduser()
    path.parent.mkdir(parents=True, exist_ok=True)
    now = datetime.now(UTC).isoformat()
    conn = sqlite3.connect(str(path))
    try:
        conn.executescript(_SCHEMA)
        conn.execute(
            "INSERT INTO bot_snapshots (symbol, position_value, updated_at) "
            "VALUES (?, ?, ?) "
            "ON CONFLICT(symbol) DO UPDATE SET "
            "position_value = excluded.position_value, updated_at = excluded.updated_at",
            (symbol, str(position_value), now),
        )
        total_position_value = sum(
            (Decimal(row[0]) for row in conn.execute("SELECT position_value FROM bot_snapshots")),
            start=Decimal("0"),
        )
        current_equity = balance + total_position_value

        row = conn.execute("SELECT peak_equity FROM portfolio_peak_equity WHERE id = 1").fetchone()
        if row is None:
            peak_equity = current_equity
            conn.execute(
                "INSERT INTO portfolio_peak_equity (id, peak_equity, updated_at) VALUES (1, ?, ?)",
                (str(peak_equity), now),
            )
        else:
            stored_peak = Decimal(row[0])
            peak_equity = max(stored_peak, current_equity)
            if peak_equity != stored_peak:
                conn.execute(
                    "UPDATE portfolio_peak_equity SET peak_equity = ?, updated_at = ? WHERE id = 1",
                    (str(peak_equity), now),
                )
        conn.commit()
    finally:
        conn.close()
    return current_equity, peak_equity
