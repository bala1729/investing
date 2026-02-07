"""Database module for trade persistence."""

from src.database.models import (
    Base,
    OrderRecord,
    PerformanceSnapshot,
    Position,
    Trade,
    close_database,
    get_engine,
    get_session_factory,
    init_database,
)
from src.database.repository import (
    OrderRepository,
    PerformanceRepository,
    PositionRepository,
    TradeRepository,
    UnitOfWork,
)

__all__ = [
    # Models
    "Base",
    "Trade",
    "OrderRecord",
    "Position",
    "PerformanceSnapshot",
    # Database functions
    "init_database",
    "close_database",
    "get_engine",
    "get_session_factory",
    # Repositories
    "TradeRepository",
    "OrderRepository",
    "PositionRepository",
    "PerformanceRepository",
    "UnitOfWork",
]
