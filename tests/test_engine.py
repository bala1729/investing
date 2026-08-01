"""Tests for TradingEngine: the risk-gated bridge from signal to order."""

import asyncio
from decimal import Decimal
from unittest.mock import AsyncMock

import pandas as pd
import pytest

from src.bot.engine import EngineResult, TradingEngine
from src.bot.strategies.base import Signal, Strategy
from src.config import Settings
from src.database.models import init_database
from src.database.repository import UnitOfWork
from src.exchange.executor import Order, OrderSide, OrderStatus, OrderType
from src.risk.manager import RiskManager


@pytest.fixture(autouse=True)
async def _init_db(db_settings: Settings) -> None:
    await init_database()


def make_order(
    order_id: str = "order_1",
    symbol: str = "BTC/USD",
    side: OrderSide = OrderSide.BUY,
    status: OrderStatus = OrderStatus.FILLED,
    filled_amount: Decimal = Decimal("0.1"),
    average_fill_price: Decimal | None = Decimal("100"),
) -> Order:
    return Order(
        id=order_id,
        symbol=symbol,
        side=side,
        order_type=OrderType.MARKET,
        amount=filled_amount,
        price=None,
        status=status,
        filled_amount=filled_amount,
        average_fill_price=average_fill_price,
        exchange_order_id="ex_1",
        is_paper=True,
    )


def make_client(last_price: Decimal = Decimal("100")) -> AsyncMock:
    client = AsyncMock()
    client.fetch_ticker.return_value = {"last": float(last_price)}
    return client


def make_executor(balance: Decimal = Decimal("10000")) -> AsyncMock:
    executor = AsyncMock()
    executor.get_balance.return_value = balance
    executor.execute_market_order.return_value = make_order()
    executor.execute_limit_order.return_value = make_order()
    return executor


def make_engine(
    client: AsyncMock,
    executor: AsyncMock,
    settings: Settings,
    risk_manager: RiskManager | None = None,
) -> TradingEngine:
    return TradingEngine(
        client, executor, risk_manager or RiskManager(settings), settings=settings
    )


def buy_signal(symbol: str = "BTC/USD") -> Signal:
    return Signal(symbol=symbol, side=OrderSide.BUY, strategy="test", reason="test")


def sell_signal(symbol: str = "BTC/USD") -> Signal:
    return Signal(symbol=symbol, side=OrderSide.SELL, strategy="test", reason="test")


