"""Data access layer for trading database."""

import uuid
from datetime import UTC, datetime
from decimal import Decimal
from types import TracebackType
from typing import Any

from sqlalchemy import delete, func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from src.database.models import (
    OrderRecord,
    PerformanceSnapshot,
    Position,
    Trade,
    get_session_factory,
)
from src.exchange.executor import Order, OrderStatus


class TradeRepository:
    """Repository for trade operations."""

    def __init__(self, session: AsyncSession) -> None:
        """Initialize with database session."""
        self._session = session

    async def create(
        self,
        order: Order,
        strategy: str | None = None,
        fee: Decimal = Decimal("0"),
        fee_currency: str | None = None,
    ) -> Trade:
        """Create a trade record from an executed order.

        Args:
            order: The executed order
            strategy: Strategy name that generated this trade
            fee: Trading fee
            fee_currency: Fee currency

        Returns:
            Created trade record
        """
        trade = Trade(
            trade_id=f"trade_{uuid.uuid4().hex[:12]}",
            order_id=order.id,
            exchange_trade_id=order.exchange_order_id,
            symbol=order.symbol,
            side=order.side.value,
            amount=order.filled_amount,
            price=order.average_fill_price or Decimal("0"),
            cost=order.filled_amount * (order.average_fill_price or Decimal("0")),
            fee=fee,
            fee_currency=fee_currency,
            strategy=strategy,
            is_paper=order.is_paper,
        )
        self._session.add(trade)
        await self._session.flush()
        return trade

    async def get_by_id(self, trade_id: str) -> Trade | None:
        """Get trade by ID."""
        result = await self._session.execute(
            select(Trade).where(Trade.trade_id == trade_id)
        )
        return result.scalar_one_or_none()

    async def get_by_symbol(
        self,
        symbol: str,
        limit: int = 100,
        since: datetime | None = None,
    ) -> list[Trade]:
        """Get trades for a symbol."""
        query = select(Trade).where(Trade.symbol == symbol)
        if since:
            query = query.where(Trade.created_at >= since)
        query = query.order_by(Trade.created_at.desc()).limit(limit)
        result = await self._session.execute(query)
        return list(result.scalars().all())

    async def get_recent(
        self,
        limit: int = 100,
        is_paper: bool | None = None,
    ) -> list[Trade]:
        """Get recent trades."""
        query = select(Trade)
        if is_paper is not None:
            query = query.where(Trade.is_paper == is_paper)
        query = query.order_by(Trade.created_at.desc()).limit(limit)
        result = await self._session.execute(query)
        return list(result.scalars().all())

    async def get_by_strategy(
        self,
        strategy: str,
        limit: int = 100,
    ) -> list[Trade]:
        """Get trades for a strategy."""
        result = await self._session.execute(
            select(Trade)
            .where(Trade.strategy == strategy)
            .order_by(Trade.created_at.desc())
            .limit(limit)
        )
        return list(result.scalars().all())

    async def get_trade_count(
        self,
        since: datetime | None = None,
        is_paper: bool | None = None,
    ) -> int:
        """Get total trade count."""
        query = select(func.count(Trade.id))
        if since:
            query = query.where(Trade.created_at >= since)
        if is_paper is not None:
            query = query.where(Trade.is_paper == is_paper)
        result = await self._session.execute(query)
        return result.scalar() or 0


