"""Tests for order execution: paper trading simulator and live executor."""

from decimal import Decimal
from unittest.mock import AsyncMock

import pytest

from src.config import Settings
from src.exchange.executor import (
    Order,
    OrderExecutor,
    OrderSide,
    OrderStatus,
    OrderType,
    PaperTradingSimulator,
)


@pytest.fixture
def kraken_client() -> AsyncMock:
    client = AsyncMock()
    client.fetch_ticker.return_value = {"bid": 44990, "ask": 45010}
    return client


class TestOrderToDict:
    """Tests for Order.to_dict()."""

    def test_serializes_all_fields(self) -> None:
        order = Order(
            id="abc",
            symbol="BTC/USD",
            side=OrderSide.BUY,
            order_type=OrderType.MARKET,
            amount=Decimal("0.01"),
            price=Decimal("45000"),
            status=OrderStatus.FILLED,
            filled_amount=Decimal("0.01"),
            average_fill_price=Decimal("45000"),
            exchange_order_id="ex1",
            is_paper=True,
        )
        data = order.to_dict()
        assert data["id"] == "abc"
        assert data["side"] == "buy"
        assert data["order_type"] == "market"
        assert data["price"] == "45000"
        assert data["status"] == "filled"
        assert data["average_fill_price"] == "45000"
        assert data["is_paper"] is True

    def test_serializes_none_price_and_fill(self) -> None:
        order = Order(
            id="abc",
            symbol="BTC/USD",
            side=OrderSide.SELL,
            order_type=OrderType.MARKET,
            amount=Decimal("0.01"),
            price=None,
            status=OrderStatus.PENDING,
        )
        data = order.to_dict()
        assert data["price"] is None
        assert data["average_fill_price"] is None
        assert data["error_message"] is None


class TestPaperTradingSimulatorBalances:
    """Tests for balance get/set on the paper simulator."""

    def test_default_usd_balance(self, kraken_client: AsyncMock) -> None:
        sim = PaperTradingSimulator(kraken_client)
        assert sim.get_balance("USD") == Decimal("10000")

    def test_unknown_currency_defaults_to_zero(self, kraken_client: AsyncMock) -> None:
        sim = PaperTradingSimulator(kraken_client)
        assert sim.get_balance("BTC") == Decimal("0")

    def test_set_balance(self, kraken_client: AsyncMock) -> None:
        sim = PaperTradingSimulator(kraken_client)
        sim.set_balance("BTC", Decimal("2"))
        assert sim.get_balance("BTC") == Decimal("2")

    def test_get_all_balances_is_a_copy(self, kraken_client: AsyncMock) -> None:
        sim = PaperTradingSimulator(kraken_client)
        balances = sim.get_all_balances()
        balances["USD"] = Decimal("0")
        assert sim.get_balance("USD") == Decimal("10000")


class TestPaperTradingSimulatorMarketOrders:
    """Tests for PaperTradingSimulator.execute_market_order()."""

    async def test_buy_fills_at_ask_and_updates_balances(self, kraken_client: AsyncMock) -> None:
        sim = PaperTradingSimulator(kraken_client)
        order = await sim.execute_market_order("BTC/USD", OrderSide.BUY, Decimal("0.1"))

        assert order.status == OrderStatus.FILLED
        assert order.average_fill_price == Decimal("45010")
        assert sim.get_balance("BTC") == Decimal("0.1")
        assert sim.get_balance("USD") == Decimal("10000") - Decimal("0.1") * Decimal("45010")

    async def test_sell_fills_at_bid_and_updates_balances(self, kraken_client: AsyncMock) -> None:
        sim = PaperTradingSimulator(kraken_client)
        sim.set_balance("BTC", Decimal("1"))
        order = await sim.execute_market_order("BTC/USD", OrderSide.SELL, Decimal("0.5"))

        assert order.status == OrderStatus.FILLED
        assert order.average_fill_price == Decimal("44990")
        assert sim.get_balance("BTC") == Decimal("0.5")
        assert sim.get_balance("USD") == Decimal("10000") + Decimal("0.5") * Decimal("44990")

    async def test_buy_fails_on_insufficient_quote_balance(self, kraken_client: AsyncMock) -> None:
        sim = PaperTradingSimulator(kraken_client)
        order = await sim.execute_market_order("BTC/USD", OrderSide.BUY, Decimal("1000"))

        assert order.status == OrderStatus.FAILED
        assert order.error_message is not None
        assert "USD" in order.error_message
        assert sim.get_balance("USD") == Decimal("10000")

    async def test_sell_fails_on_insufficient_base_balance(self, kraken_client: AsyncMock) -> None:
        sim = PaperTradingSimulator(kraken_client)
        order = await sim.execute_market_order("BTC/USD", OrderSide.SELL, Decimal("1"))

        assert order.status == OrderStatus.FAILED
        assert order.error_message is not None
        assert "BTC" in order.error_message


