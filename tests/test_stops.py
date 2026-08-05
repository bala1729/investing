"""Tests for stop-loss enforcement and the trailing-stop ratchet.

Covers the three hazards that make poll-based and exchange-native enforcement
incompatible if built naively: both mechanisms selling the same position, a
native stop filling while the bot is away, and moving a resting stop by
cancel-then-create.
"""

from decimal import Decimal
from unittest.mock import AsyncMock

import pandas as pd
import pytest

from src.bot.engine import TradingEngine
from src.bot.strategies.base import Strategy
from src.config import Settings, StopEnforcement, TradingMode
from src.database.models import init_database
from src.database.repository import UnitOfWork
from src.exchange.executor import Order, OrderSide, OrderStatus, OrderType
from src.risk.manager import RiskManager


@pytest.fixture(autouse=True)
async def _init_db(db_settings: Settings) -> None:
    await init_database()


def make_client(last_price: Decimal = Decimal("100")) -> AsyncMock:
    client = AsyncMock()
    client.fetch_ticker.return_value = {"last": float(last_price)}
    client.fetch_open_orders.return_value = []
    client.fetch_closed_orders.return_value = []
    return client


def make_executor(
    quote_balance: Decimal = Decimal("10000"), base_balance: Decimal | None = None
) -> AsyncMock:
    executor = AsyncMock()

    async def _balance(currency: str) -> Decimal:
        if currency == "BTC" and base_balance is not None:
            return base_balance
        return quote_balance

    executor.get_balance.side_effect = _balance
    executor.execute_market_order.return_value = Order(
        id="o1",
        symbol="BTC/USD",
        side=OrderSide.SELL,
        order_type=OrderType.MARKET,
        amount=Decimal("1"),
        price=None,
        status=OrderStatus.FILLED,
        filled_amount=Decimal("1"),
        average_fill_price=Decimal("98"),
        exchange_order_id="x1",
        is_paper=True,
    )
    return executor


async def open_position(
    symbol: str = "BTC/USD",
    amount: Decimal = Decimal("1"),
    entry: Decimal = Decimal("100"),
    stop: Decimal | None = Decimal("98"),
) -> None:
    async with UnitOfWork() as uow:
        await uow.positions.create_or_update(
            symbol=symbol,
            side="long",
            amount=amount,
            entry_price=entry,
            strategy="test",
            is_paper=True,
            stop_loss=stop,
            take_profit=None,
        )
        await uow.commit()


async def stored_stop(symbol: str = "BTC/USD") -> Decimal | None:
    async with UnitOfWork() as uow:
        position = await uow.positions.get_by_symbol(symbol)
        return position.stop_loss if position else None


async def stored_amount(symbol: str = "BTC/USD") -> Decimal:
    async with UnitOfWork() as uow:
        position = await uow.positions.get_by_symbol(symbol)
        return position.amount if position else Decimal("0")


def poll_settings(base: Settings, **kwargs: object) -> Settings:
    """Enforcement is OFF by default, so every test must opt in explicitly."""
    return base.model_copy(update={"stop_enforcement": StopEnforcement.POLL, **kwargs})


def ratchet_settings(base: Settings, **kwargs: object) -> Settings:
    return poll_settings(base, trailing_stop_trigger_pct=2.0,
                         trailing_stop_lock_pct=1.0, **kwargs)


class TestTrailingStopCalculator:
    """The pure ratchet arithmetic both mechanisms consume."""

    def test_disabled_by_default(self, db_settings: Settings) -> None:
        rm = RiskManager(db_settings)
        assert rm.calculate_trailing_stop_price(
            Decimal("100"), Decimal("98"), Decimal("200")
        ) is None

    def test_no_raise_below_trigger(self, db_settings: Settings) -> None:
        rm = RiskManager(ratchet_settings(db_settings))
        assert rm.calculate_trailing_stop_price(
            Decimal("100"), Decimal("98"), Decimal("101.99")
        ) is None

    def test_raises_at_trigger(self, db_settings: Settings) -> None:
        rm = RiskManager(ratchet_settings(db_settings))
        assert rm.calculate_trailing_stop_price(
            Decimal("100"), Decimal("98"), Decimal("102")
        ) == Decimal("101")

    def test_is_idempotent_once_ratcheted(self, db_settings: Settings) -> None:
        """A second trigger must not re-raise; the ratchet is one step, not continuous."""
        rm = RiskManager(ratchet_settings(db_settings))
        assert rm.calculate_trailing_stop_price(
            Decimal("100"), Decimal("101"), Decimal("150")
        ) is None

    def test_never_lowers_an_existing_stop(self, db_settings: Settings) -> None:
        rm = RiskManager(ratchet_settings(db_settings))
        assert rm.calculate_trailing_stop_price(
            Decimal("100"), Decimal("105"), Decimal("102")
        ) is None

    def test_rejects_non_positive_entry(self, db_settings: Settings) -> None:
        rm = RiskManager(ratchet_settings(db_settings))
        with pytest.raises(ValueError, match="entry_price must be positive"):
            rm.calculate_trailing_stop_price(Decimal("0"), None, Decimal("1"))


