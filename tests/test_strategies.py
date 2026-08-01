"""Tests for the strategy framework: base interface and the SMA/EMA crossover examples."""

import dataclasses

import pandas as pd
import pandas_ta as ta
import pytest

from src.bot.strategies.base import Signal, Strategy, detect_crossover, ohlcv_to_dataframe
from src.bot.strategies.examples.ema_crossover import EMACrossoverStrategy
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


class TestDetectCrossover:
    """Tests for the shared crossover-detection helper used by both example strategies."""

    def test_bullish_cross(self) -> None:
        fast = pd.Series([95.0, 110.0])
        slow = pd.Series([96.667, 106.667])
        assert detect_crossover(fast, slow) == OrderSide.BUY

    def test_bearish_cross(self) -> None:
        fast = pd.Series([105.0, 97.5])
        slow = pd.Series([103.333, 98.333])
        assert detect_crossover(fast, slow) == OrderSide.SELL

    def test_no_cross_when_fast_stays_above(self) -> None:
        fast = pd.Series([110.0, 115.0])
        slow = pd.Series([100.0, 101.0])
        assert detect_crossover(fast, slow) is None

    def test_no_cross_when_fast_stays_below(self) -> None:
        fast = pd.Series([90.0, 85.0])
        slow = pd.Series([100.0, 101.0])
        assert detect_crossover(fast, slow) is None

    def test_touching_without_crossing_is_not_a_cross(self) -> None:
        # fast reaches slow exactly but doesn't move past it - no BUY, no SELL
        fast = pd.Series([90.0, 100.0])
        slow = pd.Series([100.0, 100.0])
        assert detect_crossover(fast, slow) is None

    def test_insufficient_data_returns_none(self) -> None:
        assert detect_crossover(pd.Series([100.0]), pd.Series([100.0])) is None
        assert detect_crossover(pd.Series([]), pd.Series([])) is None

    def test_nan_values_return_none(self) -> None:
        fast = pd.Series([float("nan"), 110.0])
        slow = pd.Series([96.667, 106.667])
        assert detect_crossover(fast, slow) is None


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


class TestEMACrossoverStrategy:
    """Tests for the example EMA crossover strategy.

    Unlike the hand-verified SMA tests, these check EMACrossoverStrategy's
    *integration* with pandas_ta (right indicator, right periods, right
    min-length gate, right Signal side/reason) by comparing against an EMA
    computed directly via the same trusted ta.ema() call within the test —
    not against hand-derived numbers, since EMA's recursive smoothing makes
    that impractical to verify by hand the way a plain SMA can be.
    """

    def test_rejects_fast_period_not_less_than_slow(self) -> None:
        with pytest.raises(ValueError, match="fast_period must be less than slow_period"):
            EMACrossoverStrategy(fast_period=10, slow_period=10)

    def test_default_name_encodes_periods(self) -> None:
        strategy = EMACrossoverStrategy(fast_period=10, slow_period=30)
        assert strategy.name == "ema_crossover_10_30"

    def test_returns_none_when_not_enough_candles(self) -> None:
        strategy = EMACrossoverStrategy(fast_period=5, slow_period=10)
        candles = make_candles([100.0] * 10)  # slow_period + 1 == 11 required

        assert strategy.generate_signal("BTC/USD", candles) is None

    def test_bullish_crossover_matches_reference_ema(self) -> None:
        closes = [
            100.0, 98.0, 96.0, 94.0, 92.0, 90.0, 88.0, 86.0, 84.0, 82.0, 80.0, 90.0,
            100.0, 110.0,
        ]
        candles = make_candles(closes)
        strategy = EMACrossoverStrategy(fast_period=5, slow_period=10)

        close_series = pd.Series(closes, dtype=float)
        reference_fast = ta.ema(close_series, length=5)
        reference_slow = ta.ema(close_series, length=10)
        assert detect_crossover(reference_fast, reference_slow) == OrderSide.BUY

        signal = strategy.generate_signal("BTC/USD", candles)

        assert signal is not None
        assert signal.side == OrderSide.BUY
        assert signal.strategy == "ema_crossover_5_10"
        assert "crossed above" in signal.reason
        assert f"{reference_fast.iloc[-1]:.2f}" in signal.reason
        assert f"{reference_slow.iloc[-1]:.2f}" in signal.reason

    def test_bearish_crossover_matches_reference_ema(self) -> None:
        closes = [
            100.0, 102.0, 104.0, 106.0, 108.0, 110.0, 112.0, 114.0, 116.0, 118.0, 120.0,
            110.0, 100.0, 90.0,
        ]
        candles = make_candles(closes)
        strategy = EMACrossoverStrategy(fast_period=5, slow_period=10)

        close_series = pd.Series(closes, dtype=float)
        reference_fast = ta.ema(close_series, length=5)
        reference_slow = ta.ema(close_series, length=10)
        assert detect_crossover(reference_fast, reference_slow) == OrderSide.SELL

        signal = strategy.generate_signal("BTC/USD", candles)

        assert signal is not None
        assert signal.side == OrderSide.SELL
        assert "crossed below" in signal.reason

    def test_flat_prices_produce_no_signal(self) -> None:
        strategy = EMACrossoverStrategy(fast_period=5, slow_period=10)
        candles = make_candles([100.0] * 11)

        assert strategy.generate_signal("BTC/USD", candles) is None

    def test_uses_ema_not_sma(self) -> None:
        """Guard against EMACrossoverStrategy secretly computing an SMA.

        A regression here (e.g. someone copy-pasting the SMA strategy and
        forgetting to change ta.sma -> ta.ema) would report SMA's numbers
        under an EMA label instead of failing loudly, so assert against the
        actual reference EMA value, which is numerically distinct from SMA's
        on this trending data.
        """
        closes = [
            100.0, 98.0, 96.0, 94.0, 92.0, 90.0, 88.0, 86.0, 84.0, 82.0, 80.0, 90.0,
            100.0, 110.0,
        ]
        candles = make_candles(closes)
        close_series = pd.Series(closes, dtype=float)

        reference_ema_fast = ta.ema(close_series, length=5).iloc[-1]
        reference_sma_fast = ta.sma(close_series, length=5).iloc[-1]
        assert reference_ema_fast != reference_sma_fast  # sanity: the two actually differ here

        signal = EMACrossoverStrategy(fast_period=5, slow_period=10).generate_signal(
            "BTC/USD", candles
        )

        assert signal is not None
        assert "EMA" in signal.reason
        assert f"{reference_ema_fast:.2f}" in signal.reason
        assert f"{reference_sma_fast:.2f}" not in signal.reason