class TestPaperTradingSimulatorLimitOrders:
    """Tests for PaperTradingSimulator limit order placement and cancellation."""

    async def test_execute_limit_order_is_open(self, kraken_client: AsyncMock) -> None:
        sim = PaperTradingSimulator(kraken_client)
        order = await sim.execute_limit_order(
            "BTC/USD", OrderSide.BUY, Decimal("0.1"), Decimal("40000")
        )
        assert order.status == OrderStatus.OPEN
        assert sim.get_order(order.id) is order

    async def test_cancel_open_order(self, kraken_client: AsyncMock) -> None:
        sim = PaperTradingSimulator(kraken_client)
        order = await sim.execute_limit_order(
            "BTC/USD", OrderSide.BUY, Decimal("0.1"), Decimal("40000")
        )
        cancelled = sim.cancel_order(order.id)
        assert cancelled is not None
        assert cancelled.status == OrderStatus.CANCELLED

    async def test_cancel_unknown_order_returns_none(self, kraken_client: AsyncMock) -> None:
        sim = PaperTradingSimulator(kraken_client)
        assert sim.cancel_order("does-not-exist") is None

    async def test_cancel_already_filled_order_is_a_no_op(self, kraken_client: AsyncMock) -> None:
        sim = PaperTradingSimulator(kraken_client)
        filled = await sim.execute_market_order("BTC/USD", OrderSide.BUY, Decimal("0.01"))
        result = sim.cancel_order(filled.id)
        assert result is not None
        assert result.status == OrderStatus.FILLED

    async def test_get_order_unknown_returns_none(self, kraken_client: AsyncMock) -> None:
        sim = PaperTradingSimulator(kraken_client)
        assert sim.get_order("nope") is None

    async def test_get_open_orders_filters_by_status_and_symbol(
        self, kraken_client: AsyncMock
    ) -> None:
        sim = PaperTradingSimulator(kraken_client)
        await sim.execute_limit_order("BTC/USD", OrderSide.BUY, Decimal("0.1"), Decimal("40000"))
        await sim.execute_limit_order("ETH/USD", OrderSide.BUY, Decimal("1"), Decimal("2000"))
        await sim.execute_market_order("BTC/USD", OrderSide.BUY, Decimal("0.01"))

        all_open = sim.get_open_orders()
        assert len(all_open) == 2

        btc_open = sim.get_open_orders("BTC/USD")
        assert len(btc_open) == 1
        assert btc_open[0].symbol == "BTC/USD"


def make_paper_executor(client: AsyncMock) -> OrderExecutor:
    settings = Settings(_env_file=None, trading_mode="paper")
    return OrderExecutor(client, settings, max_retries=2, retry_delay=0)


def make_live_executor(client: AsyncMock) -> OrderExecutor:
    settings = Settings(_env_file=None, trading_mode="live")
    return OrderExecutor(client, settings, max_retries=2, retry_delay=0)