class TestSettingsValidation:
    def test_lock_at_or_above_trigger_is_rejected(self) -> None:
        """Such a stop would sit above the price that armed it and fill instantly."""
        with pytest.raises(ValueError, match="must be below trailing_stop_trigger_pct"):
            Settings(_env_file=None, trailing_stop_trigger_pct=2.0, trailing_stop_lock_pct=2.0)

    def test_negative_percentages_are_rejected(self) -> None:
        with pytest.raises(ValueError, match="cannot be negative"):
            Settings(_env_file=None, trailing_stop_trigger_pct=-1.0)

    def test_a_valid_ratchet_is_accepted(self) -> None:
        settings = Settings(
            _env_file=None, trailing_stop_trigger_pct=2.0, trailing_stop_lock_pct=1.0
        )
        assert settings.trailing_stop_lock_pct == 1.0

    def test_enforcement_is_off_by_default(self) -> None:
        """Shipped disabled: measurement found no stop configuration that helped."""
        assert Settings(_env_file=None).stop_enforcement is StopEnforcement.OFF
        assert Settings(_env_file=None).effective_stop_enforcement is StopEnforcement.OFF

    def test_off_beats_paper_fallback(self) -> None:
        settings = Settings(
            _env_file=None, trading_mode=TradingMode.PAPER,
            stop_enforcement=StopEnforcement.OFF,
        )
        assert settings.effective_stop_enforcement is StopEnforcement.OFF

    def test_paper_trading_always_polls(self) -> None:
        """Gap 1: the paper simulator has no resting orders, so native cannot apply."""
        settings = Settings(
            _env_file=None, trading_mode=TradingMode.PAPER,
            stop_enforcement=StopEnforcement.NATIVE,
        )
        assert settings.effective_stop_enforcement is StopEnforcement.POLL

    def test_live_honours_the_configured_mechanism(self) -> None:
        settings = Settings(
            _env_file=None, trading_mode=TradingMode.LIVE,
            stop_enforcement=StopEnforcement.NATIVE,
        )
        assert settings.effective_stop_enforcement is StopEnforcement.NATIVE


class TestRaiseStopLoss:
    async def test_raises_and_reports_change(self, db_settings: Settings) -> None:
        await open_position(stop=Decimal("98"))
        async with UnitOfWork() as uow:
            assert await uow.positions.raise_stop_loss("BTC/USD", Decimal("101")) is True
            await uow.commit()
        assert await stored_stop() == Decimal("101")

    async def test_will_not_lower(self, db_settings: Settings) -> None:
        await open_position(stop=Decimal("101"))
        async with UnitOfWork() as uow:
            assert await uow.positions.raise_stop_loss("BTC/USD", Decimal("99")) is False
            await uow.commit()
        assert await stored_stop() == Decimal("101")

    async def test_ignores_a_closed_position(self, db_settings: Settings) -> None:
        async with UnitOfWork() as uow:
            assert await uow.positions.raise_stop_loss("BTC/USD", Decimal("101")) is False


