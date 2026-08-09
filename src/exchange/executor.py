"""Order execution logic with paper trading support."""

import asyncio
import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime
from decimal import Decimal
from enum import StrEnum
from typing import Any, cast

from loguru import logger

from src.config import Settings, get_settings
from src.exchange.kraken import KrakenClient


class OrderSide(StrEnum):
    """Order side."""

    BUY = "buy"
    SELL = "sell"


class OrderType(StrEnum):
    """Order type."""

    MARKET = "market"
    LIMIT = "limit"
    STOP_LOSS = "stop_loss"


class OrderStatus(StrEnum):
    """Order status."""

    PENDING = "pending"
    OPEN = "open"
    FILLED = "filled"
    PARTIALLY_FILLED = "partially_filled"
    CANCELLED = "cancelled"
    FAILED = "failed"


def _extract_fee(result: dict[str, Any]) -> Decimal:
    """Pull the fee an exchange reported for a fill, defaulting to zero.

    ccxt puts it in `fee: {cost, currency}` but not every venue populates it on
    the create-order response. Zero is the honest default - it records "not
    reported" rather than inventing a number - but it does mean live fees can
    read low until the order is refetched.
    """
    fee = result.get("fee") or {}
    cost = fee.get("cost")
    return Decimal(str(cost)) if cost is not None else Decimal("0")


@dataclass
class Order:
    """Order data structure."""

    id: str
    symbol: str
    side: OrderSide
    order_type: OrderType
    amount: Decimal
    price: Decimal | None
    status: OrderStatus
    filled_amount: Decimal = Decimal("0")
    average_fill_price: Decimal | None = None
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    updated_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    exchange_order_id: str | None = None
    is_paper: bool = False
    error_message: str | None = None
    fee: Decimal = Decimal("0")
    fee_currency: str | None = None

    def to_dict(self) -> dict[str, Any]:
        """Convert order to dictionary."""
        return {
            "id": self.id,
            "symbol": self.symbol,
            "side": self.side.value,
            "order_type": self.order_type.value,
            "amount": str(self.amount),
            "price": str(self.price) if self.price else None,
            "status": self.status.value,
            "filled_amount": str(self.filled_amount),
            "average_fill_price": str(self.average_fill_price) if self.average_fill_price else None,
            "created_at": self.created_at.isoformat(),
            "updated_at": self.updated_at.isoformat(),
            "exchange_order_id": self.exchange_order_id,
            "is_paper": self.is_paper,
            "error_message": self.error_message,
            "fee": str(self.fee),
            "fee_currency": self.fee_currency,
        }


