"""Tests for the safeguards added before considering live trading.

Each covers a specific way the bot could have lost money quietly: paper results
that ignored fees, a drawdown limit silently disarmed by a restart, and no way
to stop new risk without killing a process that is managing an open position.
"""

from decimal import Decimal
from pathlib import Path
from unittest.mock import AsyncMock

import pytest

from src.bot.engine import TradingEngine
from src.bot.strategies.base import Signal
from src.config import Settings
from src.database.models import init_database
from src.database.repository import UnitOfWork
from src.exchange.executor import (
    Order,
    OrderSide,
    OrderStatus,
    OrderType,
    PaperTradingSimulator,
)
from src.risk.manager import RiskManager


@pytest.fixture(autouse=True)
async def _init_db(db_settings: Settings) -> None:
    await init_database()


def make_client(price: Decimal = Decimal("100")) -> AsyncMock:
    client = AsyncMock()
    client.fetch_ticker.return_value = {
        "last": float(price), "ask": float(price), "bid": float(price)
    }
    return client


class TestPaperFees:
    """Paper trading charged nothing until 2026-08-08, so every paper result
    flattered the strategy relative to live - and fee drag is what decided every
    backtest in this project."""

    async def test_buy_charges_the_fee_on_top_of_the_cost(self) -> None:
        sim = PaperTradingSimulator(make_client(Decimal("100")), fee_pct=Decimal("0.26"))
        sim.set_balance("USD", Decimal("10000"))

        order = await sim.execute_market_order("BTC/USD", OrderSide.BUY, Decimal("10"))

        assert order.status == OrderStatus.FILLED
        assert order.fee == Decimal("2.6")          # 1000 * 0.26%
        assert order.fee_currency == "USD"
        assert sim.get_balance("USD") == Decimal("8997.4")   # 10000 - 1000 - 2.6
        assert sim.get_balance("BTC") == Decimal("10")

    async def test_sell_deducts_the_fee_from_proceeds(self) -> None:
        sim = PaperTradingSimulator(make_client(Decimal("100")), fee_pct=Decimal("0.26"))
        sim.set_balance("USD", Decimal("0"))
        sim.set_balance("BTC", Decimal("10"))

        order = await sim.execute_market_order("BTC/USD", OrderSide.SELL, Decimal("10"))

        assert order.fee == Decimal("2.6")
        assert sim.get_balance("USD") == Decimal("997.4")    # 1000 - 2.6
        assert sim.get_balance("BTC") == Decimal("0")

    async def test_a_round_trip_at_a_flat_price_loses_money(self) -> None:
        """The point of modelling fees at all: flat price must not look free."""
        sim = PaperTradingSimulator(make_client(Decimal("100")), fee_pct=Decimal("0.26"))
        sim.set_balance("USD", Decimal("10000"))

        await sim.execute_market_order("BTC/USD", OrderSide.BUY, Decimal("10"))
        await sim.execute_market_order("BTC/USD", OrderSide.SELL, Decimal("10"))

        assert sim.get_balance("USD") < Decimal("10000")

    async def test_fee_is_included_in_the_affordability_check(self) -> None:
        """A buy that fits only by ignoring the fee must be rejected, not overdraw."""
        sim = PaperTradingSimulator(make_client(Decimal("100")), fee_pct=Decimal("0.26"))
        sim.set_balance("USD", Decimal("1000"))     # exactly the gross cost, no room for fee

        order = await sim.execute_market_order("BTC/USD", OrderSide.BUY, Decimal("10"))

        assert order.status == OrderStatus.FAILED
        assert sim.get_balance("USD") == Decimal("1000")

    async def test_zero_fee_reproduces_the_old_frictionless_behaviour(self) -> None:
        sim = PaperTradingSimulator(make_client(Decimal("100")), fee_pct=Decimal("0"))
        sim.set_balance("USD", Decimal("1000"))

        order = await sim.execute_market_order("BTC/USD", OrderSide.BUY, Decimal("10"))

        assert order.status == OrderStatus.FILLED
        assert order.fee == Decimal("0")
        assert sim.get_balance("USD") == Decimal("0")

    def test_negative_fee_is_rejected(self) -> None:
        with pytest.raises(ValueError, match="fee_pct cannot be negative"):
            PaperTradingSimulator(make_client(), fee_pct=Decimal("-1"))


class TestPeakEquityPersistence:
    """The drawdown limit measures decline from the account's best. Holding that
    in memory meant every restart reset it - disarming the limit precisely when
    a bot had just been restarted after trouble."""

    async def test_records_and_returns_the_mark(self, db_settings: Settings) -> None:
        async with UnitOfWork() as uow:
            assert await uow.peak_equity.record("BTC/USD", Decimal("10000")) == Decimal("10000")
            await uow.commit()
        async with UnitOfWork() as uow:
            assert await uow.peak_equity.get("BTC/USD") == Decimal("10000")

    async def test_raises_to_a_new_high(self, db_settings: Settings) -> None:
        async with UnitOfWork() as uow:
            await uow.peak_equity.record("BTC/USD", Decimal("10000"))
            assert await uow.peak_equity.record("BTC/USD", Decimal("12000")) == Decimal("12000")
            await uow.commit()

    async def test_never_lowers(self, db_settings: Settings) -> None:
        async with UnitOfWork() as uow:
            await uow.peak_equity.record("BTC/USD", Decimal("12000"))
            assert await uow.peak_equity.record("BTC/USD", Decimal("9000")) == Decimal("12000")
            await uow.commit()
        async with UnitOfWork() as uow:
            assert await uow.peak_equity.get("BTC/USD") == Decimal("12000")

    async def test_unknown_symbol_is_none(self, db_settings: Settings) -> None:
        async with UnitOfWork() as uow:
            assert await uow.peak_equity.get("NOPE/USD") is None

    async def test_survives_a_new_engine_instance(self, db_settings: Settings) -> None:
        """A fresh TradingEngine stands in for a process restart."""
        async with UnitOfWork() as uow:
            await uow.peak_equity.record("BTC/USD", Decimal("50000"))
            await uow.commit()

        client = make_client(Decimal("100"))
        executor = AsyncMock()
        executor.get_balance.return_value = Decimal("100")
        engine = TradingEngine(client, executor, RiskManager(db_settings), db_settings)

        # Equity is now far below the recorded peak, so the drawdown gate must bite.
        result = await engine.process_signal(
            Signal(symbol="BTC/USD", side=OrderSide.BUY, strategy="t", reason="t")
        )

        assert result.executed is False
        assert "drawdown" in (result.reason or "").lower()


