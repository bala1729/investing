"""Summarize the shared trade journal (src/journal.py): per-trade log, aggregate
stats, and cross-bot timing clusters.

The clustering is the thing no single per-bot database can show: since every
symbol's cron cycle lands on the same 15-minute grid, an entry or exit that's
really "the whole account moved because BTC/ETH/SOL/DOGE are correlated assets
that all crossed their RSI threshold on the same market move" looks, from
inside one bot's own log, indistinguishable from an independent decision.
Grouping by a short time window surfaces which is which.

Usage:
    uv run python tools/journal_report.py
    uv run python tools/journal_report.py --cluster-minutes 60
"""

import argparse
import sqlite3
import sys
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from src.config import get_settings  # noqa: E402


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--db", default=None, help="Journal db path (default: settings)")
    parser.add_argument(
        "--cluster-minutes",
        type=float,
        default=30,
        help="Trades on different symbols within this many minutes of each other "
        "are reported as a timing cluster.",
    )
    args = parser.parse_args()

    db_path = Path(args.db or get_settings().journal_db_path).expanduser()
    if not db_path.exists():
        print(f"No journal at {db_path} yet - nothing recorded.")
        return

    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    rows = conn.execute("SELECT * FROM journal ORDER BY created_at ASC").fetchall()
    conn.close()

    if not rows:
        print("Journal exists but is empty.")
        return

    print(f"{len(rows)} journal entries from {db_path}\n")

    print(f"{'time':<20} {'symbol':<9} {'side':<5} {'price':>12} {'hold':>8} {'return%':>9}")
    for r in rows:
        hold = f"{r['hold_seconds'] / 3600:.1f}h" if r["hold_seconds"] is not None else "-"
        ret = f"{r['return_pct']:+.2f}" if r["return_pct"] is not None else "-"
        print(
            f"{r['created_at'][:19]:<20} {r['symbol']:<9} {r['side']:<5} "
            f"{float(r['price']):>12.6f} {hold:>8} {ret:>9}"
        )

    exits = [r for r in rows if r["side"] == "sell" and r["return_pct"] is not None]
    if exits:
        wins = [r for r in exits if r["return_pct"] > 0]
        avg_return = sum(r["return_pct"] for r in exits) / len(exits)
        avg_hold_h = sum(r["hold_seconds"] for r in exits) / len(exits) / 3600
        print(
            f"\n{len(exits)} closed trades: {len(wins)}/{len(exits)} winners "
            f"({len(wins) / len(exits) * 100:.0f}%), avg return {avg_return:+.2f}%, "
            f"avg hold {avg_hold_h:.1f}h"
        )

    print(f"\nTiming clusters (symbols within {args.cluster_minutes:.0f} min of each other):")
    window = args.cluster_minutes * 60
    used = [False] * len(rows)
    for i, r in enumerate(rows):
        if used[i]:
            continue
        t0 = datetime.fromisoformat(r["created_at"])
        group = [r]
        used[i] = True
        for j in range(i + 1, len(rows)):
            if used[j]:
                continue
            tj = datetime.fromisoformat(rows[j]["created_at"])
            if (tj - t0).total_seconds() <= window:
                group.append(rows[j])
                used[j] = True
        symbols = {g["symbol"] for g in group}
        if len(symbols) > 1:
            sides = ", ".join(f"{g['symbol']} {g['side']}" for g in group)
            print(f"  {r['created_at'][:19]}: {sides}")


if __name__ == "__main__":
    main()