class TestOrderExecutorPaperMode:
    """Tests for OrderExecutor delegating to the paper simulator."""

    async def test_is_paper_trading_true(self, kraken_client: AsyncMock) -> None:
        executor = make_paper_executor(kraken_client)
        assert executor.is_paper_trading is True

    async def test_execute_market_order_delegates_to_simulator(
        self, kraken_client: AsyncMock
    ) -> None:
        executor = make_paper_executor(kraken_client)
        order = await executor.execute_market_order("BTC/USD", OrderSide.BUY, Decimal("0.01"))
        assert order.is_paper is True
        assert order.status == OrderStatus.FILLED

    async def test_execute_limit_order_delegates_to_simulator(
        self, kraken_client: AsyncMock
    ) -> None:
        executor = make_paper_executor(kraken_client)
        order = await executor.execute_limit_order(
            "BTC/USD", OrderSide.BUY, Decimal("0.01"), Decimal("40000")
        )
        assert order.is_paper is True
        assert order.status == OrderStatus.OPEN

    async def test_cancel_order_true_when_cancelled(self, kraken_client: AsyncMock) -> None:
        executor = make_paper_executor(kraken_client)
        order = await executor.execute_limit_order(
            "BTC/USD", OrderSide.BUY, Decimal("0.01"), Decimal("40000")
        )
        assert await executor.cancel_order(order.id, "BTC/USD") is True

    async def test_cancel_order_false_when_unknown(self, kraken_client: AsyncMock) -> None:
        executor = make_paper_executor(kraken_client)
        assert await executor.cancel_order("nope", "BTC/USD") is False

    async def test_get_balance(self, kraken_client: AsyncMock) -> None:
        executor = make_paper_executor(kraken_client)
        assert await executor.get_balance("USD") == Decimal("10000")

    async def test_get_all_balances_stringifies_values(self, kraken_client: AsyncMock) -> None:
        executor = make_paper_executor(kraken_client)
        balances = await executor.get_all_balances()
        assert balances["USD"] == "10000"

    async def test_get_open_orders(self, kraken_client: AsyncMock) -> None:
        executor = make_paper_executor(kraken_client)
        await executor.execute_limit_order(
            "BTC/USD", OrderSide.BUY, Decimal("0.01"), Decimal("40000")
        )
        assert len(executor.get_open_orders()) == 1

    async def test_set_paper_balance(self, kraken_client: AsyncMock) -> None:
        executor = make_paper_executor(kraken_client)
        executor.set_paper_balance("BTC", Decimal("5"))
        assert await executor.get_balance("BTC") == Decimal("5")


