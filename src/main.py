"""FastAPI application entry point."""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI

from src.api.webhooks import router as webhooks_router
from src.bot.engine import TradingEngine
from src.config import get_settings
from src.database.models import init_database
from src.exchange.executor import OrderExecutor
from src.exchange.kraken import KrakenClient
from src.risk.manager import RiskManager


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    """Initialize and tear down shared resources for the app's lifetime."""
    settings = get_settings()
    client = KrakenClient(settings)
    await client.initialize()
    await init_database()

    executor = OrderExecutor(client, settings)
    risk_manager = RiskManager(settings)

    app.state.client = client
    app.state.executor = executor
    app.state.risk_manager = risk_manager
    app.state.engine = TradingEngine(client, executor, risk_manager, settings)

    yield

    await client.close()


app = FastAPI(title="Kraken Trading Bot", lifespan=lifespan)
app.include_router(webhooks_router)


@app.get("/health")
async def health_check() -> dict[str, str]:
    """Basic liveness check."""
    return {"status": "ok"}