class TestPollEnforcement:
    async def test_no_position_is_a_no_op(self, db_settings: Settings) -> None:
        settings = poll_settings(db_settings)
        engine = TradingEngine(
            make_client(), make_executor(), RiskManager(settings), settings
        )
        assert await engine.enforce_stops("BTC/USD") is None

    async def test_price_above_stop_lets_the_cycle_continue(self, db_settings: Settings) -> None:
        await open_position()
        settings = poll_settings(db_settings)
        engine = TradingEngine(
            make_client(Decimal("99")), make_executor(), RiskManager(settings), settings
        )
        assert await engine.enforce_stops("BTC/USD") is None
        assert await stored_amount() == Decimal("1")

    async def test_price_at_stop_sells(self, db_settings: Settings) -> None:
        await open_position()
        executor = make_executor(base_balance=Decimal("1"))
        settings = poll_settings(db_settings)
        engine = TradingEngine(
            make_client(Decimal("98")), executor, RiskManager(settings), settings
        )

        result = await engine.enforce_stops("BTC/USD")

        assert result is not None and result.executed is True
        executor.execute_market_order.assert_awaited_once()
        assert await stored_amount() == Decimal("0")

    async def test_ratchet_raises_the_stored_stop(self, db_settings: Settings) -> None:
        await open_position()
        settings = ratchet_settings(db_settings)
        engine = TradingEngine(
            make_client(Decimal("102")), make_executor(), RiskManager(settings), settings
        )

        assert await engine.enforce_stops("BTC/USD") is None
        assert await stored_stop() == Decimal("101")

    async def test_ratcheted_stop_then_triggers_on_a_pullback(self, db_settings: Settings) -> None:
        """The whole point: a pullback to +1% now exits instead of riding to -2%."""
        await open_position()
        settings = ratchet_settings(db_settings)
        executor = make_executor(base_balance=Decimal("1"))

        engine = TradingEngine(
            make_client(Decimal("102")), executor, RiskManager(settings), settings
        )
        await engine.enforce_stops("BTC/USD")

        engine = TradingEngine(
            make_client(Decimal("100.5")), executor, RiskManager(settings), settings
        )
        result = await engine.enforce_stops("BTC/USD")

        assert result is not None and result.executed is True
        assert await stored_amount() == Decimal("0")


