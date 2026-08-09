"""SQLAlchemy database models for trade persistence."""

from datetime import UTC, datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import (
    Boolean,
    DateTime,
    Index,
    Numeric,
    String,
    Text,
)
from sqlalchemy.ext.asyncio import (
    AsyncAttrs,
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

from src.config import get_settings


class Base(AsyncAttrs, DeclarativeBase):
    """Base class for all database models."""

    pass


class Trade(Base):
    """Trade record model."""

    __tablename__ = "trades"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    trade_id: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    order_id: Mapped[str] = mapped_column(String(64), index=True)
    exchange_trade_id: Mapped[str | None] = mapped_column(String(128))

    symbol: Mapped[str] = mapped_column(String(32), index=True)
    side: Mapped[str] = mapped_column(String(10))
    amount: Mapped[Decimal] = mapped_column(Numeric(precision=18, scale=8))
    price: Mapped[Decimal] = mapped_column(Numeric(precision=18, scale=8))
    cost: Mapped[Decimal] = mapped_column(Numeric(precision=18, scale=8))
    fee: Mapped[Decimal] = mapped_column(Numeric(precision=18, scale=8), default=Decimal("0"))
    fee_currency: Mapped[str | None] = mapped_column(String(10))

    strategy: Mapped[str | None] = mapped_column(String(64))
    is_paper: Mapped[bool] = mapped_column(Boolean, default=False)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(UTC),
        index=True,
    )

    __table_args__ = (
        Index("ix_trades_symbol_created", "symbol", "created_at"),
    )

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary."""
        return {
            "id": self.id,
            "trade_id": self.trade_id,
            "order_id": self.order_id,
            "exchange_trade_id": self.exchange_trade_id,
            "symbol": self.symbol,
            "side": self.side,
            "amount": str(self.amount),
            "price": str(self.price),
            "cost": str(self.cost),
            "fee": str(self.fee),
            "fee_currency": self.fee_currency,
            "strategy": self.strategy,
            "is_paper": self.is_paper,
            "created_at": self.created_at.isoformat(),
        }


class OrderRecord(Base):
    """Order record model for tracking order history."""

    __tablename__ = "orders"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    order_id: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    exchange_order_id: Mapped[str | None] = mapped_column(String(128))

    symbol: Mapped[str] = mapped_column(String(32), index=True)
    side: Mapped[str] = mapped_column(String(10))
    order_type: Mapped[str] = mapped_column(String(20))
    amount: Mapped[Decimal] = mapped_column(Numeric(precision=18, scale=8))
    price: Mapped[Decimal | None] = mapped_column(Numeric(precision=18, scale=8))
    filled_amount: Mapped[Decimal] = mapped_column(
        Numeric(precision=18, scale=8), default=Decimal("0")
    )
    average_fill_price: Mapped[Decimal | None] = mapped_column(Numeric(precision=18, scale=8))

    status: Mapped[str] = mapped_column(String(20), index=True)
    strategy: Mapped[str | None] = mapped_column(String(64))
    is_paper: Mapped[bool] = mapped_column(Boolean, default=False)
    error_message: Mapped[str | None] = mapped_column(Text)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(UTC),
        index=True,
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(UTC),
        onupdate=lambda: datetime.now(UTC),
    )

    __table_args__ = (
        Index("ix_orders_symbol_status", "symbol", "status"),
    )

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary."""
        return {
            "id": self.id,
            "order_id": self.order_id,
            "exchange_order_id": self.exchange_order_id,
            "symbol": self.symbol,
            "side": self.side,
            "order_type": self.order_type,
            "amount": str(self.amount),
            "price": str(self.price) if self.price else None,
            "filled_amount": str(self.filled_amount),
            "average_fill_price": str(self.average_fill_price) if self.average_fill_price else None,
            "status": self.status,
            "strategy": self.strategy,
            "is_paper": self.is_paper,
            "error_message": self.error_message,
            "created_at": self.created_at.isoformat(),
            "updated_at": self.updated_at.isoformat(),
        }


