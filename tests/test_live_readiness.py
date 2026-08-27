"""Tests for the safeguards added before considering live trading.

Each covers a specific way the bot could have lost money quietly: paper results
that ignored fees, a drawdown limit silently disarmed by a restart, and no way
to stop new risk without killing a process that is managing an open position.
"""

import sqlite3
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
    OrderExecutor,
    OrderSide,
    OrderStatus,
    OrderType,
    PaperTradingSimulator,
)
from src.portfolio_equity import record_and_get_portfolio_equity
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


class TestPortfolioEquityTracking:
    """The drawdown limit measures decline from the account's best. Two separate
    things used to break this: (1) holding it in memory meant every restart
    reset it - disarming the limit precisely when a bot had just been
    restarted after trouble; (2) persisting it *per symbol* (the original fix
    for (1)) meant each bot compared its own balance+position as if that were
    the whole account, when in reality every live bot here shares one Kraken
    account and one free-USD balance - a bot sitting flat would look like it
    had suffered a real drawdown the moment any *other* bot drew capital out
    of that shared balance into a new position. Two real live incidents
    (kraken-bot-state/RESTART.md, 2026-08-17 and 2026-08-27) before this
    module replaced the per-symbol table with one true cross-bot total."""

    async def test_records_and_returns_the_mark(self, tmp_path: Path) -> None:
        db = str(tmp_path / "portfolio.db")
        current, peak = record_and_get_portfolio_equity(
            db, "BTC/USD", Decimal("0"), Decimal("10000")
        )
        assert current == Decimal("10000")
        assert peak == Decimal("10000")

    async def test_raises_to_a_new_high(self, tmp_path: Path) -> None:
        db = str(tmp_path / "portfolio.db")
        record_and_get_portfolio_equity(db, "BTC/USD", Decimal("0"), Decimal("10000"))
        _, peak = record_and_get_portfolio_equity(db, "BTC/USD", Decimal("0"), Decimal("12000"))
        assert peak == Decimal("12000")

    async def test_never_lowers(self, tmp_path: Path) -> None:
        db = str(tmp_path / "portfolio.db")
        record_and_get_portfolio_equity(db, "BTC/USD", Decimal("0"), Decimal("12000"))
        _, peak = record_and_get_portfolio_equity(db, "BTC/USD", Decimal("0"), Decimal("9000"))
        assert peak == Decimal("12000")

    async def test_sums_every_bots_position_value_not_just_this_ones(
        self, tmp_path: Path
    ) -> None:
        """The actual bug, reproduced directly: a bot sitting flat (its own
        position_value is 0) must still see the true account total, not just
        its own empty slice of it - other bots' most-recently-recorded
        position values count too."""
        db = str(tmp_path / "portfolio.db")
        record_and_get_portfolio_equity(db, "ETH/USD", Decimal("50"), Decimal("300"))
        record_and_get_portfolio_equity(db, "SOL/USD", Decimal("20"), Decimal("300"))
        current, _ = record_and_get_portfolio_equity(db, "BTC/USD", Decimal("0"), Decimal("300"))
        # 300 shared free USD + ETH's 50 + SOL's 20 + BTC's own 0
        assert current == Decimal("370")

    async def test_survives_a_new_engine_instance(self, db_settings: Settings) -> None:
        """A fresh TradingEngine stands in for a process restart."""
        record_and_get_portfolio_equity(
            db_settings.portfolio_equity_db_path, "BTC/USD", Decimal("0"), Decimal("50000")
        )

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

    async def test_a_flat_bots_own_balance_no_longer_false_positives_a_drawdown(
        self, db_settings: Settings
    ) -> None:
        """End-to-end reproduction of the exact 2026-08-27 incident: BTC's peak
        was set while the account was "whole" (one bot, no capital drawn out
        yet); other bots then drew most of the free-USD balance into their own
        positions. Under the old per-symbol tracking, BTC's own balance+0
        looked like a >10% drawdown from that stale peak. With the shared
        total, the capital other bots hold is still counted, so it doesn't."""
        portfolio_db = db_settings.portfolio_equity_db_path
        # The peak, set once while "whole": 358 free USD, nothing deployed yet.
        record_and_get_portfolio_equity(portfolio_db, "BTC/USD", Decimal("0"), Decimal("358"))
        # Other bots then each drew capital out of that same shared balance
        # into their own positions - by the time BTC checks again, only ~300
        # of the original 358 is still free USD, the rest sits in ETH/SOL/DOGE.
        record_and_get_portfolio_equity(portfolio_db, "ETH/USD", Decimal("20"), Decimal("300"))
        record_and_get_portfolio_equity(portfolio_db, "SOL/USD", Decimal("18"), Decimal("300"))
        record_and_get_portfolio_equity(portfolio_db, "DOGE/USD", Decimal("15"), Decimal("300"))

        client = make_client(Decimal("100"))
        executor = AsyncMock()
        executor.get_balance.return_value = Decimal("300")  # the current shared free USD
        executor.execute_market_order.return_value = Order(
            id="order_1",
            symbol="BTC/USD",
            side=OrderSide.BUY,
            order_type=OrderType.MARKET,
            amount=Decimal("0.01"),
            price=None,
            status=OrderStatus.FILLED,
            filled_amount=Decimal("0.01"),
            average_fill_price=Decimal("100"),
            exchange_order_id="ex_1",
            is_paper=True,
        )
        engine = TradingEngine(client, executor, RiskManager(db_settings), db_settings)

        result = await engine.process_signal(
            Signal(symbol="BTC/USD", side=OrderSide.BUY, strategy="t", reason="t")
        )

        # 300 + 20 + 18 + 15 = 353, only ~1.4% off the 358 peak - well inside
        # the 10% default max_drawdown_pct, so the signal must proceed past
        # the drawdown gate (it may still not execute for other reasons, e.g.
        # sizing, but "drawdown" must not be why).
        assert "drawdown" not in (result.reason or "").lower()

    async def test_snapshot_refreshes_even_on_a_short_circuited_cycle(
        self, db_settings: Settings
    ) -> None:
        """A bot sitting "already holding" short-circuits process_signal on
        every cycle in between actual entries/exits - real for hours or days
        at this account's cadence. The snapshot write must not be gated
        behind that early return, or a long-held position's contribution to
        the shared total goes stale the same way the old per-symbol table
        did, just slower (caught locally: moving the write before the
        early-return gates is what actually fixed this, not just adding the
        shared file)."""
        async with UnitOfWork() as uow:
            await uow.positions.create_or_update(
                symbol="BTC/USD", side="long", amount=Decimal("2"), entry_price=Decimal("100")
            )
            await uow.commit()

        client = make_client(Decimal("150"))  # position now worth 2 * 150 = 300
        executor = AsyncMock()
        executor.get_balance.return_value = Decimal("50")
        engine = TradingEngine(client, executor, RiskManager(db_settings), db_settings)

        result = await engine.process_signal(
            Signal(symbol="BTC/USD", side=OrderSide.BUY, strategy="t", reason="t")
        )

        assert result.executed is False
        assert "Already holding" in (result.reason or "")

        conn = sqlite3.connect(db_settings.portfolio_equity_db_path)
        row = conn.execute(
            "SELECT position_value FROM bot_snapshots WHERE symbol = 'BTC/USD'"
        ).fetchone()
        conn.close()
        assert row is not None
        assert Decimal(row[0]) == Decimal("300")


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


