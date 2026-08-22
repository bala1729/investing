#!/usr/bin/env python3
"""CLI: check that a bot is alive, and raise the alarm if it died holding a position.

A dead bot with no position is an inconvenience. A dead bot *holding* a
position is the dangerous state: nothing is watching the trade, no exit signal
can fire, and with STOP_ENFORCEMENT=off there is no resting order to protect it
either. That distinction is the whole reason this script exists, and it is why
the two cases alert differently.

Designed to be run from cron - it checks once and exits, rather than running as
a second daemon that could itself die unnoticed.

Usage:
    uv run python scripts/watchdog.py --pid-file bot.pid --symbol SOL/USD
    uv run python scripts/watchdog.py --pid-file bot.pid --symbol SOL/USD \\
        --log-file bot.log --max-log-age-minutes 45

Exit codes: 0 healthy, 1 a problem was found (alerted if SMS is configured).
"""

import argparse
import asyncio
import os
import sys
import time
from decimal import Decimal
from pathlib import Path

from src.database.models import init_database
from src.database.repository import UnitOfWork
from src.notifications import SmsNotifier


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--pid-file",
        default=None,
        help="File containing the bot's PID. Omit for a cron-driven --once bot, which has "
        "no persistent process to check - health is then judged by --log-file freshness "
        "alone (required in that case).",
    )
    parser.add_argument(
        "--symbol",
        required=True,
        help="Trading pair the bot manages, used to look up any open position",
    )
    parser.add_argument(
        "--log-file",
        default=None,
        help="Bot log file. If given, a stale log counts as a failure even when the "
        "process is technically alive - a hung bot looks identical to a healthy one "
        "from the process table alone.",
    )
    parser.add_argument(
        "--max-log-age-minutes",
        type=float,
        default=45.0,
        help="How stale the log may get before the bot is considered hung. Default 45 "
        "minutes, comfortably longer than a 15-minute poll interval.",
    )
    parser.add_argument(
        "--label",
        default=None,
        help="Name for this bot in the alert text. Defaults to the pid file's stem.",
    )
    return parser.parse_args()


def process_is_alive(pid: int) -> bool:
    """Whether `pid` exists, without requiring permission to signal it."""
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        # Exists but is owned by someone else - alive for our purposes.
        return True
    return True


def read_pid(pid_file: str) -> int | None:
    try:
        return int(Path(pid_file).read_text().strip())
    except (OSError, ValueError):
        return None


def log_age_minutes(log_file: str) -> float | None:
    try:
        return (time.time() - Path(log_file).stat().st_mtime) / 60
    except OSError:
        return None


async def open_position_amount(symbol: str) -> Decimal:
    """Size of any open position, or zero. A closed position leaves a zeroed row."""
    await init_database()
    async with UnitOfWork() as uow:
        position = await uow.positions.get_by_symbol(symbol)
        return position.amount if position and position.amount > 0 else Decimal("0")


async def main() -> int:
    args = parse_args()
    if args.pid_file is None and not args.log_file:
        raise SystemExit("--log-file is required when --pid-file is omitted")
    label = args.label or Path(args.log_file if args.pid_file is None else args.pid_file).stem

    if args.pid_file is None:
        # No persistent process to check (a cron-driven --once bot) - log
        # freshness is the only available health signal.
        pid = None
        alive = True
    else:
        pid = read_pid(args.pid_file)
        alive = pid is not None and process_is_alive(pid)

    stale_minutes: float | None = None
    if alive and args.log_file:
        age = log_age_minutes(args.log_file)
        if age is not None and age > args.max_log_age_minutes:
            stale_minutes = age

    if alive and stale_minutes is None:
        print(f"OK {label}: pid {pid} alive" if pid is not None else f"OK {label}: log fresh")
        return 0

    # Something is wrong. How bad depends entirely on whether money is exposed.
    amount = await open_position_amount(args.symbol)
    if not alive:
        problem = f"DOWN (pid {pid or 'unknown'} not running)"
    else:
        problem = f"HUNG (no log activity for {stale_minutes:.0f} min)"

    if amount > 0:
        message = (
            f"ALERT {label} is {problem} while HOLDING {amount} {args.symbol}. "
            f"Position is unmanaged - no exit signal can fire."
        )
    else:
        message = f"ALERT {label} is {problem}. No open position."

    print(message, file=sys.stderr)
    sent = await SmsNotifier().send(message)
    if not sent:
        print("(SMS not sent - alerting not configured or send failed)", file=sys.stderr)
    return 1


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