class Position(Base):
    """Position tracking model."""

    __tablename__ = "positions"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    symbol: Mapped[str] = mapped_column(String(32), unique=True, index=True)

    side: Mapped[str] = mapped_column(String(10))  # long/short
    amount: Mapped[Decimal] = mapped_column(Numeric(precision=18, scale=8))
    entry_price: Mapped[Decimal] = mapped_column(Numeric(precision=18, scale=8))
    current_price: Mapped[Decimal | None] = mapped_column(Numeric(precision=18, scale=8))

    unrealized_pnl: Mapped[Decimal] = mapped_column(
        Numeric(precision=18, scale=8), default=Decimal("0")
    )
    realized_pnl: Mapped[Decimal] = mapped_column(
        Numeric(precision=18, scale=8), default=Decimal("0")
    )

    stop_loss: Mapped[Decimal | None] = mapped_column(Numeric(precision=18, scale=8))
    take_profit: Mapped[Decimal | None] = mapped_column(Numeric(precision=18, scale=8))

    strategy: Mapped[str | None] = mapped_column(String(64))
    is_paper: Mapped[bool] = mapped_column(Boolean, default=False)

    opened_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(UTC),
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(UTC),
        onupdate=lambda: datetime.now(UTC),
    )

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary."""
        return {
            "id": self.id,
            "symbol": self.symbol,
            "side": self.side,
            "amount": str(self.amount),
            "entry_price": str(self.entry_price),
            "current_price": str(self.current_price) if self.current_price else None,
            "unrealized_pnl": str(self.unrealized_pnl),
            "realized_pnl": str(self.realized_pnl),
            "stop_loss": str(self.stop_loss) if self.stop_loss else None,
            "take_profit": str(self.take_profit) if self.take_profit else None,
            "strategy": self.strategy,
            "is_paper": self.is_paper,
            "opened_at": self.opened_at.isoformat(),
            "updated_at": self.updated_at.isoformat(),
        }


class PeakEquity(Base):
    """Per-symbol high-water mark of account equity, used for drawdown limits.

    A separate table rather than a column on Position because it must outlive
    any individual position: the drawdown limit is meant to measure the decline
    from the best the account has ever been, and a position row is zeroed the
    moment a trade closes.

    Persisting this at all is the point. It used to live in a dict on
    TradingEngine, so every restart reset the high-water mark to whatever equity
    happened to be at that moment - which silently disarmed max_drawdown_pct
    exactly when it mattered, since a bot is most likely to be restarted after
    something went wrong.

    New table rather than a new column, so create_all() adds it to existing
    databases without a migration.
    """

    __tablename__ = "peak_equity"

    symbol: Mapped[str] = mapped_column(String(32), primary_key=True)
    peak_equity: Mapped[Decimal] = mapped_column(Numeric(precision=18, scale=8))
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(UTC),
        onupdate=lambda: datetime.now(UTC),
    )

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary."""
        return {
            "symbol": self.symbol,
            "peak_equity": str(self.peak_equity),
            "updated_at": self.updated_at.isoformat(),
        }


class PaperBalance(Base):
    """Persisted paper-trading balances, so a restart resumes rather than resets.

    PaperTradingSimulator held these in memory, which quietly broke restarts as
    soon as a bot held a position: the database still showed the open position,
    but the simulator came back with the starting cash and no base currency. The
    engine clamps a sell to `min(position.amount, executor balance)`, so that
    orphaned the position - it could never be sold, and the bot would sit on an
    unsellable holding indefinitely.

    Keyed by currency rather than symbol because balances are per-asset: one
    USD row funds every pair the bot trades.
    """

    __tablename__ = "paper_balances"

    currency: Mapped[str] = mapped_column(String(16), primary_key=True)
    amount: Mapped[Decimal] = mapped_column(Numeric(precision=28, scale=12))
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(UTC),
        onupdate=lambda: datetime.now(UTC),
    )

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary."""
        return {
            "currency": self.currency,
            "amount": str(self.amount),
            "updated_at": self.updated_at.isoformat(),
        }


class PerformanceSnapshot(Base):
    """Daily performance snapshot for tracking P&L over time."""

    __tablename__ = "performance_snapshots"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    snapshot_date: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), index=True, unique=True
    )

    total_balance_usd: Mapped[Decimal] = mapped_column(Numeric(precision=18, scale=2))
    daily_pnl: Mapped[Decimal] = mapped_column(
        Numeric(precision=18, scale=2), default=Decimal("0")
    )
    cumulative_pnl: Mapped[Decimal] = mapped_column(
        Numeric(precision=18, scale=2), default=Decimal("0")
    )

    total_trades: Mapped[int] = mapped_column(default=0)
    winning_trades: Mapped[int] = mapped_column(default=0)
    losing_trades: Mapped[int] = mapped_column(default=0)

    max_drawdown_pct: Mapped[Decimal] = mapped_column(
        Numeric(precision=5, scale=2), default=Decimal("0")
    )

    is_paper: Mapped[bool] = mapped_column(Boolean, default=False)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(UTC),
    )

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary."""
        return {
            "id": self.id,
            "snapshot_date": self.snapshot_date.isoformat(),
            "total_balance_usd": str(self.total_balance_usd),
            "daily_pnl": str(self.daily_pnl),
            "cumulative_pnl": str(self.cumulative_pnl),
            "total_trades": self.total_trades,
            "winning_trades": self.winning_trades,
            "losing_trades": self.losing_trades,
            "max_drawdown_pct": str(self.max_drawdown_pct),
            "is_paper": self.is_paper,
            "created_at": self.created_at.isoformat(),
        }


# Database engine and session factory
_engine: AsyncEngine | None = None
_session_factory: async_sessionmaker[AsyncSession] | None = None


async def get_engine() -> AsyncEngine:
    """Get or create the async database engine."""
    global _engine
    if _engine is None:
        settings = get_settings()
        _engine = create_async_engine(
            settings.database_url,
            echo=settings.log_level == "DEBUG",
        )
    return _engine


async def get_session_factory() -> async_sessionmaker[AsyncSession]:
    """Get or create the async session factory."""
    global _session_factory
    if _session_factory is None:
        engine = await get_engine()
        _session_factory = async_sessionmaker(engine, expire_on_commit=False)
    return _session_factory


async def init_database() -> None:
    """Initialize the database and create tables."""
    engine = await get_engine()
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)


async def close_database() -> None:
    """Close database connections."""
    global _engine, _session_factory
    if _engine:
        await _engine.dispose()
        _engine = None
        _session_factory = None