class TestPaperBalancePersistence:
    """A restart must resume mid-position rather than reset.

    In-memory balances quietly broke restarts the moment a bot held something:
    the database still showed the position, but the simulator came back with
    starting cash and no base currency. process_signal clamps a sell to
    min(position.amount, executor balance), so the position became unsellable.
    """

    async def test_fresh_database_keeps_the_seeded_balance(
        self, db_settings: Settings
    ) -> None:
        """Nothing stored is a first run, not a lost one."""
        executor = OrderExecutor(make_client(), db_settings)
        assert await executor.restore_paper_state() is False
        assert await executor.get_balance("USD") == Decimal("10000")

    async def test_a_fill_is_persisted_immediately(self, db_settings: Settings) -> None:
        """Persisted per fill, not at shutdown - a killed bot never runs shutdown code."""
        settings = db_settings.model_copy(update={"paper_fee_pct": 0.26})
        executor = OrderExecutor(make_client(Decimal("100")), settings)
        await executor.execute_market_order("BTC/USD", OrderSide.BUY, Decimal("10"))

        async with UnitOfWork() as uow:
            stored = await uow.paper_balances.load_all()
        assert stored["BTC"] == Decimal("10")
        assert stored["USD"] == Decimal("8997.4")

    async def test_a_new_executor_resumes_the_position(self, db_settings: Settings) -> None:
        settings = db_settings.model_copy(update={"paper_fee_pct": 0.26})
        executor = OrderExecutor(make_client(Decimal("100")), settings)
        await executor.execute_market_order("BTC/USD", OrderSide.BUY, Decimal("10"))

        restarted = OrderExecutor(make_client(Decimal("100")), settings)
        assert await restarted.restore_paper_state() is True
        assert await restarted.get_balance("BTC") == Decimal("10")
        assert await restarted.get_balance("USD") == Decimal("8997.4")

    async def test_the_resumed_position_can_actually_be_sold(
        self, db_settings: Settings
    ) -> None:
        """The specific failure this fixes: a restart used to leave it unsellable."""
        settings = db_settings.model_copy(update={"paper_fee_pct": 0.0})
        executor = OrderExecutor(make_client(Decimal("100")), settings)
        await executor.execute_market_order("BTC/USD", OrderSide.BUY, Decimal("10"))

        restarted = OrderExecutor(make_client(Decimal("100")), settings)
        await restarted.restore_paper_state()
        order = await restarted.execute_market_order("BTC/USD", OrderSide.SELL, Decimal("10"))

        assert order.status == OrderStatus.FILLED
        assert await restarted.get_balance("BTC") == Decimal("0")

    async def test_an_asset_sold_to_zero_is_not_left_stale(
        self, db_settings: Settings
    ) -> None:
        settings = db_settings.model_copy(update={"paper_fee_pct": 0.0})
        executor = OrderExecutor(make_client(Decimal("100")), settings)
        await executor.execute_market_order("BTC/USD", OrderSide.BUY, Decimal("10"))
        await executor.execute_market_order("BTC/USD", OrderSide.SELL, Decimal("10"))

        async with UnitOfWork() as uow:
            stored = await uow.paper_balances.load_all()
        assert stored["BTC"] == Decimal("0")
        assert stored["USD"] == Decimal("10000")

    async def test_live_mode_does_not_restore(self, db_settings: Settings) -> None:
        """In live mode the exchange holds the real balances and is the source of truth."""
        from src.config import TradingMode

        settings = db_settings.model_copy(update={"trading_mode": TradingMode.LIVE})
        executor = OrderExecutor(make_client(), settings)
        assert await executor.restore_paper_state() is False

    async def test_paper_mode_restores_through_the_executor(
        self, db_settings: Settings
    ) -> None:
        async with UnitOfWork() as uow:
            await uow.paper_balances.save_all(
                {"USD": Decimal("1234.5"), "BTC": Decimal("2")}
            )
            await uow.commit()

        executor = OrderExecutor(make_client(), db_settings)
        assert await executor.restore_paper_state() is True
        assert await executor.get_balance("BTC") == Decimal("2")