class TestNativeEnforcement:
    def _live(self, base: Settings) -> Settings:
        return base.model_copy(
            update={
                "trading_mode": TradingMode.LIVE,
                "stop_enforcement": StopEnforcement.NATIVE,
                "trailing_stop_trigger_pct": 2.0,
                "trailing_stop_lock_pct": 1.0,
            }
        )

    async def test_bot_does_not_sell_when_the_exchange_owns_the_stop(
        self, db_settings: Settings
    ) -> None:
        """Gap 1: price is below the stop, but the resting order is the only seller."""
        await open_position()
        settings = self._live(db_settings)
        client = make_client(Decimal("90"))
        executor = make_executor(base_balance=Decimal("1"))
        engine = TradingEngine(client, executor, RiskManager(settings), settings)

        assert await engine.enforce_stops("BTC/USD") is None
        executor.execute_market_order.assert_not_awaited()
        assert await stored_amount() == Decimal("1")

    async def test_places_a_resting_stop_when_none_exists(self, db_settings: Settings) -> None:
        await open_position()
        settings = self._live(db_settings)
        client = make_client(Decimal("99"))
        engine = TradingEngine(client, make_executor(base_balance=Decimal("1")),
                               RiskManager(settings), settings)

        await engine.enforce_stops("BTC/USD")

        client.create_stop_loss_order.assert_awaited_once()
        assert client.create_stop_loss_order.await_args.args[3] == pytest.approx(98.0)

    async def test_existing_resting_stop_is_left_alone_when_unchanged(
        self, db_settings: Settings
    ) -> None:
        """Gap 3: no needless cancel/create, which would open an unprotected window."""
        await open_position()
        settings = self._live(db_settings)
        client = make_client(Decimal("99"))
        client.fetch_open_orders.return_value = [{"id": "s1", "type": "stop-loss"}]
        engine = TradingEngine(client, make_executor(base_balance=Decimal("1")),
                               RiskManager(settings), settings)

        await engine.enforce_stops("BTC/USD")

        client.cancel_order.assert_not_awaited()
        client.create_stop_loss_order.assert_not_awaited()

    async def test_ratchet_cancels_and_replaces_the_resting_stop(
        self, db_settings: Settings
    ) -> None:
        await open_position()
        settings = self._live(db_settings)
        client = make_client(Decimal("102"))
        client.fetch_open_orders.return_value = [{"id": "s1", "type": "stop-loss"}]
        engine = TradingEngine(client, make_executor(base_balance=Decimal("1")),
                               RiskManager(settings), settings)

        await engine.enforce_stops("BTC/USD")

        client.cancel_order.assert_awaited_once_with("s1", "BTC/USD")
        assert client.create_stop_loss_order.await_args.args[3] == pytest.approx(101.0)

    async def test_a_cancel_that_lost_the_race_still_places_the_new_stop(
        self, db_settings: Settings
    ) -> None:
        """Gap 3: cancel failing means it already filled - do not abort the replace."""
        await open_position()
        settings = self._live(db_settings)
        client = make_client(Decimal("102"))
        client.fetch_open_orders.return_value = [{"id": "s1", "type": "stop-loss"}]
        client.cancel_order.side_effect = RuntimeError("order already filled")
        engine = TradingEngine(client, make_executor(base_balance=Decimal("1")),
                               RiskManager(settings), settings)

        await engine.enforce_stops("BTC/USD")

        client.create_stop_loss_order.assert_awaited_once()

    async def test_reconciles_a_stop_that_filled_while_the_bot_was_away(
        self, db_settings: Settings
    ) -> None:
        """Gap 2: exchange balance is gone, so the local position must be closed."""
        await open_position()
        settings = self._live(db_settings)
        client = make_client(Decimal("97"))
        client.fetch_closed_orders.return_value = [
            {"side": "sell", "average": 98.0, "id": "s1"}
        ]
        executor = make_executor(base_balance=Decimal("0"))
        engine = TradingEngine(client, executor, RiskManager(settings), settings)

        result = await engine.enforce_stops("BTC/USD")

        assert result is not None and result.executed is False
        assert "closed on the exchange" in (result.reason or "")
        assert await stored_amount() == Decimal("0")
        executor.execute_market_order.assert_not_awaited()

    async def test_reconciliation_falls_back_to_the_stop_price(
        self, db_settings: Settings
    ) -> None:
        await open_position()
        settings = self._live(db_settings)
        client = make_client(Decimal("97"))
        client.fetch_closed_orders.return_value = []
        engine = TradingEngine(client, make_executor(base_balance=Decimal("0")),
                               RiskManager(settings), settings)

        assert await engine.enforce_stops("BTC/USD") is not None
        assert await stored_amount() == Decimal("0")

    async def test_dust_does_not_look_like_an_external_close(
        self, db_settings: Settings
    ) -> None:
        """Rounding must not be mistaken for a fill, or every cycle would close the position."""
        await open_position(amount=Decimal("1"))
        settings = self._live(db_settings)
        engine = TradingEngine(make_client(Decimal("99")),
                               make_executor(base_balance=Decimal("0.999")),
                               RiskManager(settings), settings)

        await engine.enforce_stops("BTC/USD")

        assert await stored_amount() == Decimal("1")