class TestKillSwitch:
    async def test_blocks_new_entries_while_the_file_exists(
        self, db_settings: Settings, tmp_path: Path
    ) -> None:
        switch = tmp_path / "KILL_SWITCH"
        switch.touch()
        settings = db_settings.model_copy(update={"kill_switch_file": str(switch)})
        executor = AsyncMock()
        executor.get_balance.return_value = Decimal("10000")
        engine = TradingEngine(make_client(), executor, RiskManager(settings), settings)

        result = await engine.process_signal(
            Signal(symbol="BTC/USD", side=OrderSide.BUY, strategy="t", reason="t")
        )

        assert result.executed is False
        assert "Kill switch" in (result.reason or "")
        executor.execute_market_order.assert_not_awaited()

    async def test_never_blocks_an_exit(self, db_settings: Settings, tmp_path: Path) -> None:
        """A kill switch that trapped you in a position would be worse than none."""
        switch = tmp_path / "KILL_SWITCH"
        switch.touch()
        settings = db_settings.model_copy(update={"kill_switch_file": str(switch)})
        async with UnitOfWork() as uow:
            await uow.positions.create_or_update(
                symbol="BTC/USD", side="long", amount=Decimal("1"),
                entry_price=Decimal("100"), strategy="t", is_paper=True,
                stop_loss=None, take_profit=None,
            )
            await uow.commit()

        executor = AsyncMock()
        executor.get_balance.return_value = Decimal("1")
        executor.execute_market_order.return_value = Order(
            id="o1",
            symbol="BTC/USD",
            side=OrderSide.SELL,
            order_type=OrderType.MARKET,
            amount=Decimal("1"),
            price=None,
            status=OrderStatus.FILLED,
            filled_amount=Decimal("1"),
            average_fill_price=Decimal("100"),
            is_paper=True,
        )
        engine = TradingEngine(make_client(), executor, RiskManager(settings), settings)

        result = await engine.process_signal(
            Signal(symbol="BTC/USD", side=OrderSide.SELL, strategy="t", reason="t")
        )

        assert result.executed is True

    async def test_absent_file_allows_entries(
        self, db_settings: Settings, tmp_path: Path
    ) -> None:
        settings = db_settings.model_copy(
            update={"kill_switch_file": str(tmp_path / "nope")}
        )
        engine = TradingEngine(make_client(), AsyncMock(), RiskManager(settings), settings)
        assert engine._kill_switch_engaged() is False

    async def test_empty_path_disables_the_switch(self, db_settings: Settings) -> None:
        settings = db_settings.model_copy(update={"kill_switch_file": ""})
        engine = TradingEngine(make_client(), AsyncMock(), RiskManager(settings), settings)
        assert engine._kill_switch_engaged() is False


class TestAlertingNeverBreaksTrading:
    async def test_a_failing_alert_does_not_fail_the_trade(
        self, db_settings: Settings
    ) -> None:
        """A trade that executed must never be reported as failed because SMS broke."""
        executor = AsyncMock()
        executor.get_balance.return_value = Decimal("10000")
        executor.execute_market_order.return_value = Order(
            id="o1",
            symbol="BTC/USD",
            side=OrderSide.BUY,
            order_type=OrderType.MARKET,
            amount=Decimal("1"),
            price=None,
            status=OrderStatus.FILLED,
            filled_amount=Decimal("1"),
            average_fill_price=Decimal("100"),
            is_paper=True,
        )
        notifier = AsyncMock()
        notifier.send.side_effect = RuntimeError("provider exploded")
        engine = TradingEngine(
            make_client(), executor, RiskManager(db_settings), db_settings, notifier=notifier
        )

        result = await engine.process_signal(
            Signal(symbol="BTC/USD", side=OrderSide.BUY, strategy="t", reason="t")
        )

        assert result.executed is True
        notifier.send.assert_awaited_once()


class TestPeakEquitySerialisation:
    async def test_to_dict(self, db_settings: Settings) -> None:
        async with UnitOfWork() as uow:
            await uow.peak_equity.record("BTC/USD", Decimal("123.45"))
            await uow.commit()
        async with UnitOfWork() as uow:
            row = await uow.peak_equity.get("BTC/USD")
        assert row == Decimal("123.45")

        from src.database.models import PeakEquity

        d = PeakEquity(symbol="BTC/USD", peak_equity=Decimal("123.45"),
                       updated_at=__import__("datetime").datetime.now(
                           __import__("datetime").UTC)).to_dict()
        assert d["symbol"] == "BTC/USD"
        assert d["peak_equity"] == "123.45"
        assert "updated_at" in d
