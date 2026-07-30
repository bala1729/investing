"""TradingView webhook endpoint for receiving trading signals."""

from typing import cast

from fastapi import APIRouter, Depends, HTTPException, Request, status
from loguru import logger

from src.api.schemas import TradingViewSignal, WebhookResponse
from src.config import Settings, get_settings
from src.database.repository import UnitOfWork
from src.exchange.executor import OrderExecutor, OrderSide, OrderStatus

router = APIRouter()


def get_executor(request: Request) -> OrderExecutor:
    """Retrieve the shared OrderExecutor from application state."""
    return cast(OrderExecutor, request.app.state.executor)


@router.post("/webhook/tradingview", response_model=WebhookResponse)
async def receive_tradingview_signal(
    signal: TradingViewSignal,
    executor: OrderExecutor = Depends(get_executor),
    settings: Settings = Depends(get_settings),
) -> WebhookResponse:
    """Receive a TradingView alert and execute the corresponding order."""
    if signal.secret != settings.webhook_secret:
        logger.warning(f"Rejected webhook signal for {signal.symbol}: invalid secret")
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid webhook secret"
        )

    side = OrderSide(signal.action)

    if signal.price is not None:
        order = await executor.execute_limit_order(
            signal.symbol, side, signal.quantity, signal.price
        )
    else:
        order = await executor.execute_market_order(signal.symbol, side, signal.quantity)

    async with UnitOfWork() as uow:
        await uow.orders.create(order, strategy=signal.strategy)
        if order.status == OrderStatus.FILLED:
            await uow.trades.create(order, strategy=signal.strategy)
        await uow.commit()

    logger.info(
        f"Webhook processed: {signal.action} {signal.quantity} {signal.symbol} "
        f"-> {order.status.value}"
    )

    return WebhookResponse(
        order_id=order.id,
        status=order.status.value,
        symbol=order.symbol,
        side=order.side.value,
        amount=str(order.amount),
        price=str(order.price) if order.price else None,
    )
