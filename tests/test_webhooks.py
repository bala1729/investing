"""Tests for the TradingView webhook endpoint."""

from decimal import Decimal
from unittest.mock import AsyncMock

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from src.api.webhooks import router
from src.bot.engine import EngineResult
from src.config import Settings, get_settings
from src.exchange.executor import Order, OrderSide, OrderStatus, OrderType


def build_app(settings: Settings, engine: AsyncMock) -> FastAPI:
    """Build a minimal app with the webhook router and overridden dependencies."""
    app = FastAPI()
    app.include_router(router)
    app.state.engine = engine
    app.dependency_overrides[get_settings] = lambda: settings
    return app


def make_order(
    status: OrderStatus = OrderStatus.FILLED, side: OrderSide = OrderSide.BUY
) -> Order:
    """Build a fake filled order for use as an engine return value."""
    return Order(
        id="paper_abc123",
        symbol="BTC/USD",
        side=side,
        order_type=OrderType.MARKET,
        amount=Decimal("0.01"),
        price=None,
        status=status,
        filled_amount=Decimal("0.01"),
        average_fill_price=Decimal("45000"),
        is_paper=True,
    )


@pytest.fixture
def settings() -> Settings:
    return Settings(_env_file=None, webhook_secret="test-secret")


class TestReceiveTradingViewSignal:
    """Tests for POST /webhook/tradingview."""

    async def test_rejects_invalid_secret(self, settings: Settings) -> None:
        engine = AsyncMock()
        app = build_app(settings, engine)

        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            response = await client.post(
                "/webhook/tradingview",
                json={"secret": "wrong", "symbol": "BTC/USD", "action": "buy", "quantity": "0.01"},
            )

        assert response.status_code == 401
        engine.process_signal.assert_not_called()

    async def test_executed_signal_returns_order_details(self, settings: Settings) -> None:
        engine = AsyncMock()
        engine.process_signal.return_value = EngineResult(executed=True, order=make_order())
        app = build_app(settings, engine)

        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            response = await client.post(
                "/webhook/tradingview",
                json={
                    "secret": "test-secret",
                    "symbol": "BTC/USD",
                    "action": "buy",
                    "quantity": "0.01",
                    "strategy": "momentum",
                },
            )

        assert response.status_code == 200
        body = response.json()
        assert body["approved"] is True
        assert body["order_id"] == "paper_abc123"
        assert body["status"] == "filled"
        assert body["reason"] is None

        assert engine.process_signal.await_args is not None
        call_kwargs = engine.process_signal.await_args.kwargs
        assert call_kwargs["quantity"] == Decimal("0.01")
        assert call_kwargs["limit_price"] is None
        signal = engine.process_signal.await_args.args[0]
        assert signal.symbol == "BTC/USD"
        assert signal.side == OrderSide.BUY
        assert signal.strategy == "momentum"

    async def test_limit_price_is_passed_through(self, settings: Settings) -> None:
        engine = AsyncMock()
        engine.process_signal.return_value = EngineResult(
            executed=True, order=make_order(status=OrderStatus.OPEN, side=OrderSide.SELL)
        )
        app = build_app(settings, engine)

        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            response = await client.post(
                "/webhook/tradingview",
                json={
                    "secret": "test-secret",
                    "symbol": "BTC/USD",
                    "action": "sell",
                    "quantity": "0.01",
                    "price": "46000",
                },
            )

        assert response.status_code == 200
        assert engine.process_signal.await_args is not None
        call_kwargs = engine.process_signal.await_args.kwargs
        assert call_kwargs["limit_price"] == Decimal("46000")

    async def test_omitted_quantity_lets_engine_size_it(self, settings: Settings) -> None:
        engine = AsyncMock()
        engine.process_signal.return_value = EngineResult(executed=True, order=make_order())
        app = build_app(settings, engine)

        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            response = await client.post(
                "/webhook/tradingview",
                json={"secret": "test-secret", "symbol": "BTC/USD", "action": "buy"},
            )

        assert response.status_code == 200
        assert engine.process_signal.await_args is not None
        call_kwargs = engine.process_signal.await_args.kwargs
        assert call_kwargs["quantity"] is None

    async def test_rejected_signal_returns_approved_false_with_reason(
        self, settings: Settings
    ) -> None:
        engine = AsyncMock()
        engine.process_signal.return_value = EngineResult(
            executed=False, reason="Max drawdown of 10.0% breached"
        )
        app = build_app(settings, engine)

        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            response = await client.post(
                "/webhook/tradingview",
                json={
                    "secret": "test-secret",
                    "symbol": "BTC/USD",
                    "action": "buy",
                    "quantity": "0.01",
                },
            )

        assert response.status_code == 200
        body = response.json()
        assert body["approved"] is False
        assert body["reason"] == "Max drawdown of 10.0% breached"
        assert body["order_id"] is None
        assert body["status"] is None

    async def test_rejects_non_positive_quantity(self, settings: Settings) -> None:
        engine = AsyncMock()
        app = build_app(settings, engine)

        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            response = await client.post(
                "/webhook/tradingview",
                json={
                    "secret": "test-secret",
                    "symbol": "BTC/USD",
                    "action": "buy",
                    "quantity": "0",
                },
            )

        assert response.status_code == 422
        engine.process_signal.assert_not_called()
