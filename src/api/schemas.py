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
    quantity: Decimal | None = Field(
        default=None,
        gt=0,
        description="Order amount in base currency. Omit to let the risk manager size it "
        "automatically from account balance and position-sizing limits.",
    )
    price: Decimal | None = Field(
        default=None, description="Limit price; omit for a market order"
    )
    strategy: str | None = Field(
        default=None, description="Name of the strategy that generated the signal"
    )


class WebhookResponse(BaseModel):
    """Response returned after processing a webhook signal.

    `approved` is False when the risk manager rejected the signal (e.g.
    drawdown or exposure limits) or there was nothing to execute (e.g. a
    SELL with no open position) - `reason` explains why, and the order
    fields are left unset since no order was placed.
    """

    approved: bool
    reason: str | None = None
    order_id: str | None = None
    status: str | None = None
    symbol: str
    side: str
    amount: str | None = None
    price: str | None = None
