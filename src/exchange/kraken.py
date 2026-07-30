"""Kraken exchange client using CCXT."""

from decimal import Decimal
from types import TracebackType
from typing import Any

import ccxt.async_support as ccxt
from loguru import logger

from src.config import Settings, get_settings


class KrakenClient:
    """Async Kraken exchange client wrapping CCXT."""

    def __init__(self, settings: Settings | None = None) -> None:
        """Initialize the Kraken client.

        Args:
            settings: Application settings. Uses default if not provided.
        """
        self._settings = settings or get_settings()
        self._exchange: ccxt.kraken | None = None
        self._initialized = False

    async def initialize(self) -> None:
        """Initialize the exchange connection."""
        if self._initialized:
            return

        config: dict[str, Any] = {
            "enableRateLimit": True,
            "rateLimit": 1000,  # 1 request per second for safety
        }

        # Only add API credentials if provided
        if self._settings.kraken_api_key and self._settings.kraken_api_secret:
            config["apiKey"] = self._settings.kraken_api_key
            config["secret"] = self._settings.kraken_api_secret

        self._exchange = ccxt.kraken(config)

        if self._settings.is_paper_trading:
            logger.info("Kraken client initialized in PAPER TRADING mode")
            # Enable sandbox mode if available
            if self._exchange.urls.get("test"):
                self._exchange.set_sandbox_mode(True)
                logger.info("Using Kraken sandbox/test environment")
        else:
            logger.warning("Kraken client initialized in LIVE TRADING mode")

        self._initialized = True

    async def close(self) -> None:
        """Close the exchange connection."""
        if self._exchange:
            await self._exchange.close()
            self._exchange = None
            self._initialized = False
            logger.info("Kraken client connection closed")

    def _ensure_initialized(self) -> ccxt.kraken:
        """Ensure the client is initialized and return the exchange instance."""
        if not self._initialized or not self._exchange:
            raise RuntimeError("KrakenClient not initialized. Call initialize() first.")
        return self._exchange

    # -------------------------------------------------------------------------
    # Market Data Methods (Public - no auth required)
    # -------------------------------------------------------------------------

    async def fetch_ticker(self, symbol: str) -> dict[str, Any]:
        """Fetch current ticker data for a symbol.

        Args:
            symbol: Trading pair symbol (e.g., 'BTC/USD')

        Returns:
            Ticker data including bid, ask, last price, volume, etc.
        """
        exchange = self._ensure_initialized()
        ticker = await exchange.fetch_ticker(symbol)
        logger.debug(f"Fetched ticker for {symbol}: last={ticker.get('last')}")
        return ticker

    async def fetch_tickers(self, symbols: list[str] | None = None) -> dict[str, Any]:
        """Fetch tickers for multiple symbols.

        Args:
            symbols: List of symbols to fetch. None for all.

        Returns:
            Dictionary of symbol -> ticker data
        """
        exchange = self._ensure_initialized()
        return await exchange.fetch_tickers(symbols)

    async def fetch_ohlcv(
        self,
        symbol: str,
        timeframe: str = "1h",
        since: int | None = None,
        limit: int = 100,
    ) -> list[list[Any]]:
        """Fetch OHLCV (candlestick) data.

        Args:
            symbol: Trading pair symbol
            timeframe: Candle timeframe (1m, 5m, 15m, 1h, 4h, 1d, etc.)
            since: Start timestamp in milliseconds
            limit: Maximum number of candles to fetch

        Returns:
            List of [timestamp, open, high, low, close, volume]
        """
        exchange = self._ensure_initialized()
        ohlcv = await exchange.fetch_ohlcv(symbol, timeframe, since, limit)
        logger.debug(f"Fetched {len(ohlcv)} candles for {symbol} ({timeframe})")
        return ohlcv

    async def fetch_order_book(
        self, symbol: str, limit: int = 20
    ) -> dict[str, Any]:
        """Fetch the order book for a symbol.

        Args:
            symbol: Trading pair symbol
            limit: Depth of order book

        Returns:
            Order book with bids and asks
        """
        exchange = self._ensure_initialized()
        return await exchange.fetch_order_book(symbol, limit)

    async def fetch_markets(self) -> list[dict[str, Any]]:
        """Fetch all available markets.

        Returns:
            List of market information dictionaries
        """
        exchange = self._ensure_initialized()
        return await exchange.fetch_markets()

    async def get_market_info(self, symbol: str) -> dict[str, Any] | None:
        """Get market information for a specific symbol.

        Args:
            symbol: Trading pair symbol

        Returns:
            Market info or None if not found
        """
        exchange = self._ensure_initialized()
        await exchange.load_markets()
        return exchange.markets.get(symbol)

    # -------------------------------------------------------------------------
    # Account Methods (Private - auth required)
    # -------------------------------------------------------------------------

    async def fetch_balance(self) -> dict[str, Any]:
        """Fetch account balance.

        Returns:
            Balance information for all currencies
        """
        exchange = self._ensure_initialized()
        balance = await exchange.fetch_balance()
        logger.debug("Fetched account balance")
        return balance

    async def get_free_balance(self, currency: str) -> Decimal:
        """Get available (free) balance for a currency.

        Args:
            currency: Currency code (e.g., 'USD', 'BTC')

        Returns:
            Available balance as Decimal
        """
        balance = await self.fetch_balance()
        free = balance.get("free", {}).get(currency, 0)
        return Decimal(str(free))

    # -------------------------------------------------------------------------
    # Order Methods (Private - auth required)
    # -------------------------------------------------------------------------

    async def create_market_order(
        self,
        symbol: str,
        side: str,
        amount: float,
    ) -> dict[str, Any]:
        """Create a market order.

        Args:
            symbol: Trading pair symbol
            side: 'buy' or 'sell'
            amount: Order amount in base currency

        Returns:
            Order information
        """
        exchange = self._ensure_initialized()
        logger.info(f"Creating market {side} order: {amount} {symbol}")
        order = await exchange.create_market_order(symbol, side, amount)
        logger.info(f"Market order created: id={order.get('id')}, status={order.get('status')}")
        return order

    async def create_limit_order(
        self,
        symbol: str,
        side: str,
        amount: float,
        price: float,
    ) -> dict[str, Any]:
        """Create a limit order.

        Args:
            symbol: Trading pair symbol
            side: 'buy' or 'sell'
            amount: Order amount in base currency
            price: Limit price

        Returns:
            Order information
        """
        exchange = self._ensure_initialized()
        logger.info(f"Creating limit {side} order: {amount} {symbol} @ {price}")
        order = await exchange.create_limit_order(symbol, side, amount, price)
        logger.info(f"Limit order created: id={order.get('id')}, status={order.get('status')}")
        return order

    async def create_stop_loss_order(
        self,
        symbol: str,
        side: str,
        amount: float,
        stop_price: float,
    ) -> dict[str, Any]:
        """Create a stop-loss order.

        Args:
            symbol: Trading pair symbol
            side: 'buy' or 'sell'
            amount: Order amount in base currency
            stop_price: Trigger price for stop loss

        Returns:
            Order information
        """
        exchange = self._ensure_initialized()
        logger.info(f"Creating stop-loss {side} order: {amount} {symbol} @ {stop_price}")
        order = await exchange.create_order(
            symbol=symbol,
            type="stop-loss",
            side=side,
            amount=amount,
            price=None,
            params={"stopPrice": stop_price},
        )
        logger.info(f"Stop-loss order created: id={order.get('id')}")
        return order

    async def cancel_order(self, order_id: str, symbol: str) -> dict[str, Any]:
        """Cancel an order.

        Args:
            order_id: Order ID to cancel
            symbol: Trading pair symbol

        Returns:
            Cancellation result
        """
        exchange = self._ensure_initialized()
        logger.info(f"Cancelling order {order_id} for {symbol}")
        result = await exchange.cancel_order(order_id, symbol)
        logger.info(f"Order {order_id} cancelled")
        return result

    async def fetch_order(self, order_id: str, symbol: str) -> dict[str, Any]:
        """Fetch a specific order.

        Args:
            order_id: Order ID
            symbol: Trading pair symbol

        Returns:
            Order information
        """
        exchange = self._ensure_initialized()
        return await exchange.fetch_order(order_id, symbol)

    async def fetch_open_orders(self, symbol: str | None = None) -> list[dict[str, Any]]:
        """Fetch all open orders.

        Args:
            symbol: Filter by symbol (optional)

        Returns:
            List of open orders
        """
        exchange = self._ensure_initialized()
        orders = await exchange.fetch_open_orders(symbol)
        logger.debug(f"Fetched {len(orders)} open orders")
        return orders

    async def fetch_closed_orders(
        self,
        symbol: str | None = None,
        since: int | None = None,
        limit: int = 50,
    ) -> list[dict[str, Any]]:
        """Fetch closed orders.

        Args:
            symbol: Filter by symbol (optional)
            since: Start timestamp in milliseconds
            limit: Maximum number of orders

        Returns:
            List of closed orders
        """
        exchange = self._ensure_initialized()
        return await exchange.fetch_closed_orders(symbol, since, limit)

    async def fetch_my_trades(
        self,
        symbol: str | None = None,
        since: int | None = None,
        limit: int = 50,
    ) -> list[dict[str, Any]]:
        """Fetch trade history.

        Args:
            symbol: Filter by symbol (optional)
            since: Start timestamp in milliseconds
            limit: Maximum number of trades

        Returns:
            List of trades
        """
        exchange = self._ensure_initialized()
        return await exchange.fetch_my_trades(symbol, since, limit)

    # -------------------------------------------------------------------------
    # Utility Methods
    # -------------------------------------------------------------------------

    async def get_minimum_order_amount(self, symbol: str) -> Decimal | None:
        """Get minimum order amount for a symbol.

        Args:
            symbol: Trading pair symbol

        Returns:
            Minimum order amount or None if not available
        """
        market = await self.get_market_info(symbol)
        if market and "limits" in market:
            min_amount = market["limits"].get("amount", {}).get("min")
            if min_amount is not None:
                return Decimal(str(min_amount))
        return None

    async def get_price_precision(self, symbol: str) -> int | None:
        """Get price precision (decimal places) for a symbol.

        Args:
            symbol: Trading pair symbol

        Returns:
            Number of decimal places or None
        """
        market = await self.get_market_info(symbol)
        if market and "precision" in market:
            return market["precision"].get("price")
        return None

    @property
    def is_paper_trading(self) -> bool:
        """Check if running in paper trading mode."""
        return self._settings.is_paper_trading

    async def __aenter__(self) -> "KrakenClient":
        """Async context manager entry."""
        await self.initialize()
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc_val: BaseException | None,
        exc_tb: TracebackType | None,
    ) -> None:
        """Async context manager exit."""
        await self.close()