class TestOrderExecutorLiveMode:
    """Tests for OrderExecutor's live-trading paths against a mocked client."""

    async def test_is_paper_trading_false(self, kraken_client: AsyncMock) -> None:
        executor = make_live_executor(kraken_client)
        assert executor.is_paper_trading is False

    async def test_execute_market_order_success(self, kraken_client: AsyncMock) -> None:
        # Kraken's real create response: no status/filled/average/fee, only an id.
        kraken_client.create_market_order.return_value = {"id": "ex1", "txid": ["ex1"]}
        kraken_client.fetch_order.return_value = {
            "status": "closed",  # ccxt's spelling for filled
            "filled": "0.01",
            "average": "45000",
            "fee": {"cost": "0.05", "currency": "USD"},
        }
        executor = make_live_executor(kraken_client)
        order = await executor.execute_market_order("BTC/USD", OrderSide.BUY, Decimal("0.01"))

        assert order.status == OrderStatus.FILLED
        assert order.exchange_order_id == "ex1"
        assert order.average_fill_price == Decimal("45000")
        assert order.fee == Decimal("0.05")
        assert order.is_paper is False
        kraken_client.create_market_order.assert_awaited_once_with(
            symbol="BTC/USD", side="buy", amount=0.01
        )
        kraken_client.fetch_order.assert_awaited_once_with("ex1", "BTC/USD")

    async def test_execute_market_order_no_average_price(self, kraken_client: AsyncMock) -> None:
        kraken_client.create_market_order.return_value = {"id": "ex1", "txid": ["ex1"]}
        kraken_client.fetch_order.return_value = {"status": "open", "filled": "0"}
        executor = make_live_executor(kraken_client)
        order = await executor.execute_market_order("BTC/USD", OrderSide.BUY, Decimal("0.01"))

        assert order.average_fill_price is None
        assert order.status == OrderStatus.OPEN

    async def test_execute_market_order_retries_then_succeeds(
        self, kraken_client: AsyncMock
    ) -> None:
        kraken_client.create_market_order.side_effect = [
            RuntimeError("network blip"),
            {"id": "ex1", "txid": ["ex1"]},
        ]
        kraken_client.fetch_order.return_value = {"status": "closed", "filled": "0.01"}
        executor = make_live_executor(kraken_client)
        order = await executor.execute_market_order("BTC/USD", OrderSide.BUY, Decimal("0.01"))

        assert order.status == OrderStatus.FILLED
        assert kraken_client.create_market_order.await_count == 2

    async def test_a_real_kraken_create_response_does_not_raise_or_retry(
        self, kraken_client: AsyncMock
    ) -> None:
        """Regression: Kraken's create-order response has no status field at all, and
        ccxt's parsed dict still carries a "status" key with value None. The old code
        (`OrderStatus(result.get("status", "filled"))`) raised on this - the key being
        *present* with value None meant `.get`'s fallback never applied - and the
        surrounding retry loop then placed a second real order for one Kraken had
        already accepted.
        """
        kraken_client.create_market_order.return_value = {
            "id": "ex1",
            "txid": ["ex1"],
            "status": None,
        }
        kraken_client.fetch_order.return_value = {
            "status": "closed",
            "filled": "0.01",
            "average": "45000",
        }
        executor = make_live_executor(kraken_client)

        order = await executor.execute_market_order("BTC/USD", OrderSide.BUY, Decimal("0.01"))

        assert order.status == OrderStatus.FILLED
        assert kraken_client.create_market_order.await_count == 1  # never retried

    async def test_ccxt_cancelled_spelling_maps_correctly(self, kraken_client: AsyncMock) -> None:
        """ccxt spells it "canceled" (one L); this codebase spells it "cancelled" (two)."""
        kraken_client.create_market_order.return_value = {"id": "ex1", "txid": ["ex1"]}
        kraken_client.fetch_order.return_value = {"status": "canceled", "filled": "0"}
        executor = make_live_executor(kraken_client)

        order = await executor.execute_market_order("BTC/USD", OrderSide.BUY, Decimal("0.01"))

        assert order.status == OrderStatus.CANCELLED

    async def test_fetched_status_still_open_polls_before_giving_up(
        self, kraken_client: AsyncMock
    ) -> None:
        kraken_client.create_market_order.return_value = {"id": "ex1", "txid": ["ex1"]}
        kraken_client.fetch_order.side_effect = [
            {"status": "open", "filled": "0"},
            {"status": "closed", "filled": "0.01", "average": "45000"},
        ]
        executor = make_live_executor(kraken_client)

        order = await executor.execute_market_order("BTC/USD", OrderSide.BUY, Decimal("0.01"))

        assert order.status == OrderStatus.FILLED
        assert kraken_client.fetch_order.await_count == 2
        kraken_client.create_market_order.assert_awaited_once()  # still never retried

    async def test_a_transient_fetch_error_is_retried_not_given_up_on(
        self, kraken_client: AsyncMock
    ) -> None:
        """Regression: observed live against real Kraken - fetch_order raised
        OrderNotFound immediately after an order was created, for an order that had,
        in fact, already filled; fetching again moments later succeeded cleanly. The
        old code gave up on the first exception instead of retrying like it already
        did for a status still reading "open"."""
        kraken_client.create_market_order.return_value = {"id": "ex1", "txid": ["ex1"]}
        kraken_client.fetch_order.side_effect = [
            RuntimeError("OrderNotFound"),
            {"status": "closed", "filled": "0.01", "average": "45000"},
        ]
        executor = make_live_executor(kraken_client)

        order = await executor.execute_market_order("BTC/USD", OrderSide.BUY, Decimal("0.01"))

        assert order.status == OrderStatus.FILLED
        assert kraken_client.fetch_order.await_count == 2
        kraken_client.create_market_order.assert_awaited_once()  # still never retried

    async def test_unconfirmable_fill_status_reports_open_not_failed(
        self, kraken_client: AsyncMock
    ) -> None:
        """A real order Kraken accepted must never come back FAILED - that would read as
        safe to retry when a real order already exists."""
        kraken_client.create_market_order.return_value = {"id": "ex1", "txid": ["ex1"]}
        kraken_client.fetch_order.side_effect = RuntimeError("network blip")
        executor = make_live_executor(kraken_client)

        order = await executor.execute_market_order("BTC/USD", OrderSide.BUY, Decimal("0.01"))

        assert order.status == OrderStatus.OPEN
        assert order.exchange_order_id == "ex1"
        assert kraken_client.create_market_order.await_count == 1

    async def test_fee_falls_back_to_trades_when_the_order_does_not_report_one(
        self, kraken_client: AsyncMock
    ) -> None:
        kraken_client.create_market_order.return_value = {"id": "ex1", "txid": ["ex1"]}
        kraken_client.fetch_order.return_value = {
            "status": "closed",
            "filled": "0.01",
            "average": "45000",
            # no "fee" key - Kraken doesn't always report it on the order itself
        }
        kraken_client.fetch_my_trades.return_value = [
            {"order": "ex1", "fee": {"cost": "0.03", "currency": "USD"}},
            {"order": "other-order", "fee": {"cost": "99", "currency": "USD"}},
        ]
        executor = make_live_executor(kraken_client)

        order = await executor.execute_market_order("BTC/USD", OrderSide.BUY, Decimal("0.01"))

        assert order.fee == Decimal("0.03")  # only the matching order's trade, not "other-order"

    async def test_fee_recovery_failure_falls_back_to_zero(self, kraken_client: AsyncMock) -> None:
        kraken_client.create_market_order.return_value = {"id": "ex1", "txid": ["ex1"]}
        kraken_client.fetch_order.return_value = {
            "status": "closed",
            "filled": "0.01",
            "average": "45000",
        }
        kraken_client.fetch_my_trades.side_effect = RuntimeError("down")
        executor = make_live_executor(kraken_client)

        order = await executor.execute_market_order("BTC/USD", OrderSide.BUY, Decimal("0.01"))

        assert order.status == OrderStatus.FILLED  # the fill itself is still reported
        assert order.fee == Decimal("0")

    async def test_no_exchange_order_id_still_reports_open_not_failed(
        self, kraken_client: AsyncMock
    ) -> None:
        """Create succeeded (no exception) but returned no id to fetch a fill for."""
        kraken_client.create_market_order.return_value = {}
        executor = make_live_executor(kraken_client)

        order = await executor.execute_market_order("BTC/USD", OrderSide.BUY, Decimal("0.01"))

        assert order.status == OrderStatus.OPEN
        assert order.exchange_order_id is None
        kraken_client.fetch_order.assert_not_awaited()

    async def test_execute_market_order_all_retries_fail(self, kraken_client: AsyncMock) -> None:
        kraken_client.create_market_order.side_effect = RuntimeError("down")
        executor = make_live_executor(kraken_client)
        order = await executor.execute_market_order("BTC/USD", OrderSide.BUY, Decimal("0.01"))

        assert order.status == OrderStatus.FAILED
        assert order.error_message == "down"
        assert kraken_client.create_market_order.await_count == 2

    async def test_execute_limit_order_success(self, kraken_client: AsyncMock) -> None:
        kraken_client.create_limit_order.return_value = {
            "id": "ex2",
            "status": "open",
            "filled": "0",
            "average": None,
        }
        executor = make_live_executor(kraken_client)
        order = await executor.execute_limit_order(
            "BTC/USD", OrderSide.SELL, Decimal("0.01"), Decimal("46000")
        )

        assert order.status == OrderStatus.OPEN
        assert order.exchange_order_id == "ex2"
        kraken_client.create_limit_order.assert_awaited_once_with(
            symbol="BTC/USD", side="sell", amount=0.01, price=46000.0
        )

    async def test_execute_limit_order_all_retries_fail(self, kraken_client: AsyncMock) -> None:
        kraken_client.create_limit_order.side_effect = RuntimeError("rejected")
        executor = make_live_executor(kraken_client)
        order = await executor.execute_limit_order(
            "BTC/USD", OrderSide.SELL, Decimal("0.01"), Decimal("46000")
        )

        assert order.status == OrderStatus.FAILED
        assert order.error_message == "rejected"

    async def test_cancel_order_success(self, kraken_client: AsyncMock) -> None:
        executor = make_live_executor(kraken_client)
        assert await executor.cancel_order("ex1", "BTC/USD") is True
        kraken_client.cancel_order.assert_awaited_once_with("ex1", "BTC/USD")

    async def test_cancel_order_failure_returns_false(self, kraken_client: AsyncMock) -> None:
        kraken_client.cancel_order.side_effect = RuntimeError("already closed")
        executor = make_live_executor(kraken_client)
        assert await executor.cancel_order("ex1", "BTC/USD") is False

    async def test_get_balance_delegates_to_client(self, kraken_client: AsyncMock) -> None:
        kraken_client.get_free_balance.return_value = Decimal("42")
        executor = make_live_executor(kraken_client)
        assert await executor.get_balance("USD") == Decimal("42")

    async def test_get_all_balances_delegates_to_client(self, kraken_client: AsyncMock) -> None:
        kraken_client.fetch_balance.return_value = {"free": {"USD": 100}}
        executor = make_live_executor(kraken_client)
        balances = await executor.get_all_balances()
        assert balances == {"USD": 100}

    async def test_get_open_orders_returns_empty_list(self, kraken_client: AsyncMock) -> None:
        executor = make_live_executor(kraken_client)
        assert executor.get_open_orders() == []

    async def test_set_paper_balance_warns_and_does_not_raise(
        self, kraken_client: AsyncMock
    ) -> None:
        executor = make_live_executor(kraken_client)
        executor.set_paper_balance("USD", Decimal("1"))  # should not raise
