"""Tests for repositories and the UnitOfWork pattern."""

from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest

from src.config import Settings
from src.database.models import init_database
from src.database.repository import UnitOfWork
from src.exchange.executor import Order, OrderSide, OrderStatus, OrderType


def make_order(
    order_id: str = "order_1",
    status: OrderStatus = OrderStatus.FILLED,
    side: OrderSide = OrderSide.BUY,
    filled_amount: Decimal = Decimal("0.01"),
    average_fill_price: Decimal | None = Decimal("45000"),
    is_paper: bool = True,
) -> Order:
    return Order(
        id=order_id,
        symbol="BTC/USD",
        side=side,
        order_type=OrderType.MARKET,
        amount=Decimal("0.01"),
        price=None,
        status=status,
        filled_amount=filled_amount,
        average_fill_price=average_fill_price,
        exchange_order_id="ex_1",
        is_paper=is_paper,
    )


@pytest.fixture(autouse=True)
async def _init_db(db_settings: Settings) -> None:
    await init_database()


class TestTradeRepository:
    async def test_create_and_get_by_id(self) -> None:
        async with UnitOfWork() as uow:
            created = await uow.trades.create(make_order(), strategy="momentum")
            await uow.commit()

        async with UnitOfWork() as uow:
            found = await uow.trades.get_by_id(created.trade_id)

        assert found is not None
        assert found.order_id == "order_1"
        assert found.strategy == "momentum"
        assert found.cost == Decimal("0.01") * Decimal("45000")

    async def test_create_defaults_price_when_no_fill_price(self) -> None:
        order = make_order(average_fill_price=None)
        async with UnitOfWork() as uow:
            trade = await uow.trades.create(order)
            await uow.commit()

        assert trade.price == Decimal("0")
        assert trade.cost == Decimal("0")

    async def test_get_by_id_missing_returns_none(self) -> None:
        async with UnitOfWork() as uow:
            assert await uow.trades.get_by_id("nope") is None

    async def test_get_by_symbol_filters_and_orders(self) -> None:
        async with UnitOfWork() as uow:
            await uow.trades.create(make_order("o1"))
            await uow.trades.create(make_order("o2"))
            await uow.commit()

        async with UnitOfWork() as uow:
            results = await uow.trades.get_by_symbol("BTC/USD")
            assert len(results) == 2

            none_results = await uow.trades.get_by_symbol("ETH/USD")
            assert none_results == []

    async def test_get_by_symbol_since_filter(self) -> None:
        async with UnitOfWork() as uow:
            await uow.trades.create(make_order("o1"))
            await uow.commit()

        future = datetime.now(UTC) + timedelta(days=1)
        async with UnitOfWork() as uow:
            results = await uow.trades.get_by_symbol("BTC/USD", since=future)
            assert results == []

    async def test_get_recent_filters_by_paper_flag(self) -> None:
        async with UnitOfWork() as uow:
            await uow.trades.create(make_order("o1", is_paper=True))
            await uow.trades.create(make_order("o2", is_paper=False))
            await uow.commit()

        async with UnitOfWork() as uow:
            paper_only = await uow.trades.get_recent(is_paper=True)
            all_trades = await uow.trades.get_recent()

        assert len(paper_only) == 1
        assert len(all_trades) == 2

    async def test_get_by_strategy(self) -> None:
        async with UnitOfWork() as uow:
            await uow.trades.create(make_order("o1"), strategy="momentum")
            await uow.trades.create(make_order("o2"), strategy="mean_reversion")
            await uow.commit()

        async with UnitOfWork() as uow:
            results = await uow.trades.get_by_strategy("momentum")

        assert len(results) == 1
        assert results[0].strategy == "momentum"

    async def test_get_trade_count(self) -> None:
        async with UnitOfWork() as uow:
            await uow.trades.create(make_order("o1", is_paper=True))
            await uow.trades.create(make_order("o2", is_paper=False))
            await uow.commit()

        async with UnitOfWork() as uow:
            assert await uow.trades.get_trade_count() == 2
            assert await uow.trades.get_trade_count(is_paper=True) == 1

        future = datetime.now(UTC) + timedelta(days=1)
        async with UnitOfWork() as uow:
            assert await uow.trades.get_trade_count(since=future) == 0