class TestPaperBalanceEdges:
    async def test_a_currency_dropped_from_the_snapshot_is_zeroed(
        self, db_settings: Settings
    ) -> None:
        """Full overwrite, not a delta - a stale row would resurrect a sold asset."""
        async with UnitOfWork() as uow:
            await uow.paper_balances.save_all({"USD": Decimal("100"), "BTC": Decimal("5")})
            await uow.commit()
        async with UnitOfWork() as uow:
            await uow.paper_balances.save_all({"USD": Decimal("600")})
            await uow.commit()
        async with UnitOfWork() as uow:
            stored = await uow.paper_balances.load_all()
        assert stored["USD"] == Decimal("600")
        assert stored["BTC"] == Decimal("0")

    async def test_a_persistence_failure_does_not_fail_the_trade(
        self, db_settings: Settings, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Bookkeeping must never undo a fill that already happened."""
        import src.exchange.executor as executor_module

        executor = OrderExecutor(make_client(Decimal("100")), db_settings)

        class Boom:
            async def __aenter__(self) -> None:
                raise RuntimeError("db gone")

            async def __aexit__(self, *args: object) -> None:
                return None

        monkeypatch.setattr(executor_module, "UnitOfWork", Boom, raising=False)
        with monkeypatch.context() as m:
            m.setattr("src.database.repository.UnitOfWork", Boom)
            order = await executor.execute_market_order(
                "BTC/USD", OrderSide.BUY, Decimal("1")
            )
        assert order.status == OrderStatus.FILLED

    def test_paper_balance_to_dict(self) -> None:
        from datetime import UTC, datetime

        from src.database.models import PaperBalance

        d = PaperBalance(
            currency="USD", amount=Decimal("1.5"), updated_at=datetime.now(UTC)
        ).to_dict()
        assert d["currency"] == "USD"
        assert d["amount"] == "1.5"
        assert "updated_at" in d
