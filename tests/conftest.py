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
    # Also isolates journal_db_path (via env, so it's picked up by every Settings(...)
    # a test constructs, not just this one) - without it, TradingEngine._record_journal
    # writes real rows into the production journal at its default path.
    monkeypatch.setenv("JOURNAL_DB_PATH", str(tmp_path / "journal.db"))
    settings = Settings(_env_file=None, database_url=f"sqlite+aiosqlite:///{db_path}")

    monkeypatch.setattr(models_module, "get_settings", lambda: settings)
    models_module._engine = None
    models_module._session_factory = None

    yield settings

    await models_module.close_database()