class TestProcessSignalBuy:
    async def test_approved_buy_executes_and_persists(self, db_settings: Settings) -> None:
        client = make_client(last_price=Decimal("100"))
        executor = make_executor(balance=Decimal("10000"))
        engine = make_engine(client, executor, db_settings)

        result = await engine.process_signal(buy_signal())

        assert result.executed is True
        assert result.order is not None
        executor.execute_market_order.assert_awaited_once()
        call_args = executor.execute_market_order.await_args
        assert call_args.args[0] == "BTC/USD"
        assert call_args.args[1] == OrderSide.BUY
        assert call_args.args[2] == Decimal("10000") * Decimal("5") / 100 / Decimal("100")

        async with UnitOfWork() as uow:
            position = await uow.positions.get_by_symbol("BTC/USD")
            orders = await uow.orders.get_recent()
            trades = await uow.trades.get_recent()

        assert position is not None
        assert position.amount > 0
        assert position.stop_loss is not None
        assert position.take_profit is not None
        assert len(orders) == 1
        assert len(trades) == 1

    async def test_skipped_when_already_holding_a_position(self, db_settings: Settings) -> None:
        async with UnitOfWork() as uow:
            await uow.positions.create_or_update(
                symbol="BTC/USD", side="long", amount=Decimal("1"), entry_price=Decimal("90")
            )
            await uow.commit()

        client = make_client()
        executor = make_executor()
        engine = make_engine(client, executor, db_settings)

        result = await engine.process_signal(buy_signal())

        assert result.executed is False
        assert result.reason is not None
        assert "Already holding" in result.reason
        executor.execute_market_order.assert_not_called()

    async def test_allowed_again_after_position_was_closed(self, db_settings: Settings) -> None:
        # close_position() zeroes amount but leaves the row - a BUY must not
        # be blocked by a stale, already-closed position record.
        async with UnitOfWork() as uow:
            await uow.positions.create_or_update(
                symbol="BTC/USD", side="long", amount=Decimal("1"), entry_price=Decimal("90")
            )
            await uow.positions.close_position("BTC/USD", Decimal("95"))
            await uow.commit()

        client = make_client()
        executor = make_executor()
        engine = make_engine(client, executor, db_settings)

        result = await engine.process_signal(buy_signal())

        assert result.executed is True
        executor.execute_market_order.assert_awaited_once()

    async def test_rejected_when_exposure_limit_reached(self, db_settings: Settings) -> None:
        limited_settings = Settings(
            _env_file=None, database_url=db_settings.database_url, max_open_positions=1
        )
        async with UnitOfWork() as uow:
            await uow.positions.create_or_update(
                symbol="ETH/USD", side="long", amount=Decimal("1"), entry_price=Decimal("2000")
            )
            await uow.commit()

        client = make_client()
        executor = make_executor()
        engine = make_engine(client, executor, limited_settings)

        result = await engine.process_signal(buy_signal("BTC/USD"))

        assert result.executed is False
        assert result.reason is not None
        assert "positions" in result.reason.lower()
        executor.execute_market_order.assert_not_called()

    async def test_rejected_when_drawdown_breached_after_a_loss(
        self, db_settings: Settings
    ) -> None:
        risk_settings = Settings(
            _env_file=None, database_url=db_settings.database_url, max_drawdown_pct=10.0
        )
        client = make_client(last_price=Decimal("100"))
        executor = make_executor(balance=Decimal("10000"))
        engine = make_engine(client, executor, risk_settings)

        # Warm up the peak-equity high-water mark via an approved SELL against
        # an existing position (SELL is always approved regardless of risk).
        async with UnitOfWork() as uow:
            await uow.positions.create_or_update(
                symbol="BTC/USD", side="long", amount=Decimal("1"), entry_price=Decimal("90")
            )
            await uow.commit()
        executor.execute_market_order.return_value = make_order(
            side=OrderSide.SELL, filled_amount=Decimal("1")
        )
        warm_up = await engine.process_signal(sell_signal())
        assert warm_up.executed is True  # peak equity now ~10100 (balance 10000 + 1*100)

        # Now simulate a large balance drop and try to open a new position.
        executor.get_balance.return_value = Decimal("8000")
        executor.execute_market_order.return_value = make_order(side=OrderSide.BUY)

        result = await engine.process_signal(buy_signal())

        assert result.executed is False
        assert result.reason is not None
        assert "drawdown" in result.reason.lower()

    async def test_explicit_quantity_overrides_risk_sizing(self, db_settings: Settings) -> None:
        client = make_client()
        executor = make_executor()
        engine = make_engine(client, executor, db_settings)

        await engine.process_signal(buy_signal(), quantity=Decimal("0.05"))

        call_args = executor.execute_market_order.await_args
        assert call_args.args[2] == Decimal("0.05")

    async def test_limit_price_uses_limit_order_and_skips_ticker_fetch(
        self, db_settings: Settings
    ) -> None:
        client = make_client()
        executor = make_executor()
        engine = make_engine(client, executor, db_settings)

        await engine.process_signal(
            buy_signal(), quantity=Decimal("0.05"), limit_price=Decimal("95")
        )

        client.fetch_ticker.assert_not_called()
        executor.execute_limit_order.assert_awaited_once()
        executor.execute_market_order.assert_not_called()
        call_args = executor.execute_limit_order.await_args
        assert call_args.args[3] == Decimal("95")

    async def test_unfilled_order_does_not_create_trade_or_position(
        self, db_settings: Settings
    ) -> None:
        client = make_client()
        executor = make_executor()
        executor.execute_market_order.return_value = make_order(status=OrderStatus.OPEN)
        engine = make_engine(client, executor, db_settings)

        result = await engine.process_signal(buy_signal())

        assert result.executed is True
        async with UnitOfWork() as uow:
            trades = await uow.trades.get_recent()
            position = await uow.positions.get_by_symbol("BTC/USD")
        assert trades == []
        assert position is None

    async def test_zero_balance_yields_no_amount_to_trade(self, db_settings: Settings) -> None:
        client = make_client()
        executor = make_executor(balance=Decimal("0"))
        engine = make_engine(client, executor, db_settings)

        result = await engine.process_signal(buy_signal())

        assert result.executed is False
        assert result.reason == "No amount to trade"
        executor.execute_market_order.assert_not_called()


