"""Tests for the strategy framework: base interface and the SMA crossover example."""

import dataclasses

import pandas as pd
import pytest

from src.bot.strategies.base import Signal, Strategy, ohlcv_to_dataframe
from src.bot.strategies.examples.moving_average_crossover import (
    MovingAverageCrossoverStrategy,
)
from src.exchange.executor import OrderSide


class TestSignal:
    """Tests for the Signal value object."""

    def test_defaults_confidence_to_one(self) -> None:
        signal = Signal(symbol="BTC/USD", side=OrderSide.BUY, strategy="test", reason="because")
        assert signal.confidence == 1.0

    def test_is_immutable(self) -> None:
        signal = Signal(symbol="BTC/USD", side=OrderSide.BUY, strategy="test", reason="because")
        with pytest.raises(dataclasses.FrozenInstanceError):
            signal.side = OrderSide.SELL  # type: ignore[misc]


class TestOhlcvToDataframe:
    """Tests for the raw-ccxt-rows -> DataFrame conversion helper."""

    def test_converts_columns_and_index(self) -> None:
        ohlcv = [
            [1700000000000, 10.0, 12.0, 9.0, 11.0, 100.0],
            [1700000060000, 11.0, 13.0, 10.0, 12.0, 150.0],
        ]
        df = ohlcv_to_dataframe(ohlcv)

        assert list(df.columns) == ["open", "high", "low", "close", "volume"]
        assert len(df) == 2
        assert isinstance(df.index, pd.DatetimeIndex)
        assert df.index.tz is not None
        assert df.iloc[0]["close"] == 11.0
        assert df.iloc[1]["volume"] == 150.0

    def test_empty_input_produces_empty_dataframe(self) -> None:
        df = ohlcv_to_dataframe([])
        assert len(df) == 0
        assert list(df.columns) == ["open", "high", "low", "close", "volume"]


class TestStrategyBaseClass:
    """Tests for the abstract Strategy base."""

    def test_cannot_instantiate_directly(self) -> None:
        with pytest.raises(TypeError):
            Strategy()  # type: ignore[abstract]

    def test_default_name_is_class_name(self) -> None:
        class NoopStrategy(Strategy):
            def generate_signal(self, symbol: str, candles: pd.DataFrame) -> Signal | None:
                return None

        assert NoopStrategy().name == "NoopStrategy"

    def test_explicit_name_overrides_default(self) -> None:
        class NoopStrategy(Strategy):
            def generate_signal(self, symbol: str, candles: pd.DataFrame) -> Signal | None:
                return None

        assert NoopStrategy(name="custom").name == "custom"


def make_candles(closes: list[float]) -> pd.DataFrame:
    """Build a minimal candles DataFrame with just the close column the strategy needs."""
    return pd.DataFrame({"close": closes})


class TestMovingAverageCrossoverStrategy:
    """Tests for the example SMA crossover strategy."""

    def test_rejects_fast_period_not_less_than_slow(self) -> None:
        with pytest.raises(ValueError, match="fast_period must be less than slow_period"):
            MovingAverageCrossoverStrategy(fast_period=10, slow_period=10)

    def test_default_name_encodes_periods(self) -> None:
        strategy = MovingAverageCrossoverStrategy(fast_period=10, slow_period=30)
        assert strategy.name == "sma_crossover_10_30"

    def test_returns_none_when_not_enough_candles(self) -> None:
        strategy = MovingAverageCrossoverStrategy(fast_period=2, slow_period=3)
        candles = make_candles([100, 100, 100])  # slow_period + 1 == 4 required

        assert strategy.generate_signal("BTC/USD", candles) is None

    def test_bullish_crossover_produces_buy_signal(self) -> None:
        strategy = MovingAverageCrossoverStrategy(fast_period=2, slow_period=3)
        candles = make_candles([100, 100, 90, 130])

        signal = strategy.generate_signal("BTC/USD", candles)

        assert signal is not None
        assert signal.symbol == "BTC/USD"
        assert signal.side == OrderSide.BUY
        assert signal.strategy == "sma_crossover_2_3"
        assert "crossed above" in signal.reason

    def test_bearish_crossover_produces_sell_signal(self) -> None:
        strategy = MovingAverageCrossoverStrategy(fast_period=2, slow_period=3)
        candles = make_candles([100, 100, 110, 85])

        signal = strategy.generate_signal("BTC/USD", candles)

        assert signal is not None
        assert signal.side == OrderSide.SELL
        assert "crossed below" in signal.reason

    def test_flat_prices_produce_no_signal(self) -> None:
        strategy = MovingAverageCrossoverStrategy(fast_period=2, slow_period=3)
        candles = make_candles([100, 100, 100, 100])

        assert strategy.generate_signal("BTC/USD", candles) is None
