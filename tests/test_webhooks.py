"""Tests for the TradingView webhook endpoint."""

from decimal import Decimal
from unittest.mock import AsyncMock, patch

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from src.api.webhooks import router
from src.config import Settings, get_settings
from src.exchange.executor import Order, OrderSide, OrderStatus, OrderType


def build_app(settings: Settings, executor: AsyncMock) -> FastAPI:
    """Build a minimal app with the webhook router and overridden dependencies."""
    app = FastAPI()
    app.include_router(router)
    app.state.executor = executor
    app.dependency_overrides[get_settings] = lambda: settings
    return app


def make_order(status: OrderStatus = OrderStatus.FILLED) -> Order:
    """Build a fake filled market order for use as an executor return value."""
    return Order(
        id="paper_abc123",
        symbol="BTC/USD",
        side=OrderSide.BUY,
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
        executor = AsyncMock()
        app = build_app(settings, executor)

        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            response = await client.post(
                "/webhook/tradingview",
                json={"secret": "wrong", "symbol": "BTC/USD", "action": "buy", "quantity": "0.01"},
            )

        assert response.status_code == 401
        executor.execute_market_order.assert_not_called()

    async def test_executes_market_order_when_no_price_given(self, settings: Settings) -> None:
        executor = AsyncMock()
        executor.execute_market_order.return_value = make_order()
        app = build_app(settings, executor)

        with patch("src.api.webhooks.UnitOfWork") as mock_uow_cls:
            mock_uow = AsyncMock()
            mock_uow_cls.return_value.__aenter__.return_value = mock_uow

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
        assert body["order_id"] == "paper_abc123"
        assert body["status"] == "filled"
        executor.execute_market_order.assert_awaited_once_with(
            "BTC/USD", OrderSide.BUY, Decimal("0.01")
        )
        mock_uow.orders.create.assert_awaited_once()
        mock_uow.trades.create.assert_awaited_once()

    async def test_executes_limit_order_when_price_given(self, settings: Settings) -> None:
        executor = AsyncMock()
        executor.execute_limit_order.return_value = make_order(status=OrderStatus.OPEN)
        app = build_app(settings, executor)

        with patch("src.api.webhooks.UnitOfWork") as mock_uow_cls:
            mock_uow = AsyncMock()
            mock_uow_cls.return_value.__aenter__.return_value = mock_uow

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
        executor.execute_limit_order.assert_awaited_once_with(
            "BTC/USD", OrderSide.SELL, Decimal("0.01"), Decimal("46000")
        )
        mock_uow.trades.create.assert_not_awaited()

    async def test_rejects_non_positive_quantity(self, settings: Settings) -> None:
        executor = AsyncMock()
        app = build_app(settings, executor)

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
        executor.execute_market_order.assert_not_called()