class TestOrderRepository:
    async def test_create_and_get_by_id(self) -> None:
        async with UnitOfWork() as uow:
            await uow.orders.create(make_order(), strategy="momentum")
            await uow.commit()

        async with UnitOfWork() as uow:
            found = await uow.orders.get_by_id("order_1")

        assert found is not None
        assert found.status == "filled"

    async def test_get_by_id_missing_returns_none(self) -> None:
        async with UnitOfWork() as uow:
            assert await uow.orders.get_by_id("nope") is None

    async def test_update_status_sets_all_optional_fields(self) -> None:
        async with UnitOfWork() as uow:
            await uow.orders.create(make_order("o1", status=OrderStatus.OPEN))
            await uow.commit()

        async with UnitOfWork() as uow:
            await uow.orders.update_status(
                "o1",
                OrderStatus.FILLED,
                filled_amount=Decimal("0.01"),
                average_fill_price=Decimal("46000"),
                error_message="none",
            )
            await uow.commit()

        async with UnitOfWork() as uow:
            record = await uow.orders.get_by_id("o1")

        assert record is not None
        assert record.status == "filled"
        assert record.filled_amount == Decimal("0.01")
        assert record.average_fill_price == Decimal("46000")

    async def test_update_status_minimal(self) -> None:
        async with UnitOfWork() as uow:
            await uow.orders.create(make_order("o1", status=OrderStatus.OPEN))
            await uow.commit()

        async with UnitOfWork() as uow:
            await uow.orders.update_status("o1", OrderStatus.CANCELLED)
            await uow.commit()

        async with UnitOfWork() as uow:
            record = await uow.orders.get_by_id("o1")

        assert record is not None
        assert record.status == "cancelled"

    async def test_get_open_orders_filters_status_and_symbol(self) -> None:
        async with UnitOfWork() as uow:
            await uow.orders.create(make_order("o1", status=OrderStatus.OPEN))
            await uow.orders.create(make_order("o2", status=OrderStatus.FILLED))
            await uow.commit()

        async with UnitOfWork() as uow:
            open_orders = await uow.orders.get_open_orders()
            assert len(open_orders) == 1

            filtered = await uow.orders.get_open_orders(symbol="BTC/USD")
            assert len(filtered) == 1

            none_for_other_symbol = await uow.orders.get_open_orders(symbol="ETH/USD")
            assert none_for_other_symbol == []

    async def test_get_recent_filters_by_paper_flag(self) -> None:
        async with UnitOfWork() as uow:
            await uow.orders.create(make_order("o1", is_paper=True))
            await uow.orders.create(make_order("o2", is_paper=False))
            await uow.commit()

        async with UnitOfWork() as uow:
            paper_only = await uow.orders.get_recent(is_paper=True)
            all_orders = await uow.orders.get_recent()

        assert len(paper_only) == 1
        assert len(all_orders) == 2


