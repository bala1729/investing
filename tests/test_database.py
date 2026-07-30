"""Tests for the database engine/session plumbing and ORM model to_dict()."""

from datetime import UTC, datetime
from decimal import Decimal

from sqlalchemy import text

import src.database.models as models_module
from src.config import Settings
from src.database.models import (
    OrderRecord,
    PerformanceSnapshot,
    Position,
    Trade,
    close_database,
    get_engine,
    get_session_factory,
    init_database,
)


class TestEngineAndSessionFactory:
    """Tests for get_engine() / get_session_factory() caching and init/close."""

    async def test_get_engine_returns_cached_instance(self, db_settings: Settings) -> None:
        first = await get_engine()
        second = await get_engine()
        assert first is second

    async def test_get_session_factory_returns_cached_instance(
        self, db_settings: Settings
    ) -> None:
        first = await get_session_factory()
        second = await get_session_factory()
        assert first is second

    async def test_init_database_creates_expected_tables(self, db_settings: Settings) -> None:
        await init_database()
        session_factory = await get_session_factory()

        async with session_factory() as session:
            result = await session.execute(
                text("SELECT name FROM sqlite_master WHERE type='table'")
            )
            tables = {row[0] for row in result.all()}

        assert {"trades", "orders", "positions", "performance_snapshots"} <= tables

    async def test_close_database_resets_globals(self, db_settings: Settings) -> None:
        await init_database()
        await close_database()

        assert models_module._engine is None
        assert models_module._session_factory is None

    async def test_close_database_without_init_is_a_no_op(self, db_settings: Settings) -> None:
        await close_database()  # should not raise


class TestTradeToDict:
    def test_to_dict(self) -> None:
        trade = Trade(
            id=1,
            trade_id="trade_1",
            order_id="order_1",
            exchange_trade_id="ex_1",
            symbol="BTC/USD",
            side="buy",
            amount=Decimal("0.01"),
            price=Decimal("45000"),
            cost=Decimal("450"),
            fee=Decimal("0.5"),
            fee_currency="USD",
            strategy="momentum",
            is_paper=True,
            created_at=datetime(2026, 1, 1, tzinfo=UTC),
        )
        data = trade.to_dict()
        assert data["trade_id"] == "trade_1"
        assert data["amount"] == "0.01"
        assert data["is_paper"] is True
        assert data["created_at"] == "2026-01-01T00:00:00+00:00"


class TestOrderRecordToDict:
    def test_to_dict_with_price(self) -> None:
        record = OrderRecord(
            id=1,
            order_id="order_1",
            exchange_order_id="ex_1",
            symbol="BTC/USD",
            side="buy",
            order_type="limit",
            amount=Decimal("0.01"),
            price=Decimal("45000"),
            filled_amount=Decimal("0"),
            average_fill_price=None,
            status="open",
            strategy=None,
            is_paper=True,
            error_message=None,
            created_at=datetime(2026, 1, 1, tzinfo=UTC),
            updated_at=datetime(2026, 1, 1, tzinfo=UTC),
        )
        data = record.to_dict()
        assert data["price"] == "45000"
        assert data["average_fill_price"] is None

    def test_to_dict_without_price(self) -> None:
        record = OrderRecord(
            id=1,
            order_id="order_1",
            exchange_order_id=None,
            symbol="BTC/USD",
            side="buy",
            order_type="market",
            amount=Decimal("0.01"),
            price=None,
            filled_amount=Decimal("0.01"),
            average_fill_price=Decimal("45000"),
            status="filled",
            strategy=None,
            is_paper=True,
            error_message=None,
            created_at=datetime(2026, 1, 1, tzinfo=UTC),
            updated_at=datetime(2026, 1, 1, tzinfo=UTC),
        )
        data = record.to_dict()
        assert data["price"] is None
        assert data["average_fill_price"] == "45000"


class TestPositionToDict:
    def test_to_dict(self) -> None:
        position = Position(
            id=1,
            symbol="BTC/USD",
            side="long",
            amount=Decimal("0.1"),
            entry_price=Decimal("40000"),
            current_price=Decimal("45000"),
            unrealized_pnl=Decimal("500"),
            realized_pnl=Decimal("0"),
            stop_loss=Decimal("38000"),
            take_profit=Decimal("50000"),
            strategy="momentum",
            is_paper=True,
            opened_at=datetime(2026, 1, 1, tzinfo=UTC),
            updated_at=datetime(2026, 1, 1, tzinfo=UTC),
        )
        data = position.to_dict()
        assert data["symbol"] == "BTC/USD"
        assert data["current_price"] == "45000"
        assert data["stop_loss"] == "38000"


class TestPerformanceSnapshotToDict:
    def test_to_dict(self) -> None:
        snapshot = PerformanceSnapshot(
            id=1,
            snapshot_date=datetime(2026, 1, 1, tzinfo=UTC),
            total_balance_usd=Decimal("10500.00"),
            daily_pnl=Decimal("500.00"),
            cumulative_pnl=Decimal("500.00"),
            total_trades=3,
            winning_trades=2,
            losing_trades=1,
            max_drawdown_pct=Decimal("1.50"),
            is_paper=True,
            created_at=datetime(2026, 1, 1, tzinfo=UTC),
        )
        data = snapshot.to_dict()
        assert data["total_balance_usd"] == "10500.00"
        assert data["total_trades"] == 3
        assert data["is_paper"] is True
