"""Pydantic schemas for the webhook API."""

from decimal import Decimal
from typing import Literal

from pydantic import BaseModel, Field


class TradingViewSignal(BaseModel):
    """Payload sent by a TradingView alert webhook.

    `symbol` must use ccxt/Kraken pair notation (e.g. "BTC/USD"), matching
    what the rest of the codebase expects - template TradingView alerts
    accordingly rather than sending Kraken's raw "BTCUSD" style.
    """

    secret: str = Field(..., description="Shared secret for authenticating the webhook")
    symbol: str = Field(..., description="Trading pair symbol, e.g. BTC/USD")
    action: Literal["buy", "sell"] = Field(..., description="Order side")
    quantity: Decimal = Field(..., gt=0, description="Order amount in base currency")
    price: Decimal | None = Field(
        default=None, description="Limit price; omit for a market order"
    )
    strategy: str | None = Field(
        default=None, description="Name of the strategy that generated the signal"
    )


class WebhookResponse(BaseModel):
    """Response returned after processing a webhook signal."""

    order_id: str
    status: str
    symbol: str
    side: str
    amount: str
    price: str | None = None