class TestProcessSignalSell:
    async def test_clamps_to_available_balance_when_position_amount_overstates_it(
        self, db_settings: Settings
    ) -> None:
        # Position.amount is DB-rounded (8dp) and can end up slightly larger than
        # what the executor's own ledger actually holds (seen live: a full-precision
        # risk-sized buy fill rounds up on read-back, and a naive sell of the DB
        # value then fails at the executor for "insufficient balance"). The engine
        # must clamp to the executor's real balance instead of trusting the DB value.
        db_amount = Decimal("0.00794419")
        actual_available = Decimal("0.007944187317581598720032539391")
        async with UnitOfWork() as uow:
            await uow.positions.create_or_update(
                symbol="BTC/USD", side="long", amount=db_amount, entry_price=Decimal("90")
            )
            await uow.commit()

        client = make_client()
        executor = make_executor()

        async def fake_get_balance(currency: str) -> Decimal:
            return actual_available if currency == "BTC" else Decimal("10000")

        executor.get_balance.side_effect = fake_get_balance
        engine = make_engine(client, executor, db_settings)

        result = await engine.process_signal(sell_signal())

        assert result.executed is True
        call_args = executor.execute_market_order.await_args
        assert call_args.args[2] == actual_available

    async def test_skipped_when_no_open_position(self, db_settings: Settings) -> None:
        client = make_client()
        executor = make_executor()
        engine = make_engine(client, executor, db_settings)

        result = await engine.process_signal(sell_signal())

        assert result.executed is False
        assert result.reason is not None
        assert "No open position" in result.reason
        executor.execute_market_order.assert_not_called()

    async def test_closes_position_and_ignores_risk_gate(self, db_settings: Settings) -> None:
        # Set an exposure limit that's already breached; a SELL must still go through.
        limited_settings = Settings(
            _env_file=None, database_url=db_settings.database_url, max_open_positions=1
        )
        async with UnitOfWork() as uow:
            await uow.positions.create_or_update(
                symbol="BTC/USD", side="long", amount=Decimal("1"), entry_price=Decimal("90")
            )
            await uow.positions.create_or_update(
                symbol="ETH/USD", side="long", amount=Decimal("1"), entry_price=Decimal("2000")
            )
            await uow.commit()

        client = make_client(last_price=Decimal("100"))
        executor = make_executor()
        executor.execute_market_order.return_value = make_order(
            side=OrderSide.SELL, filled_amount=Decimal("1"), average_fill_price=Decimal("100")
        )
        engine = make_engine(client, executor, limited_settings)

        result = await engine.process_signal(sell_signal())

        assert result.executed is True
        async with UnitOfWork() as uow:
            position = await uow.positions.get_by_symbol("BTC/USD")
        assert position is not None
        assert position.amount == Decimal("0")
        assert position.realized_pnl == Decimal("10")  # (100 - 90) * 1

    async def test_uses_full_position_amount_when_no_explicit_quantity(
        self, db_settings: Settings
    ) -> None:
        async with UnitOfWork() as uow:
            await uow.positions.create_or_update(
                symbol="BTC/USD", side="long", amount=Decimal("1.5"), entry_price=Decimal("90")
            )
            await uow.commit()

        client = make_client()
        executor = make_executor()
        engine = make_engine(client, executor, db_settings)

        await engine.process_signal(sell_signal())

        call_args = executor.execute_market_order.await_args
        assert call_args.args[2] == Decimal("1.5")

    async def test_explicit_quantity_overrides_full_position_amount(
        self, db_settings: Settings
    ) -> None:
        async with UnitOfWork() as uow:
            await uow.positions.create_or_update(
                symbol="BTC/USD", side="long", amount=Decimal("1.5"), entry_price=Decimal("90")
            )
            await uow.commit()

        client = make_client()
        executor = make_executor()
        engine = make_engine(client, executor, db_settings)

        await engine.process_signal(sell_signal(), quantity=Decimal("0.5"))

        call_args = executor.execute_market_order.await_args
        assert call_args.args[2] == Decimal("0.5")


class ScriptedStrategy(Strategy):
    def __init__(self, signal: Signal | None) -> None:
        super().__init__(name="scripted")
        self._signal = signal
        self.calls = 0

    def generate_signal(
        self,
        symbol: str,
        candles: pd.DataFrame,
        higher_tf_candles: dict[str, pd.DataFrame] | None = None,
    ) -> Signal | None:
        self.calls += 1
        return self._signal


class RecordingStrategy(Strategy):
    """Test double: records the candles DataFrame it was given, returns a fixed signal."""

    def __init__(self, signal: Signal | None) -> None:
        super().__init__(name="recording")
        self._signal = signal
        self.received_candles: pd.DataFrame | None = None
        self.received_higher_tf_candles: dict[str, pd.DataFrame] | None = None

    def generate_signal(
        self,
        symbol: str,
        candles: pd.DataFrame,
        higher_tf_candles: dict[str, pd.DataFrame] | None = None,
    ) -> Signal | None:
        self.received_candles = candles
        self.received_higher_tf_candles = higher_tf_candles
        return self._signal


