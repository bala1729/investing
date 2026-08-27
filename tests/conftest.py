"""Shared pytest fixtures."""

from collections.abc import AsyncIterator
from pathlib import Path

import pytest

import src.database.models as models_module
from src.config import Settings


@pytest.fixture
async def db_settings(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> AsyncIterator[Settings]:
    """Point the database layer at an isolated temp-file SQLite DB for one test.

    The engine/session factory in src.database.models are module-level singletons
    keyed off get_settings(), so each test gets its own DB file and the globals
    are reset before and after to avoid leaking state between tests.
    """
    db_path = tmp_path / "test.db"
    # Also isolates journal_db_path and portfolio_equity_db_path (via env, so both
    # are picked up by every Settings(...) a test constructs, not just this one) -
    # without this, TradingEngine writes real rows into the production journal and
    # portfolio-equity files at their default paths (caught happening for both,
    # separately, each the hard way: a test run left fake trades in the real
    # journal, and separately left a stale peak_equity in the real portfolio file
    # that then made an unrelated later test miscompute a drawdown).
    monkeypatch.setenv("JOURNAL_DB_PATH", str(tmp_path / "journal.db"))
    monkeypatch.setenv("PORTFOLIO_EQUITY_DB_PATH", str(tmp_path / "portfolio_equity.db"))
    settings = Settings(_env_file=None, database_url=f"sqlite+aiosqlite:///{db_path}")

    monkeypatch.setattr(models_module, "get_settings", lambda: settings)
    models_module._engine = None
    models_module._session_factory = None

    yield settings

    await models_module.close_database()