class TestPositionRepository:
    async def test_create_new_position(self) -> None:
        async with UnitOfWork() as uow:
            position = await uow.positions.create_or_update(
                symbol="BTC/USD",
                side="long",
                amount=Decimal("0.1"),
                entry_price=Decimal("40000"),
                strategy="momentum",
                is_paper=True,
                stop_loss=Decimal("38000"),
                take_profit=Decimal("50000"),
            )
            await uow.commit()

        assert position.symbol == "BTC/USD"
        assert position.stop_loss == Decimal("38000")

    async def test_create_or_update_updates_existing(self) -> None:
        async with UnitOfWork() as uow:
            await uow.positions.create_or_update(
                symbol="BTC/USD", side="long", amount=Decimal("0.1"), entry_price=Decimal("40000")
            )
            await uow.commit()

        async with UnitOfWork() as uow:
            updated = await uow.positions.create_or_update(
                symbol="BTC/USD", side="long", amount=Decimal("0.2"), entry_price=Decimal("41000")
            )
            await uow.commit()

        assert updated.amount == Decimal("0.2")
        assert updated.entry_price == Decimal("41000")

        async with UnitOfWork() as uow:
            all_positions = await uow.positions.get_all_open()
        assert len(all_positions) == 1

    async def test_get_by_symbol_missing_returns_none(self) -> None:
        async with UnitOfWork() as uow:
            assert await uow.positions.get_by_symbol("BTC/USD") is None

    async def test_get_all_open_filters_by_amount_and_paper(self) -> None:
        async with UnitOfWork() as uow:
            await uow.positions.create_or_update(
                symbol="BTC/USD",
                side="long",
                amount=Decimal("0.1"),
                entry_price=Decimal("40000"),
                is_paper=True,
            )
            await uow.positions.create_or_update(
                symbol="ETH/USD",
                side="long",
                amount=Decimal("0"),
                entry_price=Decimal("2000"),
                is_paper=False,
            )
            await uow.commit()

        async with UnitOfWork() as uow:
            open_positions = await uow.positions.get_all_open()
            paper_positions = await uow.positions.get_all_open(is_paper=True)

        assert len(open_positions) == 1
        assert len(paper_positions) == 1

    async def test_update_price_long_position(self) -> None:
        async with UnitOfWork() as uow:
            await uow.positions.create_or_update(
                symbol="BTC/USD", side="long", amount=Decimal("1"), entry_price=Decimal("40000")
            )
            await uow.commit()

        async with UnitOfWork() as uow:
            await uow.positions.update_price("BTC/USD", Decimal("45000"))
            await uow.commit()

        async with UnitOfWork() as uow:
            position = await uow.positions.get_by_symbol("BTC/USD")

        assert position is not None
        assert position.unrealized_pnl == Decimal("5000")

    async def test_update_price_short_position(self) -> None:
        async with UnitOfWork() as uow:
            await uow.positions.create_or_update(
                symbol="BTC/USD", side="short", amount=Decimal("1"), entry_price=Decimal("40000")
            )
            await uow.commit()

        async with UnitOfWork() as uow:
            await uow.positions.update_price("BTC/USD", Decimal("35000"))
            await uow.commit()

        async with UnitOfWork() as uow:
            position = await uow.positions.get_by_symbol("BTC/USD")

        assert position is not None
        assert position.unrealized_pnl == Decimal("5000")

    async def test_update_price_missing_position_is_a_no_op(self) -> None:
        async with UnitOfWork() as uow:
            await uow.positions.update_price("BTC/USD", Decimal("45000"))  # should not raise

    async def test_close_position_long(self) -> None:
        async with UnitOfWork() as uow:
            await uow.positions.create_or_update(
                symbol="BTC/USD", side="long", amount=Decimal("1"), entry_price=Decimal("40000")
            )
            await uow.commit()

        async with UnitOfWork() as uow:
            closed = await uow.positions.close_position("BTC/USD", Decimal("45000"))
            await uow.commit()

        assert closed is not None
        assert closed.realized_pnl == Decimal("5000")
        assert closed.amount == Decimal("0")

    async def test_close_position_short(self) -> None:
        async with UnitOfWork() as uow:
            await uow.positions.create_or_update(
                symbol="BTC/USD", side="short", amount=Decimal("1"), entry_price=Decimal("40000")
            )
            await uow.commit()

        async with UnitOfWork() as uow:
            closed = await uow.positions.close_position("BTC/USD", Decimal("35000"))
            await uow.commit()

        assert closed is not None
        assert closed.realized_pnl == Decimal("5000")

    async def test_close_position_missing_returns_none(self) -> None:
        async with UnitOfWork() as uow:
            assert await uow.positions.close_position("BTC/USD", Decimal("45000")) is None

    async def test_reduce_position_long_decrements_amount_and_accumulates_pnl(self) -> None:
        async with UnitOfWork() as uow:
            await uow.positions.create_or_update(
                symbol="BTC/USD", side="long", amount=Decimal("1"), entry_price=Decimal("40000")
            )
            await uow.commit()

        async with UnitOfWork() as uow:
            reduced = await uow.positions.reduce_position(
                "BTC/USD", sold_amount=Decimal("0.3"), exit_price=Decimal("45000")
            )
            await uow.commit()

        assert reduced is not None
        assert reduced.amount == Decimal("0.7")
        assert reduced.realized_pnl == Decimal("1500")  # (45000 - 40000) * 0.3
        assert reduced.entry_price == Decimal("40000")  # unchanged for the remainder

        # A second reduction accumulates rather than overwriting realized_pnl.
        async with UnitOfWork() as uow:
            reduced_again = await uow.positions.reduce_position(
                "BTC/USD", sold_amount=Decimal("0.2"), exit_price=Decimal("46000")
            )
            await uow.commit()

        assert reduced_again is not None
        assert reduced_again.amount == Decimal("0.5")
        assert reduced_again.realized_pnl == Decimal("2700")  # 1500 + (46000-40000)*0.2

    async def test_reduce_position_short_mirrors_pnl_sign(self) -> None:
        async with UnitOfWork() as uow:
            await uow.positions.create_or_update(
                symbol="BTC/USD", side="short", amount=Decimal("1"), entry_price=Decimal("40000")
            )
            await uow.commit()

        async with UnitOfWork() as uow:
            reduced = await uow.positions.reduce_position(
                "BTC/USD", sold_amount=Decimal("0.4"), exit_price=Decimal("35000")
            )
            await uow.commit()

        assert reduced is not None
        assert reduced.realized_pnl == Decimal("2000")  # (40000 - 35000) * 0.4

    async def test_reduce_position_leaves_stop_and_target_untouched(self) -> None:
        async with UnitOfWork() as uow:
            await uow.positions.create_or_update(
                symbol="BTC/USD",
                side="long",
                amount=Decimal("1"),
                entry_price=Decimal("40000"),
                stop_loss=Decimal("38000"),
                take_profit=Decimal("50000"),
            )
            await uow.commit()

        async with UnitOfWork() as uow:
            reduced = await uow.positions.reduce_position(
                "BTC/USD", sold_amount=Decimal("0.5"), exit_price=Decimal("45000")
            )
            await uow.commit()

        assert reduced is not None
        assert reduced.stop_loss == Decimal("38000")
        assert reduced.take_profit == Decimal("50000")

    async def test_reduce_position_can_clear_stop_loss_and_take_profit(self) -> None:
        """The flags a stop/target-triggered reduction passes to avoid re-firing on the
        remainder every cycle - see PositionRepository.reduce_position's docstring."""
        async with UnitOfWork() as uow:
            await uow.positions.create_or_update(
                symbol="BTC/USD",
                side="long",
                amount=Decimal("1"),
                entry_price=Decimal("40000"),
                stop_loss=Decimal("38000"),
                take_profit=Decimal("50000"),
            )
            await uow.commit()

        async with UnitOfWork() as uow:
            reduced = await uow.positions.reduce_position(
                "BTC/USD",
                sold_amount=Decimal("0.5"),
                exit_price=Decimal("45000"),
                clear_stop_loss=True,
                clear_take_profit=True,
            )
            await uow.commit()

        assert reduced is not None
        assert reduced.stop_loss is None
        assert reduced.take_profit is None

    async def test_reduce_position_missing_returns_none(self) -> None:
        async with UnitOfWork() as uow:
            result = await uow.positions.reduce_position(
                "BTC/USD", sold_amount=Decimal("0.1"), exit_price=Decimal("45000")
            )
            assert result is None

    async def test_delete_position(self) -> None:
        async with UnitOfWork() as uow:
            await uow.positions.create_or_update(
                symbol="BTC/USD", side="long", amount=Decimal("1"), entry_price=Decimal("40000")
            )
            await uow.commit()

        async with UnitOfWork() as uow:
            await uow.positions.delete("BTC/USD")
            await uow.commit()

        async with UnitOfWork() as uow:
            assert await uow.positions.get_by_symbol("BTC/USD") is None