class TestNativeEnforcementFailureModes:
    """The error paths matter more than usual here: a silent failure in stop
    handling leaves real money unprotected, so each one is pinned to a defined
    behaviour rather than left to whatever the exception happens to do."""

    def _live(self, base: Settings) -> Settings:
        return base.model_copy(
            update={
                "trading_mode": TradingMode.LIVE,
                "stop_enforcement": StopEnforcement.NATIVE,
            }
        )

    async def test_unreadable_closed_orders_keeps_the_position_open(
        self, db_settings: Settings
    ) -> None:
        """Better a stale position than a close booked at an invented price."""
        await open_position(stop=None)
        settings = self._live(db_settings)
        client = make_client(Decimal("97"))
        client.fetch_closed_orders.side_effect = RuntimeError("api down")
        engine = TradingEngine(client, make_executor(base_balance=Decimal("0")),
                               RiskManager(settings), settings)

        assert await engine.enforce_stops("BTC/USD") is None
        assert await stored_amount() == Decimal("1")

    async def test_non_sell_closed_orders_are_skipped(self, db_settings: Settings) -> None:
        await open_position()
        settings = self._live(db_settings)
        client = make_client(Decimal("97"))
        client.fetch_closed_orders.return_value = [
            {"side": "buy", "average": 500.0},
            {"side": "sell", "average": 98.5},
        ]
        engine = TradingEngine(client, make_executor(base_balance=Decimal("0")),
                               RiskManager(settings), settings)

        assert await engine.enforce_stops("BTC/USD") is not None
        assert await stored_amount() == Decimal("0")

    async def test_unlistable_open_orders_skips_the_sync(self, db_settings: Settings) -> None:
        """Cannot know what rests on the exchange, so placing another would risk a duplicate."""
        await open_position()
        settings = self._live(db_settings)
        client = make_client(Decimal("99"))
        client.fetch_open_orders.side_effect = RuntimeError("api down")
        engine = TradingEngine(client, make_executor(base_balance=Decimal("1")),
                               RiskManager(settings), settings)

        assert await engine.enforce_stops("BTC/USD") is None
        client.create_stop_loss_order.assert_not_awaited()

    async def test_failure_to_place_the_stop_is_loud_and_not_fatal(
        self, db_settings: Settings
    ) -> None:
        await open_position()
        settings = self._live(db_settings)
        client = make_client(Decimal("99"))
        client.create_stop_loss_order.side_effect = RuntimeError("rejected")
        engine = TradingEngine(client, make_executor(base_balance=Decimal("1")),
                               RiskManager(settings), settings)

        assert await engine.enforce_stops("BTC/USD") is None
        assert await stored_amount() == Decimal("1")

    async def test_position_with_no_stop_at_all_is_left_alone(
        self, db_settings: Settings
    ) -> None:
        await open_position(stop=None)
        settings = poll_settings(db_settings, trailing_stop_trigger_pct=0.0)
        engine = TradingEngine(make_client(Decimal("50")), make_executor(),
                               RiskManager(settings), settings)

        assert await engine.enforce_stops("BTC/USD") is None
        assert await stored_amount() == Decimal("1")


class TestStopsRunBeforeStrategy:
    async def test_a_stopped_out_cycle_never_reaches_the_strategy(
        self, db_settings: Settings
    ) -> None:
        """Risk management must not queue behind signal generation."""
        await open_position()
        client = make_client(Decimal("98"))
        settings = poll_settings(db_settings)
        engine = TradingEngine(client, make_executor(base_balance=Decimal("1")),
                               RiskManager(settings), settings)

        class ExplodingStrategy(Strategy):
            def generate_signal(
                self,
                symbol: str,
                candles: "pd.DataFrame",
                higher_tf_candles: "dict[str, pd.DataFrame] | None" = None,
            ) -> None:
                raise AssertionError("strategy must not run after a stop-out")

        result = await engine.run_strategy_once(ExplodingStrategy(), "BTC/USD")

        assert result.executed is True
        client.fetch_ohlcv.assert_not_awaited()


class TestDisabledByDefault:
    """With enforcement off the engine must behave exactly as it did before stops existed."""

    async def test_a_position_far_below_its_stop_is_not_touched(
        self, db_settings: Settings
    ) -> None:
        await open_position(entry=Decimal("100"), stop=Decimal("98"))
        executor = make_executor(base_balance=Decimal("1"))
        engine = TradingEngine(
            make_client(Decimal("50")), executor, RiskManager(db_settings), db_settings
        )

        assert await engine.enforce_stops("BTC/USD") is None
        executor.execute_market_order.assert_not_awaited()
        assert await stored_amount() == Decimal("1")

    async def test_costs_no_exchange_calls(self, db_settings: Settings) -> None:
        """Runs every cycle of every bot, so disabled must mean genuinely free."""
        await open_position()
        client = make_client(Decimal("50"))
        engine = TradingEngine(
            client, make_executor(), RiskManager(db_settings), db_settings
        )

        await engine.enforce_stops("BTC/USD")

        client.fetch_ticker.assert_not_awaited()
        client.fetch_open_orders.assert_not_awaited()

    async def test_the_ratchet_never_moves_a_stop(self, db_settings: Settings) -> None:
        await open_position(entry=Decimal("100"), stop=Decimal("98"))
        engine = TradingEngine(
            make_client(Decimal("150")), make_executor(), RiskManager(db_settings), db_settings
        )

        await engine.enforce_stops("BTC/USD")

        assert await stored_stop() == Decimal("98")