class TestRunStrategyOnce:
    async def test_no_signal_produced(self, db_settings: Settings) -> None:
        client = make_client()
        client.fetch_ohlcv.return_value = [[1, 100, 100, 100, 100, 1]]
        executor = make_executor()
        engine = make_engine(client, executor, db_settings)
        strategy = ScriptedStrategy(None)

        result = await engine.run_strategy_once(strategy, "BTC/USD", timeframe="1w")

        assert result.executed is False
        assert result.reason is not None
        assert "no signal" in result.reason.lower()
        client.fetch_ohlcv.assert_awaited_once()
        executor.execute_market_order.assert_not_called()

    async def test_signal_is_routed_through_process_signal(self, db_settings: Settings) -> None:
        client = make_client()
        client.fetch_ohlcv.return_value = [[1, 100, 100, 100, 100, 1]]
        executor = make_executor()
        engine = make_engine(client, executor, db_settings)
        strategy = ScriptedStrategy(buy_signal())

        result = await engine.run_strategy_once(strategy, "BTC/USD")

        assert result.executed is True
        executor.execute_market_order.assert_awaited_once()

    async def test_drops_the_most_recent_possibly_incomplete_candle(
        self, db_settings: Settings
    ) -> None:
        client = make_client()
        client.fetch_ohlcv.return_value = [
            [1, 100.0, 100.0, 100.0, 100.0, 1.0],
            [2, 101.0, 101.0, 101.0, 101.0, 1.0],
            [3, 102.0, 102.0, 102.0, 102.0, 1.0],  # still forming - must be dropped
        ]
        executor = make_executor()
        engine = make_engine(client, executor, db_settings)
        strategy = RecordingStrategy(None)

        await engine.run_strategy_once(strategy, "BTC/USD", timeframe="1w", limit=2)

        client.fetch_ohlcv.assert_awaited_once_with("BTC/USD", timeframe="1w", limit=3)
        assert strategy.received_candles is not None
        assert len(strategy.received_candles) == 2
        assert strategy.received_candles.iloc[-1]["close"] == 101.0

    async def test_handles_empty_ohlcv_response(self, db_settings: Settings) -> None:
        client = make_client()
        client.fetch_ohlcv.return_value = []
        executor = make_executor()
        engine = make_engine(client, executor, db_settings)
        strategy = RecordingStrategy(None)

        result = await engine.run_strategy_once(strategy, "BTC/USD")

        assert result.executed is False
        assert strategy.received_candles is not None
        assert len(strategy.received_candles) == 0

    async def test_fetches_higher_timeframes_for_a_mapped_entry_timeframe(
        self, db_settings: Settings
    ) -> None:
        client = make_client()
        client.fetch_ohlcv.return_value = [
            [1, 100.0, 100.0, 100.0, 100.0, 1.0],
            [2, 101.0, 101.0, 101.0, 101.0, 1.0],
        ]
        executor = make_executor()
        engine = make_engine(client, executor, db_settings)
        strategy = RecordingStrategy(None)

        await engine.run_strategy_once(strategy, "BTC/USD", timeframe="1h", limit=1)

        assert client.fetch_ohlcv.await_count == 3
        called_timeframes = {
            call.kwargs["timeframe"] for call in client.fetch_ohlcv.await_args_list
        }
        assert called_timeframes == {"1h", "4h", "1d"}
        assert strategy.received_higher_tf_candles is not None
        assert set(strategy.received_higher_tf_candles) == {"4h", "1d"}

    async def test_does_not_fetch_higher_timeframes_for_an_unmapped_entry_timeframe(
        self, db_settings: Settings
    ) -> None:
        client = make_client()
        client.fetch_ohlcv.return_value = [
            [1, 100.0, 100.0, 100.0, 100.0, 1.0],
            [2, 101.0, 101.0, 101.0, 101.0, 1.0],
        ]
        executor = make_executor()
        engine = make_engine(client, executor, db_settings)
        strategy = RecordingStrategy(None)

        await engine.run_strategy_once(strategy, "BTC/USD", timeframe="1w", limit=1)

        client.fetch_ohlcv.assert_awaited_once()
        assert strategy.received_higher_tf_candles is None


class TestRunForever:
    async def test_polls_repeatedly_and_survives_exceptions(
        self, db_settings: Settings, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        client = make_client()
        executor = make_executor()
        engine = make_engine(client, executor, db_settings)
        strategy = ScriptedStrategy(None)

        call_count = 0

        async def fake_run_strategy_once(*args: object, **kwargs: object) -> EngineResult:
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                raise RuntimeError("transient failure")
            return EngineResult(executed=False, reason="no signal")

        monkeypatch.setattr(engine, "run_strategy_once", fake_run_strategy_once)

        # poll_interval_seconds=0 - a real asyncio.sleep(0) yields control back
        # to the loop without actually waiting, so no need to mock sleep itself.
        task = asyncio.create_task(engine.run_forever(strategy, "BTC/USD", poll_interval_seconds=0))
        for _ in range(1000):
            if call_count >= 3:
                break
            await asyncio.sleep(0)

        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task

        assert call_count >= 3  # survived the first exception and kept polling