class TestPerformanceRepository:
    async def test_create_snapshot_and_get_latest(self) -> None:
        async with UnitOfWork() as uow:
            await uow.performance.create_snapshot(
                total_balance_usd=Decimal("10000"),
                daily_pnl=Decimal("100"),
                cumulative_pnl=Decimal("100"),
                total_trades=1,
                winning_trades=1,
                losing_trades=0,
                max_drawdown_pct=Decimal("0"),
                is_paper=True,
            )
            await uow.commit()

        async with UnitOfWork() as uow:
            latest = await uow.performance.get_latest()
            latest_paper = await uow.performance.get_latest(is_paper=True)

        assert latest is not None
        assert latest.total_balance_usd == Decimal("10000")
        assert latest_paper is not None

    async def test_get_latest_returns_none_when_empty(self) -> None:
        async with UnitOfWork() as uow:
            assert await uow.performance.get_latest() is None

    async def test_get_history_respects_days_limit(self) -> None:
        async with UnitOfWork() as uow:
            for _ in range(3):
                await uow.performance.create_snapshot(total_balance_usd=Decimal("10000"))
            await uow.commit()

        async with UnitOfWork() as uow:
            history = await uow.performance.get_history(days=2)
            paper_history = await uow.performance.get_history(is_paper=True)

        assert len(history) == 2
        assert paper_history == []


class TestUnitOfWork:
    async def test_repository_properties_are_cached(self) -> None:
        async with UnitOfWork() as uow:
            assert uow.trades is uow.trades
            assert uow.orders is uow.orders
            assert uow.positions is uow.positions
            assert uow.performance is uow.performance

    async def test_repository_access_before_enter_raises(self) -> None:
        uow = UnitOfWork()
        with pytest.raises(RuntimeError, match="not initialized"):
            _ = uow.trades
        with pytest.raises(RuntimeError, match="not initialized"):
            _ = uow.orders
        with pytest.raises(RuntimeError, match="not initialized"):
            _ = uow.positions
        with pytest.raises(RuntimeError, match="not initialized"):
            _ = uow.performance

    async def test_exception_inside_context_triggers_rollback(self) -> None:
        with pytest.raises(ValueError):
            async with UnitOfWork() as uow:
                await uow.trades.create(make_order())
                raise ValueError("boom")

        async with UnitOfWork() as uow:
            assert await uow.trades.get_by_id("trade_1") is None

    async def test_rollback_without_session_is_a_no_op(self) -> None:
        uow = UnitOfWork()
        await uow.rollback()  # should not raise

    async def test_commit_without_session_is_a_no_op(self) -> None:
        uow = UnitOfWork()
        await uow.commit()  # should not raise

    async def test_explicit_rollback(self) -> None:
        async with UnitOfWork() as uow:
            await uow.orders.create(make_order("o1"))
            await uow.rollback()

        async with UnitOfWork() as uow:
            assert await uow.orders.get_by_id("o1") is None
