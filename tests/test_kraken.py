"""Tests for the Kraken CCXT client wrapper."""

from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.config import Settings
from src.exchange.kraken import KrakenClient


def make_exchange_mock() -> MagicMock:
    """Build a mock standing in for a ccxt.async_support.kraken instance."""
    exchange = MagicMock()
    exchange.urls = {}
    exchange.close = AsyncMock()
    exchange.fetch_ticker = AsyncMock(return_value={"last": 45000, "bid": 44990, "ask": 45010})
    exchange.fetch_tickers = AsyncMock(return_value={"BTC/USD": {"last": 45000}})
    exchange.fetch_ohlcv = AsyncMock(return_value=[[1, 2, 3, 4, 5, 6]])
    exchange.fetch_order_book = AsyncMock(return_value={"bids": [], "asks": []})
    exchange.fetch_markets = AsyncMock(return_value=[{"symbol": "BTC/USD"}])
    exchange.load_markets = AsyncMock()
    exchange.markets = {
        "BTC/USD": {"limits": {"amount": {"min": 0.001}}, "precision": {"price": 2}}
    }
    exchange.fetch_balance = AsyncMock(return_value={"free": {"USD": 1000, "BTC": 0.5}})
    exchange.create_market_order = AsyncMock(return_value={"id": "1", "status": "closed"})
    exchange.create_limit_order = AsyncMock(return_value={"id": "2", "status": "open"})
    exchange.create_order = AsyncMock(return_value={"id": "3", "status": "open"})
    exchange.cancel_order = AsyncMock(return_value={"id": "1", "status": "canceled"})
    exchange.fetch_order = AsyncMock(return_value={"id": "1", "status": "closed"})
    exchange.fetch_open_orders = AsyncMock(return_value=[{"id": "1"}])
    exchange.fetch_closed_orders = AsyncMock(return_value=[{"id": "2"}])
    exchange.fetch_my_trades = AsyncMock(return_value=[{"id": "t1"}])
    exchange.set_sandbox_mode = MagicMock()
    return exchange


@pytest.fixture
def exchange() -> MagicMock:
    return make_exchange_mock()


class TestInitialize:
    """Tests for KrakenClient.initialize()."""

    async def test_paper_mode_without_sandbox_url(self, exchange: MagicMock) -> None:
        settings = Settings(_env_file=None, trading_mode="paper")
        client = KrakenClient(settings)
        with patch("src.exchange.kraken.ccxt.kraken", return_value=exchange):
            await client.initialize()

        assert client.is_paper_trading is True
        exchange.set_sandbox_mode.assert_not_called()

    async def test_paper_mode_with_sandbox_url_enables_sandbox(self, exchange: MagicMock) -> None:
        exchange.urls = {"test": "https://sandbox.kraken.com"}
        settings = Settings(_env_file=None, trading_mode="paper")
        client = KrakenClient(settings)
        with patch("src.exchange.kraken.ccxt.kraken", return_value=exchange):
            await client.initialize()

        exchange.set_sandbox_mode.assert_called_once_with(True)

    async def test_live_mode_does_not_touch_sandbox(self, exchange: MagicMock) -> None:
        exchange.urls = {"test": "https://sandbox.kraken.com"}
        settings = Settings(_env_file=None, trading_mode="live")
        client = KrakenClient(settings)
        with patch("src.exchange.kraken.ccxt.kraken", return_value=exchange):
            await client.initialize()

        exchange.set_sandbox_mode.assert_not_called()

    async def test_includes_api_credentials_when_present(self, exchange: MagicMock) -> None:
        settings = Settings(
            _env_file=None, kraken_api_key="key", kraken_api_secret="secret"
        )
        client = KrakenClient(settings)
        with patch("src.exchange.kraken.ccxt.kraken", return_value=exchange) as mock_ctor:
            await client.initialize()

        config = mock_ctor.call_args[0][0]
        assert config["apiKey"] == "key"
        assert config["secret"] == "secret"

    async def test_second_call_is_a_no_op(self, exchange: MagicMock) -> None:
        settings = Settings(_env_file=None)
        client = KrakenClient(settings)
        with patch("src.exchange.kraken.ccxt.kraken", return_value=exchange) as mock_ctor:
            await client.initialize()
            await client.initialize()

        mock_ctor.assert_called_once()


class TestClose:
    """Tests for KrakenClient.close()."""

    async def test_closes_and_resets_state(self, exchange: MagicMock) -> None:
        settings = Settings(_env_file=None)
        client = KrakenClient(settings)
        with patch("src.exchange.kraken.ccxt.kraken", return_value=exchange):
            await client.initialize()
            await client.close()

        exchange.close.assert_awaited_once()
        with pytest.raises(RuntimeError):
            client._ensure_initialized()

    async def test_close_without_initialize_is_a_no_op(self) -> None:
        client = KrakenClient(Settings(_env_file=None))
        await client.close()  # should not raise


class TestEnsureInitialized:
    """Tests for the _ensure_initialized guard."""

    def test_raises_when_not_initialized(self) -> None:
        client = KrakenClient(Settings(_env_file=None))
        with pytest.raises(RuntimeError, match="not initialized"):
            client._ensure_initialized()