class PaperTradingSimulator:
    """Simulates order execution for paper trading."""

    def __init__(self, client: KrakenClient, fee_pct: Decimal = Decimal("0")) -> None:
        """Initialize the paper trading simulator.

        Args:
            client: Kraken client for fetching real market data
            fee_pct: Fee charged per fill, as a percent of trade value. Defaults
                to 0 for backwards compatibility with direct construction, but
                OrderExecutor always passes the configured rate - paper results
                that ignore fees are systematically optimistic, and fee drag is
                what decided every result in docs/backtest-results.md.
        """
        if fee_pct < 0:
            raise ValueError("fee_pct cannot be negative")
        self._fee_pct = fee_pct
        self._client = client
        self._orders: dict[str, Order] = {}
        self._balances: dict[str, Decimal] = {
            "USD": Decimal("10000"),  # Start with $10,000
        }

    def get_balance(self, currency: str) -> Decimal:
        """Get simulated balance for a currency."""
        return self._balances.get(currency, Decimal("0"))

    def set_balance(self, currency: str, amount: Decimal) -> None:
        """Set simulated balance for a currency."""
        self._balances[currency] = amount

    def get_all_balances(self) -> dict[str, Decimal]:
        """Get all simulated balances."""
        return self._balances.copy()

    async def execute_market_order(
        self,
        symbol: str,
        side: OrderSide,
        amount: Decimal,
    ) -> Order:
        """Simulate market order execution.

        Uses real market prices to simulate fills.
        """
        order_id = f"paper_{uuid.uuid4().hex[:12]}"

        # Get current market price
        ticker = await self._client.fetch_ticker(symbol)
        if side == OrderSide.BUY:
            fill_price = Decimal(str(ticker["ask"]))
        else:
            fill_price = Decimal(str(ticker["bid"]))

        # Parse symbol to get base and quote currencies
        base, quote = symbol.split("/")

        # Fee is charged in the quote currency on both sides, matching how
        # Kraken bills a spot trade: added to what a buy costs, deducted from
        # what a sell returns.
        gross = amount * fill_price
        fee = gross * self._fee_pct / 100

        # Check if we have sufficient balance
        if side == OrderSide.BUY:
            required = gross + fee
            if self._balances.get(quote, Decimal("0")) < required:
                order = Order(
                    id=order_id,
                    symbol=symbol,
                    side=side,
                    order_type=OrderType.MARKET,
                    amount=amount,
                    price=None,
                    status=OrderStatus.FAILED,
                    is_paper=True,
                    error_message=f"Insufficient {quote} balance",
                )
                self._orders[order_id] = order
                return order
        else:
            if self._balances.get(base, Decimal("0")) < amount:
                order = Order(
                    id=order_id,
                    symbol=symbol,
                    side=side,
                    order_type=OrderType.MARKET,
                    amount=amount,
                    price=None,
                    status=OrderStatus.FAILED,
                    is_paper=True,
                    error_message=f"Insufficient {base} balance",
                )
                self._orders[order_id] = order
                return order

        # Execute the simulated trade
        if side == OrderSide.BUY:
            self._balances[quote] = self._balances.get(quote, Decimal("0")) - (gross + fee)
            self._balances[base] = self._balances.get(base, Decimal("0")) + amount
        else:
            self._balances[base] = self._balances.get(base, Decimal("0")) - amount
            self._balances[quote] = self._balances.get(quote, Decimal("0")) + (gross - fee)

        order = Order(
            id=order_id,
            symbol=symbol,
            side=side,
            order_type=OrderType.MARKET,
            amount=amount,
            price=None,
            status=OrderStatus.FILLED,
            filled_amount=amount,
            average_fill_price=fill_price,
            is_paper=True,
            fee=fee,
            fee_currency=quote,
        )
        self._orders[order_id] = order

        logger.info(
            f"[PAPER] Market {side.value} executed: {amount} {symbol} @ {fill_price}"
        )
        return order

    async def execute_limit_order(
        self,
        symbol: str,
        side: OrderSide,
        amount: Decimal,
        price: Decimal,
    ) -> Order:
        """Simulate limit order placement.

        Note: Paper limit orders are marked as OPEN but won't actually
        be monitored for fills. For full simulation, additional logic
        would be needed to check market prices.
        """
        order_id = f"paper_{uuid.uuid4().hex[:12]}"

        order = Order(
            id=order_id,
            symbol=symbol,
            side=side,
            order_type=OrderType.LIMIT,
            amount=amount,
            price=price,
            status=OrderStatus.OPEN,
            is_paper=True,
        )
        self._orders[order_id] = order

        logger.info(
            f"[PAPER] Limit {side.value} placed: {amount} {symbol} @ {price}"
        )
        return order

    def cancel_order(self, order_id: str) -> Order | None:
        """Cancel a paper order."""
        order = self._orders.get(order_id)
        if order and order.status == OrderStatus.OPEN:
            order.status = OrderStatus.CANCELLED
            order.updated_at = datetime.now(UTC)
            logger.info(f"[PAPER] Order {order_id} cancelled")
        return order

    def get_order(self, order_id: str) -> Order | None:
        """Get a paper order by ID."""
        return self._orders.get(order_id)

    def get_open_orders(self, symbol: str | None = None) -> list[Order]:
        """Get all open paper orders."""
        orders = [o for o in self._orders.values() if o.status == OrderStatus.OPEN]
        if symbol:
            orders = [o for o in orders if o.symbol == symbol]
        return orders


