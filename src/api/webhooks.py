"""TradingView webhook endpoint for receiving trading signals."""

from typing import cast

from fastapi import APIRouter, Depends, HTTPException, Request, status
from loguru import logger

from src.api.schemas import TradingViewSignal, WebhookResponse
from src.bot.engine import TradingEngine
from src.bot.strategies.base import Signal
from src.config import Settings, get_settings
from src.exchange.executor import OrderSide

router = APIRouter()


def get_engine(request: Request) -> TradingEngine:
    """Retrieve the shared TradingEngine from application state."""
    return cast(TradingEngine, request.app.state.engine)


@router.post("/webhook/tradingview", response_model=WebhookResponse)
async def receive_tradingview_signal(
    payload: TradingViewSignal,
    engine: TradingEngine = Depends(get_engine),
    settings: Settings = Depends(get_settings),
) -> WebhookResponse:
    """Receive a TradingView alert and route it through the risk-gated trading engine."""
    if payload.secret != settings.webhook_secret:
        logger.warning(f"Rejected webhook signal for {payload.symbol}: invalid secret")
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid webhook secret"
        )

    side = OrderSide(payload.action)
    signal = Signal(
        symbol=payload.symbol,
        side=side,
        strategy=payload.strategy or "tradingview_webhook",
        reason="TradingView webhook signal",
    )

    result = await engine.process_signal(
        signal, quantity=payload.quantity, limit_price=payload.price
    )

    if not result.executed or result.order is None:
        logger.info(f"Webhook signal for {payload.symbol} not executed: {result.reason}")
        return WebhookResponse(
            approved=False,
            reason=result.reason,
            symbol=payload.symbol,
            side=side.value,
        )

    order = result.order
    logger.info(
        f"Webhook processed: {payload.action} {order.amount} {payload.symbol} "
        f"-> {order.status.value}"
    )

    return WebhookResponse(
        approved=True,
        order_id=order.id,
        status=order.status.value,
        symbol=order.symbol,
        side=order.side.value,
        amount=str(order.amount),
        price=str(order.price) if order.price else None,
    )