class TestMarketDataMethods:
    """Tests for public market-data passthrough methods."""

    @pytest.fixture(autouse=True)
    async def _init_client(self, exchange: MagicMock) -> None:
        self.exchange = exchange
        self.client = KrakenClient(Settings(_env_file=None))
        with patch("src.exchange.kraken.ccxt.kraken", return_value=exchange):
            await self.client.initialize()

    async def test_fetch_ticker(self) -> None:
        result = await self.client.fetch_ticker("BTC/USD")
        assert result["last"] == 45000
        self.exchange.fetch_ticker.assert_awaited_once_with("BTC/USD")

    async def test_fetch_tickers(self) -> None:
        result = await self.client.fetch_tickers(["BTC/USD"])
        assert "BTC/USD" in result

    async def test_fetch_ohlcv(self) -> None:
        result = await self.client.fetch_ohlcv("BTC/USD", timeframe="1h", limit=1)
        assert result == [[1, 2, 3, 4, 5, 6]]

    async def test_fetch_order_book(self) -> None:
        result = await self.client.fetch_order_book("BTC/USD")
        assert "bids" in result

    async def test_fetch_markets(self) -> None:
        result = await self.client.fetch_markets()
        assert result[0]["symbol"] == "BTC/USD"

    async def test_get_market_info_found(self) -> None:
        result = await self.client.get_market_info("BTC/USD")
        assert result is not None

    async def test_get_market_info_missing(self) -> None:
        result = await self.client.get_market_info("ETH/USD")
        assert result is None

    async def test_get_minimum_order_amount(self) -> None:
        result = await self.client.get_minimum_order_amount("BTC/USD")
        assert result == Decimal("0.001")

    async def test_get_minimum_order_amount_no_market(self) -> None:
        result = await self.client.get_minimum_order_amount("ETH/USD")
        assert result is None

    async def test_get_price_precision(self) -> None:
        result = await self.client.get_price_precision("BTC/USD")
        assert result == 2

    async def test_get_price_precision_no_market(self) -> None:
        result = await self.client.get_price_precision("ETH/USD")
        assert result is None


class TestAccountMethods:
    """Tests for account/balance methods."""

    @pytest.fixture(autouse=True)
    async def _init_client(self, exchange: MagicMock) -> None:
        self.exchange = exchange
        self.client = KrakenClient(Settings(_env_file=None))
        with patch("src.exchange.kraken.ccxt.kraken", return_value=exchange):
            await self.client.initialize()

    async def test_fetch_balance(self) -> None:
        result = await self.client.fetch_balance()
        assert result["free"]["USD"] == 1000

    async def test_get_free_balance(self) -> None:
        result = await self.client.get_free_balance("USD")
        assert result == Decimal("1000")

    async def test_get_free_balance_missing_currency(self) -> None:
        result = await self.client.get_free_balance("EUR")
        assert result == Decimal("0")


class TestOrderMethods:
    """Tests for order placement/cancellation/history methods."""

    @pytest.fixture(autouse=True)
    async def _init_client(self, exchange: MagicMock) -> None:
        self.exchange = exchange
        self.client = KrakenClient(Settings(_env_file=None))
        with patch("src.exchange.kraken.ccxt.kraken", return_value=exchange):
            await self.client.initialize()

    async def test_create_market_order(self) -> None:
        result = await self.client.create_market_order("BTC/USD", "buy", 0.01)
        assert result["id"] == "1"
        self.exchange.create_market_order.assert_awaited_once_with("BTC/USD", "buy", 0.01)

    async def test_create_limit_order(self) -> None:
        result = await self.client.create_limit_order("BTC/USD", "sell", 0.01, 46000)
        assert result["id"] == "2"

    async def test_create_stop_loss_order(self) -> None:
        result = await self.client.create_stop_loss_order("BTC/USD", "sell", 0.01, 40000)
        assert result["id"] == "3"
        self.exchange.create_order.assert_awaited_once_with(
            symbol="BTC/USD",
            type="stop-loss",
            side="sell",
            amount=0.01,
            price=None,
            params={"stopPrice": 40000},
        )

    async def test_cancel_order(self) -> None:
        result = await self.client.cancel_order("1", "BTC/USD")
        assert result["status"] == "canceled"

    async def test_fetch_order(self) -> None:
        result = await self.client.fetch_order("1", "BTC/USD")
        assert result["id"] == "1"

    async def test_fetch_open_orders(self) -> None:
        result = await self.client.fetch_open_orders()
        assert len(result) == 1

    async def test_fetch_closed_orders(self) -> None:
        result = await self.client.fetch_closed_orders()
        assert len(result) == 1

    async def test_fetch_my_trades(self) -> None:
        result = await self.client.fetch_my_trades()
        assert len(result) == 1


class TestAsyncContextManager:
    """Tests for KrakenClient used as an async context manager."""

    async def test_enter_initializes_and_exit_closes(self, exchange: MagicMock) -> None:
        settings = Settings(_env_file=None)
        with patch("src.exchange.kraken.ccxt.kraken", return_value=exchange):
            async with KrakenClient(settings) as client:
                assert client._initialized is True

        exchange.close.assert_awaited_once()