class OrderRepository:
    """Repository for order operations."""

    def __init__(self, session: AsyncSession) -> None:
        """Initialize with database session."""
        self._session = session

    async def create(self, order: Order, strategy: str | None = None) -> OrderRecord:
        """Create an order record.

        Args:
            order: Order to persist
            strategy: Strategy name

        Returns:
            Created order record
        """
        record = OrderRecord(
            order_id=order.id,
            exchange_order_id=order.exchange_order_id,
            symbol=order.symbol,
            side=order.side.value,
            order_type=order.order_type.value,
            amount=order.amount,
            price=order.price,
            filled_amount=order.filled_amount,
            average_fill_price=order.average_fill_price,
            status=order.status.value,
            strategy=strategy,
            is_paper=order.is_paper,
            error_message=order.error_message,
        )
        self._session.add(record)
        await self._session.flush()
        return record

    async def update_status(
        self,
        order_id: str,
        status: OrderStatus,
        filled_amount: Decimal | None = None,
        average_fill_price: Decimal | None = None,
        error_message: str | None = None,
    ) -> None:
        """Update order status."""
        values: dict[str, Any] = {
            "status": status.value,
            "updated_at": datetime.now(UTC),
        }
        if filled_amount is not None:
            values["filled_amount"] = filled_amount
        if average_fill_price is not None:
            values["average_fill_price"] = average_fill_price
        if error_message is not None:
            values["error_message"] = error_message

        await self._session.execute(
            update(OrderRecord)
            .where(OrderRecord.order_id == order_id)
            .values(**values)
        )

    async def get_by_id(self, order_id: str) -> OrderRecord | None:
        """Get order by ID."""
        result = await self._session.execute(
            select(OrderRecord).where(OrderRecord.order_id == order_id)
        )
        return result.scalar_one_or_none()

    async def get_open_orders(self, symbol: str | None = None) -> list[OrderRecord]:
        """Get all open orders."""
        query = select(OrderRecord).where(
            OrderRecord.status.in_(["open", "pending", "partially_filled"])
        )
        if symbol:
            query = query.where(OrderRecord.symbol == symbol)
        result = await self._session.execute(query)
        return list(result.scalars().all())

    async def get_recent(
        self,
        limit: int = 100,
        is_paper: bool | None = None,
    ) -> list[OrderRecord]:
        """Get recent orders."""
        query = select(OrderRecord)
        if is_paper is not None:
            query = query.where(OrderRecord.is_paper == is_paper)
        query = query.order_by(OrderRecord.created_at.desc()).limit(limit)
        result = await self._session.execute(query)
        return list(result.scalars().all())


class PositionRepository:
    """Repository for position operations."""

    def __init__(self, session: AsyncSession) -> None:
        """Initialize with database session."""
        self._session = session

    async def create_or_update(
        self,
        symbol: str,
        side: str,
        amount: Decimal,
        entry_price: Decimal,
        strategy: str | None = None,
        is_paper: bool = False,
        stop_loss: Decimal | None = None,
        take_profit: Decimal | None = None,
    ) -> Position:
        """Create or update a position."""
        # Check if position exists
        existing = await self.get_by_symbol(symbol)

        if existing:
            # Update existing position
            existing.amount = amount
            existing.entry_price = entry_price
            existing.side = side
            existing.strategy = strategy
            existing.stop_loss = stop_loss
            existing.take_profit = take_profit
            await self._session.flush()
            return existing

        # Create new position
        position = Position(
            symbol=symbol,
            side=side,
            amount=amount,
            entry_price=entry_price,
            strategy=strategy,
            is_paper=is_paper,
            stop_loss=stop_loss,
            take_profit=take_profit,
        )
        self._session.add(position)
        await self._session.flush()
        return position

    async def get_by_symbol(self, symbol: str) -> Position | None:
        """Get position by symbol."""
        result = await self._session.execute(
            select(Position).where(Position.symbol == symbol)
        )
        return result.scalar_one_or_none()

    async def get_all_open(self, is_paper: bool | None = None) -> list[Position]:
        """Get all open positions."""
        query = select(Position).where(Position.amount > 0)
        if is_paper is not None:
            query = query.where(Position.is_paper == is_paper)
        result = await self._session.execute(query)
        return list(result.scalars().all())

    async def update_price(
        self,
        symbol: str,
        current_price: Decimal,
    ) -> None:
        """Update current price and calculate unrealized P&L."""
        position = await self.get_by_symbol(symbol)
        if position:
            position.current_price = current_price
            if position.side == "long":
                position.unrealized_pnl = (
                    current_price - position.entry_price
                ) * position.amount
            else:
                position.unrealized_pnl = (
                    position.entry_price - current_price
                ) * position.amount

    async def raise_stop_loss(self, symbol: str, stop_loss: Decimal) -> bool:
        """Move a position's stop-loss up to `stop_loss`, never down.

        Returns True if the stop was actually raised, so callers can act only on
        a real change - a native stop order should be cancelled and replaced
        only when the price it rests at has moved.

        The position's stop_loss column doubles as the trailing ratchet's
        memory: once raised it stays raised, so a bot restart cannot forget that
        the trigger was already reached and drop the stop back to its opening
        level. That is why no separate high-water-mark column is needed.
        """
        position = await self.get_by_symbol(symbol)
        if position is None or position.amount <= 0:
            return False
        if position.stop_loss is not None and stop_loss <= position.stop_loss:
            return False
        position.stop_loss = stop_loss
        return True

    async def close_position(
        self,
        symbol: str,
        exit_price: Decimal,
    ) -> Position | None:
        """Close a position and calculate realized P&L."""
        position = await self.get_by_symbol(symbol)
        if position:
            if position.side == "long":
                pnl = (exit_price - position.entry_price) * position.amount
            else:
                pnl = (position.entry_price - exit_price) * position.amount

            position.realized_pnl = pnl
            position.unrealized_pnl = Decimal("0")
            position.amount = Decimal("0")
            position.current_price = exit_price
            return position
        return None

    async def delete(self, symbol: str) -> None:
        """Delete a position."""
        await self._session.execute(
            delete(Position).where(Position.symbol == symbol)
        )