class OrderExecutor:
    """Handles order execution for both paper and live trading."""

    def __init__(
        self,
        client: KrakenClient,
        settings: Settings | None = None,
        max_retries: int = 3,
        retry_delay: float = 1.0,
    ) -> None:
        """Initialize the order executor.

        Args:
            client: Kraken exchange client
            settings: Application settings
            max_retries: Maximum retry attempts for failed orders
            retry_delay: Delay between retries in seconds
        """
        self._client = client
        self._settings = settings or get_settings()
        self._max_retries = max_retries
        self._retry_delay = retry_delay
        self._paper_simulator = PaperTradingSimulator(
            client, fee_pct=Decimal(str(self._settings.paper_fee_pct))
        )

    @property
    def is_paper_trading(self) -> bool:
        """Check if running in paper trading mode."""
        return self._settings.is_paper_trading

    async def restore_paper_state(self) -> bool:
        """Reload persisted paper balances so a restart resumes mid-position.

        Lives here rather than on PaperTradingSimulator so the simulator stays a
        pure in-memory model with no database dependency - it is used directly
        in tests and would otherwise need a database to execute a single order.

        A no-op in live mode, where the exchange holds the real balances and is
        already the source of truth.
        """
        if not self.is_paper_trading:
            return False
        from src.database.repository import UnitOfWork

        async with UnitOfWork() as uow:
            stored = await uow.paper_balances.load_all()
        if not stored:
            return False
        for currency, amount in stored.items():
            self._paper_simulator.set_balance(currency, amount)
        logger.info(
            "Restored paper balances: "
            + ", ".join(f"{c}={a}" for c, a in sorted(stored.items()))
        )
        return True

    async def _persist_paper_state(self) -> None:
        """Save paper balances after a fill.

        After every fill rather than at shutdown: a bot that is killed, or whose
        machine reboots, never gets to run shutdown code - and that is exactly
        when losing the balances would hurt.
        """
        from src.database.repository import UnitOfWork

        try:
            async with UnitOfWork() as uow:
                await uow.paper_balances.save_all(self._paper_simulator.get_all_balances())
                await uow.commit()
        except Exception:
            # Never fail a completed trade because bookkeeping could not be saved.
            logger.exception("Could not persist paper balances")

    async def execute_market_order(
        self,
        symbol: str,
        side: OrderSide,
        amount: Decimal,
    ) -> Order:
        """Execute a market order.

        Args:
            symbol: Trading pair symbol
            side: Order side (buy/sell)
            amount: Order amount

        Returns:
            Order result
        """
        if self.is_paper_trading:
            order = await self._paper_simulator.execute_market_order(symbol, side, amount)
            if order.status == OrderStatus.FILLED:
                await self._persist_paper_state()
            return order

        return await self._execute_live_market_order(symbol, side, amount)

    async def _execute_live_market_order(
        self,
        symbol: str,
        side: OrderSide,
        amount: Decimal,
    ) -> Order:
        """Execute a live market order with retry logic."""
        order_id = f"live_{uuid.uuid4().hex[:12]}"
        last_error: str | None = None

        for attempt in range(self._max_retries):
            try:
                result = await self._client.create_market_order(
                    symbol=symbol,
                    side=side.value,
                    amount=float(amount),
                )

                return Order(
                    id=order_id,
                    symbol=symbol,
                    side=side,
                    order_type=OrderType.MARKET,
                    amount=amount,
                    price=None,
                    status=OrderStatus(result.get("status", "filled")),
                    filled_amount=Decimal(str(result.get("filled", amount))),
                    average_fill_price=(
                        Decimal(str(result["average"])) if result.get("average") else None
                    ),
                    fee=_extract_fee(result),
                    fee_currency=(result.get("fee") or {}).get("currency"),
                    exchange_order_id=result.get("id"),
                    is_paper=False,
                )

            except Exception as e:
                last_error = str(e)
                logger.warning(
                    f"Market order attempt {attempt + 1}/{self._max_retries} failed: {e}"
                )
                if attempt < self._max_retries - 1:
                    await asyncio.sleep(self._retry_delay * (attempt + 1))

        # All retries failed
        return Order(
            id=order_id,
            symbol=symbol,
            side=side,
            order_type=OrderType.MARKET,
            amount=amount,
            price=None,
            status=OrderStatus.FAILED,
            is_paper=False,
            error_message=last_error,
        )

    async def execute_limit_order(
        self,
        symbol: str,
        side: OrderSide,
        amount: Decimal,
        price: Decimal,
    ) -> Order:
        """Execute a limit order.

        Args:
            symbol: Trading pair symbol
            side: Order side (buy/sell)
            amount: Order amount
            price: Limit price

        Returns:
            Order result
        """
        if self.is_paper_trading:
            return await self._paper_simulator.execute_limit_order(
                symbol, side, amount, price
            )

        return await self._execute_live_limit_order(symbol, side, amount, price)

    async def _execute_live_limit_order(
        self,
        symbol: str,
        side: OrderSide,
        amount: Decimal,
        price: Decimal,
    ) -> Order:
        """Execute a live limit order with retry logic."""
        order_id = f"live_{uuid.uuid4().hex[:12]}"
        last_error: str | None = None

        for attempt in range(self._max_retries):
            try:
                result = await self._client.create_limit_order(
                    symbol=symbol,
                    side=side.value,
                    amount=float(amount),
                    price=float(price),
                )

                return Order(
                    id=order_id,
                    symbol=symbol,
                    side=side,
                    order_type=OrderType.LIMIT,
                    amount=amount,
                    price=price,
                    status=OrderStatus(result.get("status", "open")),
                    filled_amount=Decimal(str(result.get("filled", 0))),
                    average_fill_price=(
                        Decimal(str(result["average"])) if result.get("average") else None
                    ),
                    fee=_extract_fee(result),
                    fee_currency=(result.get("fee") or {}).get("currency"),
                    exchange_order_id=result.get("id"),
                    is_paper=False,
                )

            except Exception as e:
                last_error = str(e)
                logger.warning(
                    f"Limit order attempt {attempt + 1}/{self._max_retries} failed: {e}"
                )
                if attempt < self._max_retries - 1:
                    await asyncio.sleep(self._retry_delay * (attempt + 1))

        return Order(
            id=order_id,
            symbol=symbol,
            side=side,
            order_type=OrderType.LIMIT,
            amount=amount,
            price=price,
            status=OrderStatus.FAILED,
            is_paper=False,
            error_message=last_error,
        )

    async def cancel_order(self, order_id: str, symbol: str) -> bool:
        """Cancel an order.

        Args:
            order_id: Order ID (internal or exchange)
            symbol: Trading pair symbol

        Returns:
            True if cancelled successfully
        """
        if self.is_paper_trading:
            order = self._paper_simulator.cancel_order(order_id)
            return order is not None and order.status == OrderStatus.CANCELLED

        try:
            await self._client.cancel_order(order_id, symbol)
            return True
        except Exception as e:
            logger.error(f"Failed to cancel order {order_id}: {e}")
            return False

    async def get_balance(self, currency: str) -> Decimal:
        """Get available balance for a currency.

        Args:
            currency: Currency code

        Returns:
            Available balance
        """
        if self.is_paper_trading:
            return self._paper_simulator.get_balance(currency)

        return await self._client.get_free_balance(currency)

    async def get_all_balances(self) -> dict[str, Any]:
        """Get all balances.

        Returns:
            Dictionary of balances
        """
        if self.is_paper_trading:
            return {k: str(v) for k, v in self._paper_simulator.get_all_balances().items()}

        balance = await self._client.fetch_balance()
        return cast(dict[str, Any], balance.get("free", {}))

    def get_open_orders(self, symbol: str | None = None) -> list[Order]:
        """Get open orders (paper trading only for local orders).

        For live trading, use the client directly.
        """
        if self.is_paper_trading:
            return self._paper_simulator.get_open_orders(symbol)
        return []

    def set_paper_balance(self, currency: str, amount: Decimal) -> None:
        """Set paper trading balance.

        Args:
            currency: Currency code
            amount: Balance amount
        """
        if self.is_paper_trading:
            self._paper_simulator.set_balance(currency, amount)
        else:
            logger.warning("Cannot set balance in live trading mode")