class PerformanceRepository:
    """Repository for performance tracking."""

    def __init__(self, session: AsyncSession) -> None:
        """Initialize with database session."""
        self._session = session

    async def create_snapshot(
        self,
        total_balance_usd: Decimal,
        daily_pnl: Decimal = Decimal("0"),
        cumulative_pnl: Decimal = Decimal("0"),
        total_trades: int = 0,
        winning_trades: int = 0,
        losing_trades: int = 0,
        max_drawdown_pct: Decimal = Decimal("0"),
        is_paper: bool = False,
    ) -> PerformanceSnapshot:
        """Create a performance snapshot."""
        snapshot = PerformanceSnapshot(
            snapshot_date=datetime.now(UTC),
            total_balance_usd=total_balance_usd,
            daily_pnl=daily_pnl,
            cumulative_pnl=cumulative_pnl,
            total_trades=total_trades,
            winning_trades=winning_trades,
            losing_trades=losing_trades,
            max_drawdown_pct=max_drawdown_pct,
            is_paper=is_paper,
        )
        self._session.add(snapshot)
        await self._session.flush()
        return snapshot

    async def get_latest(self, is_paper: bool | None = None) -> PerformanceSnapshot | None:
        """Get the most recent snapshot."""
        query = select(PerformanceSnapshot)
        if is_paper is not None:
            query = query.where(PerformanceSnapshot.is_paper == is_paper)
        query = query.order_by(PerformanceSnapshot.snapshot_date.desc()).limit(1)
        result = await self._session.execute(query)
        return result.scalar_one_or_none()

    async def get_history(
        self,
        days: int = 30,
        is_paper: bool | None = None,
    ) -> list[PerformanceSnapshot]:
        """Get performance history."""
        query = select(PerformanceSnapshot)
        if is_paper is not None:
            query = query.where(PerformanceSnapshot.is_paper == is_paper)
        query = query.order_by(PerformanceSnapshot.snapshot_date.desc()).limit(days)
        result = await self._session.execute(query)
        return list(result.scalars().all())


class UnitOfWork:
    """Unit of Work pattern for database transactions."""

    def __init__(self) -> None:
        """Initialize unit of work."""
        self._session: AsyncSession | None = None
        self._trades: TradeRepository | None = None
        self._orders: OrderRepository | None = None
        self._positions: PositionRepository | None = None
        self._performance: PerformanceRepository | None = None

    async def __aenter__(self) -> "UnitOfWork":
        """Enter async context."""
        session_factory = await get_session_factory()
        self._session = session_factory()
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc_val: BaseException | None,
        exc_tb: TracebackType | None,
    ) -> None:
        """Exit async context."""
        if self._session:
            if exc_type:
                await self._session.rollback()
            await self._session.close()

    @property
    def trades(self) -> TradeRepository:
        """Get trades repository."""
        if self._session is None:
            raise RuntimeError("UnitOfWork not initialized")
        if self._trades is None:
            self._trades = TradeRepository(self._session)
        return self._trades

    @property
    def orders(self) -> OrderRepository:
        """Get orders repository."""
        if self._session is None:
            raise RuntimeError("UnitOfWork not initialized")
        if self._orders is None:
            self._orders = OrderRepository(self._session)
        return self._orders

    @property
    def positions(self) -> PositionRepository:
        """Get positions repository."""
        if self._session is None:
            raise RuntimeError("UnitOfWork not initialized")
        if self._positions is None:
            self._positions = PositionRepository(self._session)
        return self._positions

    @property
    def performance(self) -> PerformanceRepository:
        """Get performance repository."""
        if self._session is None:
            raise RuntimeError("UnitOfWork not initialized")
        if self._performance is None:
            self._performance = PerformanceRepository(self._session)
        return self._performance

    async def commit(self) -> None:
        """Commit the transaction."""
        if self._session:
            await self._session.commit()

    async def rollback(self) -> None:
        """Rollback the transaction."""
        if self._session:
            await self._session.rollback()
