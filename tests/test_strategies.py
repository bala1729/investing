"""Tests for the strategy framework: base interface and the example strategies."""

import dataclasses

import pandas as pd
import pandas_ta as ta
import pytest

from src.bot.strategies.base import (
    Signal,
    Strategy,
    detect_crossover,
    first_column_starting_with,
    mtf_trend_confirms_buy,
    ohlcv_to_dataframe,
    trend_is_bullish,
)
from src.bot.strategies.examples.ema_crossover import EMACrossoverStrategy
from src.bot.strategies.examples.heikin_ashi_confluence import (
    HeikinAshiConfluenceStrategy,
    _confirms_buy,
)
from src.bot.strategies.examples.macd_crossover import MACDCrossoverStrategy
from src.bot.strategies.examples.moving_average_crossover import (
    MovingAverageCrossoverStrategy,
)
from src.bot.strategies.examples.rsi_crossover import (
    RSICrossoverStrategy,
    mtf_rsi_confirms_buy,
    rsi_and_signal_line,
    rsi_slope_is_positive,
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
            def generate_signal(
                self,
                symbol: str,
                candles: pd.DataFrame,
                higher_tf_candles: dict[str, pd.DataFrame] | None = None,
            ) -> Signal | None:
                return None

        assert NoopStrategy().name == "NoopStrategy"

    def test_explicit_name_overrides_default(self) -> None:
        class NoopStrategy(Strategy):
            def generate_signal(
                self,
                symbol: str,
                candles: pd.DataFrame,
                higher_tf_candles: dict[str, pd.DataFrame] | None = None,
            ) -> Signal | None:
                return None

        assert NoopStrategy(name="custom").name == "custom"


def make_candles(closes: list[float]) -> pd.DataFrame:
    """Build a minimal candles DataFrame with just the close column the strategy needs."""
    return pd.DataFrame({"close": closes})


class TestTrendIsBullish:
    """Tests for the state-based trend check that entries key off."""

    def test_true_when_fast_is_above_slow(self) -> None:
        assert trend_is_bullish(pd.Series([1.0, 110.0]), pd.Series([1.0, 100.0])) is True

    def test_false_when_fast_is_below_slow(self) -> None:
        assert trend_is_bullish(pd.Series([1.0, 90.0]), pd.Series([1.0, 100.0])) is False

    def test_false_on_exactly_equal_values(self) -> None:
        assert trend_is_bullish(pd.Series([100.0]), pd.Series([100.0])) is False

    def test_false_when_difference_is_only_floating_point_noise(self) -> None:
        """A rounding artifact must not read as an uptrend.

        pandas_ta computes SMA(3) of a constant 100.0 as 99.99999999999999, so a
        bare `>` reports a dead-flat market as bullish by 1.4e-14. Guarded
        because a state check - unlike a crossover, where the same artifact
        appears on both compared bars and cancels - has nothing to cancel it.
        """
        assert trend_is_bullish(pd.Series([100.0]), pd.Series([100.0 - 1.5e-14])) is False

    def test_true_for_a_real_but_small_price_difference(self) -> None:
        # a hundredth of a percent is far above float noise and must still count
        assert trend_is_bullish(pd.Series([100.01]), pd.Series([100.0])) is True

    def test_false_during_indicator_warmup(self) -> None:
        assert trend_is_bullish(pd.Series([float("nan")]), pd.Series([100.0])) is False
        assert trend_is_bullish(pd.Series([100.0]), pd.Series([float("nan")])) is False

    def test_false_on_empty_series(self) -> None:
        assert trend_is_bullish(pd.Series([], dtype=float), pd.Series([], dtype=float)) is False


class TestStateBasedEntryRecoversMissedTrends:
    """The behaviour this whole state-based-entry design exists to provide.

    With a cross-only entry, a bullish crossover that happens while a filter is
    vetoing is discarded permanently - the lines never cross again on the way
    up, so the entire trend is forfeited. Real case from the sweep: BTC/USD 1d
    in 2023 produced five BUY crossovers before the weekly trend turned bullish,
    and the strategy sat out a +156% year.
    """

    def test_buy_fires_after_confirmation_arrives_late(self) -> None:
        # Prices rise steadily: the EMA cross happens early in the series, well
        # before the bar we evaluate.
        rising = make_candles([100.0 + i * 2.0 for i in range(40)])
        strategy = EMACrossoverStrategy(fast_period=5, slow_period=10)

        # Sanity: by the final bar the cross is long past, so a cross-only
        # entry would have nothing left to trigger on.
        fast = ta.ema(rising["close"], length=5)
        slow = ta.ema(rising["close"], length=10)
        assert detect_crossover(fast, slow) is None
        assert trend_is_bullish(fast, slow) is True

        # Confirmation only becomes available now - the entry must still happen.
        uptrend = make_candles([90.0 + i * 2.0 for i in range(11)])
        signal = strategy.generate_signal("BTC/USD", rising, {"4h": uptrend, "1d": uptrend})

        assert signal is not None
        assert signal.side == OrderSide.BUY

    def test_entry_stays_blocked_while_confirmation_is_absent(self) -> None:
        rising = make_candles([100.0 + i * 2.0 for i in range(40)])
        strategy = EMACrossoverStrategy(fast_period=5, slow_period=10)
        downtrend = make_candles([110.0 - i * 2.0 for i in range(11)])

        assert strategy.generate_signal("BTC/USD", rising, {"4h": downtrend}) is None

    def test_buy_repeats_on_every_bullish_bar(self) -> None:
        """Callers dedupe; the strategy just reports the current state."""
        rising = make_candles([100.0 + i * 2.0 for i in range(40)])
        strategy = EMACrossoverStrategy(fast_period=5, slow_period=10)

        for end in range(30, 40):
            signal = strategy.generate_signal("BTC/USD", rising.iloc[:end])
            assert signal is not None
            assert signal.side == OrderSide.BUY


class TestRSIExitMargin:
    """Tests for the configurable minimum gap the exit cross must clear.

    Motivated by live behaviour: on 2026-08-05 the bot took two full round trips
    inside a ~1% price range because the 4h RSI dipped 0.10 and then 0.47 points
    below its SMA. The unfiltered cross treats a tenth of a point exactly like a
    collapse.
    """

    def test_defaults_to_zero_and_keeps_the_plain_cross(self) -> None:
        """Zero margin must reproduce the original behaviour exactly."""
        strategy = RSICrossoverStrategy(rsi_period=5, ma_period=3)
        assert strategy._exit_margin == 0.0
        signal = strategy.generate_signal("BTC/USD", make_candles(reversal_closes()))
        assert signal is not None
        assert signal.side == OrderSide.SELL
        assert "crossed below" in signal.reason

    def test_rejects_a_negative_margin(self) -> None:
        with pytest.raises(ValueError, match="exit_margin cannot be negative"):
            RSICrossoverStrategy(exit_margin=-0.1)

    def test_name_encodes_a_non_zero_margin(self) -> None:
        assert RSICrossoverStrategy().name == "rsi_crossover_14_14"
        assert RSICrossoverStrategy(exit_margin=1.5).name == "rsi_crossover_14_14_m1.5"

    def test_a_shallow_dip_does_not_trigger_the_exit(self) -> None:
        closes = reversal_closes()
        strategy = RSICrossoverStrategy(rsi_period=5, ma_period=3)
        rsi, sma = rsi_lines(closes, 5, 3)
        gap = sma.iloc[-1] - rsi.iloc[-1]
        assert gap > 0  # sanity: it is below, so margin 0 would sell

        # A margin wider than the actual dip must hold the position.
        wide = RSICrossoverStrategy(rsi_period=5, ma_period=3, exit_margin=float(gap) + 1)
        assert wide.generate_signal("BTC/USD", make_candles(closes)) is None
        # ...while the unmargined strategy sells on the same bar.
        assert strategy.generate_signal("BTC/USD", make_candles(closes)) is not None

    def test_a_deep_dip_still_triggers_the_exit(self) -> None:
        closes = reversal_closes()
        rsi, sma = rsi_lines(closes, 5, 3)
        gap = sma.iloc[-1] - rsi.iloc[-1]

        narrow = RSICrossoverStrategy(rsi_period=5, ma_period=3, exit_margin=float(gap) / 2)
        signal = narrow.generate_signal("BTC/USD", make_candles(closes))

        assert signal is not None
        assert signal.side == OrderSide.SELL
        assert "below its" in signal.reason

    def test_margined_exit_survives_a_bar_that_is_not_a_fresh_cross(self) -> None:
        """The reason the margined exit is a state check rather than a cross.

        A margined *cross* would be unreachable: once RSI slips below by too
        little to act on, detect_crossover() reports nothing on every later bar
        because the previous bar was already below, and the exit stays disarmed
        all the way down.
        """
        closes = falling_closes()
        rsi, sma = rsi_lines(closes, 5, 3)
        assert detect_crossover(rsi, sma) is None  # long since below, no fresh cross
        assert sma.iloc[-1] - rsi.iloc[-1] > 0

        strategy = RSICrossoverStrategy(rsi_period=5, ma_period=3, exit_margin=0.5)
        signal = strategy.generate_signal("BTC/USD", make_candles(closes))

        assert signal is not None
        assert signal.side == OrderSide.SELL

    def test_margin_does_not_block_entries(self) -> None:
        """The margin governs exits only; a bullish state still buys."""
        strategy = RSICrossoverStrategy(rsi_period=5, ma_period=3, exit_margin=5.0)
        signal = strategy.generate_signal("BTC/USD", make_candles(rising_closes()))
        assert signal is not None
        assert signal.side == OrderSide.BUY

    def test_returns_no_signal_during_warmup(self) -> None:
        strategy = RSICrossoverStrategy(rsi_period=5, ma_period=3, exit_margin=1.0)
        assert strategy.generate_signal("BTC/USD", make_candles([100.0] * 8)) is None

    def test_nan_indicator_values_do_not_trigger_an_exit(self) -> None:
        strategy = RSICrossoverStrategy(rsi_period=5, ma_period=3, exit_margin=1.0)
        nan_series = pd.Series([float("nan")] * 4)
        assert strategy._exit_is_triggered(nan_series, nan_series) is False

    def test_empty_series_do_not_trigger_an_exit(self) -> None:
        strategy = RSICrossoverStrategy(rsi_period=5, ma_period=3, exit_margin=1.0)
        empty = pd.Series([], dtype=float)
        assert strategy._exit_is_triggered(empty, empty) is False


class TestMtfTrendConfirmsBuy:
    """Tests for the shared multi-timeframe entry-confirmation helper."""

    def test_confirms_when_all_timeframes_trend_up(self) -> None:
        uptrend = make_candles([100.0, 105.0, 110.0, 120.0])
        higher_tf_candles = {"1h": uptrend, "15m": uptrend}

        assert (
            mtf_trend_confirms_buy(higher_tf_candles, fast_period=2, slow_period=3, use_ema=False)
            is True
        )

    def test_rejects_when_any_timeframe_trends_down(self) -> None:
        uptrend = make_candles([100.0, 105.0, 110.0, 120.0])
        downtrend = make_candles([120.0, 110.0, 105.0, 100.0])
        higher_tf_candles = {"1h": uptrend, "15m": downtrend}

        assert (
            mtf_trend_confirms_buy(higher_tf_candles, fast_period=2, slow_period=3, use_ema=False)
            is False
        )

    def test_rejects_when_not_enough_candles(self) -> None:
        short = make_candles([100.0, 105.0, 110.0])  # slow_period + 1 == 4 required
        higher_tf_candles = {"1h": short}

        assert (
            mtf_trend_confirms_buy(higher_tf_candles, fast_period=2, slow_period=3, use_ema=False)
            is False
        )

    def test_rejects_when_close_prices_contain_nan(self) -> None:
        candles = make_candles([100.0, 101.0, 102.0, float("nan")])
        higher_tf_candles = {"1h": candles}

        assert (
            mtf_trend_confirms_buy(higher_tf_candles, fast_period=2, slow_period=3, use_ema=False)
            is False
        )

    def test_empty_dict_is_vacuously_confirmed(self) -> None:
        assert mtf_trend_confirms_buy({}, fast_period=2, slow_period=3, use_ema=False) is True

    def test_use_ema_flag_selects_ema_not_sma(self) -> None:
        closes = [
            100.0, 101.39, 102.48, 99.01, 101.63, 102.03, 104.81, 105.12, 100.12,
            98.36, 93.56, 97.85, 101.64, 104.95,
        ]
        candles = make_candles(closes)
        close_series = pd.Series(closes, dtype=float)

        reference_ema_fast = ta.ema(close_series, length=5).iloc[-1]
        reference_ema_slow = ta.ema(close_series, length=10).iloc[-1]
        reference_sma_fast = ta.sma(close_series, length=5).iloc[-1]
        reference_sma_slow = ta.sma(close_series, length=10).iloc[-1]
        # sanity: EMA and SMA actually disagree on direction here, so use_ema matters
        assert (reference_ema_fast > reference_ema_slow) != (
            reference_sma_fast > reference_sma_slow
        )

        ema_result = mtf_trend_confirms_buy(
            {"1h": candles}, fast_period=5, slow_period=10, use_ema=True
        )
        sma_result = mtf_trend_confirms_buy(
            {"1h": candles}, fast_period=5, slow_period=10, use_ema=False
        )

        assert ema_result != sma_result


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
        assert "is above" in signal.reason

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

    def test_mtf_confirmation_suppresses_buy_when_higher_tf_not_aligned(self) -> None:
        strategy = MovingAverageCrossoverStrategy(fast_period=2, slow_period=3)
        candles = make_candles([100, 100, 90, 130])
        downtrend = make_candles([120.0, 110.0, 105.0, 100.0])

        signal = strategy.generate_signal("BTC/USD", candles, {"1h": downtrend})

        assert signal is None

    def test_mtf_confirmation_allows_buy_when_all_higher_tf_aligned(self) -> None:
        strategy = MovingAverageCrossoverStrategy(fast_period=2, slow_period=3)
        candles = make_candles([100, 100, 90, 130])
        uptrend = make_candles([100.0, 105.0, 110.0, 120.0])

        signal = strategy.generate_signal("BTC/USD", candles, {"1h": uptrend, "15m": uptrend})

        assert signal is not None
        assert signal.side == OrderSide.BUY

    def test_mtf_confirmation_does_not_affect_sell_signal(self) -> None:
        strategy = MovingAverageCrossoverStrategy(fast_period=2, slow_period=3)
        candles = make_candles([100, 100, 110, 85])
        downtrend = make_candles([120.0, 110.0, 105.0, 100.0])  # would veto a BUY

        signal = strategy.generate_signal("BTC/USD", candles, {"1h": downtrend})

        assert signal is not None
        assert signal.side == OrderSide.SELL

    def test_no_higher_tf_candles_matches_single_timeframe_behavior(self) -> None:
        strategy = MovingAverageCrossoverStrategy(fast_period=2, slow_period=3)
        candles = make_candles([100, 100, 90, 130])

        signal = strategy.generate_signal("BTC/USD", candles, None)

        assert signal is not None
        assert signal.side == OrderSide.BUY


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
        assert "is above" in signal.reason
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

    def test_mtf_confirmation_suppresses_buy_when_higher_tf_not_aligned(self) -> None:
        closes = [
            100.0, 98.0, 96.0, 94.0, 92.0, 90.0, 88.0, 86.0, 84.0, 82.0, 80.0, 90.0,
            100.0, 110.0,
        ]
        candles = make_candles(closes)
        strategy = EMACrossoverStrategy(fast_period=5, slow_period=10)
        downtrend = make_candles(
            [110.0, 108.0, 106.0, 104.0, 102.0, 100.0, 98.0, 96.0, 94.0, 92.0, 90.0]
        )

        signal = strategy.generate_signal("BTC/USD", candles, {"1h": downtrend})

        assert signal is None

    def test_mtf_confirmation_allows_buy_when_all_higher_tf_aligned(self) -> None:
        closes = [
            100.0, 98.0, 96.0, 94.0, 92.0, 90.0, 88.0, 86.0, 84.0, 82.0, 80.0, 90.0,
            100.0, 110.0,
        ]
        candles = make_candles(closes)
        strategy = EMACrossoverStrategy(fast_period=5, slow_period=10)
        uptrend = make_candles(
            [90.0, 92.0, 94.0, 96.0, 98.0, 100.0, 102.0, 104.0, 106.0, 108.0, 110.0]
        )

        signal = strategy.generate_signal("BTC/USD", candles, {"1h": uptrend, "15m": uptrend})

        assert signal is not None
        assert signal.side == OrderSide.BUY

    def test_mtf_confirmation_does_not_affect_sell_signal(self) -> None:
        closes = [
            100.0, 102.0, 104.0, 106.0, 108.0, 110.0, 112.0, 114.0, 116.0, 118.0, 120.0,
            110.0, 100.0, 90.0,
        ]
        candles = make_candles(closes)
        strategy = EMACrossoverStrategy(fast_period=5, slow_period=10)
        downtrend = make_candles(
            [110.0, 108.0, 106.0, 104.0, 102.0, 100.0, 98.0, 96.0, 94.0, 92.0, 90.0]
        )

        signal = strategy.generate_signal("BTC/USD", candles, {"1h": downtrend})

        assert signal is not None
        assert signal.side == OrderSide.SELL


def make_ohlc_candles(closes: list[float]) -> pd.DataFrame:
    """Build a flat (no-wick) OHLC candles DataFrame, for strategies that need the
    full open/high/low/close set (e.g. for a Heikin Ashi transform), not just close.
    """
    return pd.DataFrame({"open": closes, "high": closes, "low": closes, "close": closes})


class TestConfirmsBuy:
    """Tests for the pure MACD/RSI/Bollinger-Bands confirmation check.

    Tested directly with scalar inputs rather than via generate_signal(),
    since these indicators are naturally correlated in real price data (e.g.
    RSI overbought and price-above-upper-band tend to co-occur) - hand-crafted
    market data that trips exactly one filter at a time isn't practical to
    construct, but the pure function is trivial to test in isolation.
    """

    def test_all_conditions_pass(self) -> None:
        assert (
            _confirms_buy(
                macd_line=1.0,
                macd_signal=0.5,
                rsi=50.0,
                rsi_overbought=70.0,
                close=100.0,
                bb_upper=105.0,
            )
            is True
        )

    def test_rejects_when_macd_not_bullish(self) -> None:
        assert (
            _confirms_buy(
                macd_line=0.5,
                macd_signal=1.0,
                rsi=50.0,
                rsi_overbought=70.0,
                close=100.0,
                bb_upper=105.0,
            )
            is False
        )

    def test_rejects_when_macd_equal(self) -> None:
        assert (
            _confirms_buy(
                macd_line=1.0,
                macd_signal=1.0,
                rsi=50.0,
                rsi_overbought=70.0,
                close=100.0,
                bb_upper=105.0,
            )
            is False
        )

    def test_rejects_when_rsi_overbought(self) -> None:
        assert (
            _confirms_buy(
                macd_line=1.0,
                macd_signal=0.5,
                rsi=75.0,
                rsi_overbought=70.0,
                close=100.0,
                bb_upper=105.0,
            )
            is False
        )

    def test_rejects_when_rsi_at_overbought_boundary(self) -> None:
        assert (
            _confirms_buy(
                macd_line=1.0,
                macd_signal=0.5,
                rsi=70.0,
                rsi_overbought=70.0,
                close=100.0,
                bb_upper=105.0,
            )
            is False
        )

    def test_rejects_when_price_at_or_above_upper_band(self) -> None:
        assert (
            _confirms_buy(
                macd_line=1.0,
                macd_signal=0.5,
                rsi=50.0,
                rsi_overbought=70.0,
                close=105.0,
                bb_upper=105.0,
            )
            is False
        )


class TestHeikinAshiConfluenceStrategy:
    """Tests for the example multi-indicator confluence strategy."""

    def test_rejects_fast_period_not_less_than_slow(self) -> None:
        with pytest.raises(ValueError, match="fast_period must be less than slow_period"):
            HeikinAshiConfluenceStrategy(fast_period=10, slow_period=10)

    def test_rejects_macd_fast_not_less_than_macd_slow(self) -> None:
        with pytest.raises(ValueError, match="macd_fast must be less than macd_slow"):
            HeikinAshiConfluenceStrategy(macd_fast=26, macd_slow=26)

    def test_rejects_rsi_overbought_out_of_range(self) -> None:
        with pytest.raises(ValueError, match="rsi_overbought"):
            HeikinAshiConfluenceStrategy(rsi_overbought=0)
        with pytest.raises(ValueError, match="rsi_overbought"):
            HeikinAshiConfluenceStrategy(rsi_overbought=101)

    def test_default_name_encodes_ema_periods(self) -> None:
        strategy = HeikinAshiConfluenceStrategy(fast_period=5, slow_period=10)
        assert strategy.name == "ha_confluence_5_10"

    def test_returns_none_when_not_enough_candles(self) -> None:
        strategy = HeikinAshiConfluenceStrategy()
        candles = make_ohlc_candles([100.0] * 35)  # one short of the 36-candle minimum
        assert strategy.generate_signal("BTC/USD", candles) is None

    def test_bullish_crossover_with_full_confirmation_produces_buy(self) -> None:
        base = [100.0 - i * 0.3 for i in range(40)]
        jump = [base[-1] + i * 3.0 for i in range(1, 9)]
        candles = make_ohlc_candles((base + jump)[:42])
        strategy = HeikinAshiConfluenceStrategy()

        signal = strategy.generate_signal("BTC/USD", candles)

        assert signal is not None
        assert signal.side == OrderSide.BUY
        assert signal.strategy == "ha_confluence_5_10"
        assert "confirmed by" in signal.reason

    def test_bullish_crossover_without_full_confirmation_produces_no_signal(self) -> None:
        rise = [100.0 + i * 1.5 for i in range(30)]
        pullback = [rise[-1] - i * 2.5 for i in range(1, 8)]
        resume = [pullback[-1] + i * 12.0 for i in range(1, 5)]
        candles = make_ohlc_candles((rise + pullback + resume)[:39])
        strategy = HeikinAshiConfluenceStrategy()

        # Sanity: the EMA crossover itself does fire here - it's the
        # confirmation filters (RSI already overbought, price already above
        # the upper band) that correctly veto it, not a missing crossover.
        ha = ta.ha(candles["open"], candles["high"], candles["low"], candles["close"])
        ema_fast = ta.ema(ha["HA_close"], length=5)
        ema_slow = ta.ema(ha["HA_close"], length=10)
        assert detect_crossover(ema_fast, ema_slow) == OrderSide.BUY

        assert strategy.generate_signal("BTC/USD", candles) is None

    def test_bearish_crossover_is_unfiltered(self) -> None:
        rise = [100.0 + i * 1.0 for i in range(40)]
        decline = [rise[-1] - i * 3.0 for i in range(1, 9)]
        candles = make_ohlc_candles((rise + decline)[:43])
        strategy = HeikinAshiConfluenceStrategy()

        signal = strategy.generate_signal("BTC/USD", candles)

        assert signal is not None
        assert signal.side == OrderSide.SELL
        assert signal.strategy == "ha_confluence_5_10"
        assert "crossed below" in signal.reason

    def test_flat_prices_produce_no_signal(self) -> None:
        strategy = HeikinAshiConfluenceStrategy()
        candles = make_ohlc_candles([100.0] * 40)

        assert strategy.generate_signal("BTC/USD", candles) is None

    def test_mtf_confirmation_suppresses_buy_when_higher_tf_not_aligned(self) -> None:
        base = [100.0 - i * 0.3 for i in range(40)]
        jump = [base[-1] + i * 3.0 for i in range(1, 9)]
        candles = make_ohlc_candles((base + jump)[:42])
        strategy = HeikinAshiConfluenceStrategy()
        downtrend = make_candles([110.0 - i * 2.0 for i in range(11)])

        signal = strategy.generate_signal("BTC/USD", candles, {"1h": downtrend})

        assert signal is None

    def test_mtf_confirmation_allows_buy_when_all_higher_tf_aligned(self) -> None:
        base = [100.0 - i * 0.3 for i in range(40)]
        jump = [base[-1] + i * 3.0 for i in range(1, 9)]
        candles = make_ohlc_candles((base + jump)[:42])
        strategy = HeikinAshiConfluenceStrategy()
        uptrend = make_candles([90.0 + i * 2.0 for i in range(11)])

        signal = strategy.generate_signal("BTC/USD", candles, {"1h": uptrend, "15m": uptrend})

        assert signal is not None
        assert signal.side == OrderSide.BUY

    def test_mtf_confirmation_does_not_affect_sell_signal(self) -> None:
        rise = [100.0 + i * 1.0 for i in range(40)]
        decline = [rise[-1] - i * 3.0 for i in range(1, 9)]
        candles = make_ohlc_candles((rise + decline)[:43])
        strategy = HeikinAshiConfluenceStrategy()
        downtrend = make_candles([110.0 - i * 2.0 for i in range(11)])  # would veto a BUY

        signal = strategy.generate_signal("BTC/USD", candles, {"1h": downtrend})

        assert signal is not None
        assert signal.side == OrderSide.SELL


class TestFirstColumnStartingWith:
    """Tests for the shared pandas_ta column-matching helper."""

    def test_returns_first_matching_column(self) -> None:
        df = pd.DataFrame({"MACD_12_26_9": [1.0], "MACDh_12_26_9": [2.0], "MACDs_12_26_9": [3.0]})

        assert first_column_starting_with(df, "MACDs_").iloc[0] == 3.0

    def test_prefix_matching_is_not_confused_by_similar_names(self) -> None:
        # "MACD_" must not match "MACDh_"/"MACDs_", which both start with "MACD"
        df = pd.DataFrame({"MACDh_12_26_9": [2.0], "MACD_12_26_9": [1.0]})

        assert first_column_starting_with(df, "MACD_").iloc[0] == 1.0

    def test_raises_when_no_column_matches(self) -> None:
        df = pd.DataFrame({"MACD_12_26_9": [1.0]})

        with pytest.raises(StopIteration):
            first_column_starting_with(df, "BBU_")


class TestMACDCrossoverStrategy:
    """Tests for the standalone MACD signal-line crossover strategy.

    Like the EMA tests, these verify integration with pandas_ta (right
    indicator, right periods, right min-length gate, right Signal side) by
    comparing against a MACD computed via the same trusted ta.macd() call
    inside the test - MACD's nested EMA smoothing makes hand-derived
    reference numbers impractical.
    """

    def test_rejects_fast_period_not_less_than_slow(self) -> None:
        with pytest.raises(ValueError, match="fast_period must be less than slow_period"):
            MACDCrossoverStrategy(fast_period=26, slow_period=26)

    def test_rejects_non_positive_signal_period(self) -> None:
        with pytest.raises(ValueError, match="signal_period must be positive"):
            MACDCrossoverStrategy(signal_period=0)

    def test_default_name_encodes_all_three_periods(self) -> None:
        assert MACDCrossoverStrategy().name == "macd_crossover_12_26_9"
        assert MACDCrossoverStrategy(9, 20, 5).name == "macd_crossover_9_20_5"

    def test_returns_none_when_not_enough_candles(self) -> None:
        strategy = MACDCrossoverStrategy(fast_period=3, slow_period=6, signal_period=3)
        # needs slow + signal + 1 == 10 candles
        candles = make_candles([100.0 + i for i in range(9)])

        assert strategy.generate_signal("BTC/USD", candles) is None

    def test_bullish_crossover_matches_reference_macd(self) -> None:
        closes = [100.0 - i * 2.0 for i in range(20)] + [68.0]
        candles = make_candles(closes)
        strategy = MACDCrossoverStrategy(fast_period=3, slow_period=6, signal_period=3)

        macd_df = ta.macd(pd.Series(closes, dtype=float), fast=3, slow=6, signal=3)
        reference_macd = first_column_starting_with(macd_df, "MACD_")
        reference_signal = first_column_starting_with(macd_df, "MACDs_")
        assert detect_crossover(reference_macd, reference_signal) == OrderSide.BUY

        signal = strategy.generate_signal("BTC/USD", candles)

        assert signal is not None
        assert signal.side == OrderSide.BUY
        assert signal.strategy == "macd_crossover_3_6_3"
        assert "is above" in signal.reason
        assert f"{reference_macd.iloc[-1]:.2f}" in signal.reason

    def test_bearish_crossover_matches_reference_macd(self) -> None:
        closes = [100.0 + i * 2.0 for i in range(20)] + [132.0]
        candles = make_candles(closes)
        strategy = MACDCrossoverStrategy(fast_period=3, slow_period=6, signal_period=3)

        macd_df = ta.macd(pd.Series(closes, dtype=float), fast=3, slow=6, signal=3)
        reference_macd = first_column_starting_with(macd_df, "MACD_")
        reference_signal = first_column_starting_with(macd_df, "MACDs_")
        assert detect_crossover(reference_macd, reference_signal) == OrderSide.SELL

        signal = strategy.generate_signal("BTC/USD", candles)

        assert signal is not None
        assert signal.side == OrderSide.SELL
        assert "crossed below" in signal.reason

    def test_flat_prices_produce_no_signal(self) -> None:
        strategy = MACDCrossoverStrategy(fast_period=3, slow_period=6, signal_period=3)
        candles = make_candles([100.0] * 30)

        assert strategy.generate_signal("BTC/USD", candles) is None

    def test_mtf_confirmation_suppresses_buy_when_higher_tf_not_aligned(self) -> None:
        closes = [100.0 - i * 2.0 for i in range(20)] + [68.0]
        candles = make_candles(closes)
        strategy = MACDCrossoverStrategy(fast_period=3, slow_period=6, signal_period=3)
        downtrend = make_candles([110.0 - i * 2.0 for i in range(11)])

        assert strategy.generate_signal("BTC/USD", candles, {"4h": downtrend}) is None

    def test_mtf_confirmation_allows_buy_when_higher_tf_aligned(self) -> None:
        closes = [100.0 - i * 2.0 for i in range(20)] + [68.0]
        candles = make_candles(closes)
        strategy = MACDCrossoverStrategy(fast_period=3, slow_period=6, signal_period=3)
        uptrend = make_candles([90.0 + i * 2.0 for i in range(11)])

        signal = strategy.generate_signal("BTC/USD", candles, {"4h": uptrend, "1d": uptrend})

        assert signal is not None
        assert signal.side == OrderSide.BUY

    def test_mtf_confirmation_does_not_affect_sell_signal(self) -> None:
        closes = [100.0 + i * 2.0 for i in range(20)] + [132.0]
        candles = make_candles(closes)
        strategy = MACDCrossoverStrategy(fast_period=3, slow_period=6, signal_period=3)
        downtrend = make_candles([110.0 - i * 2.0 for i in range(11)])  # would veto a BUY

        signal = strategy.generate_signal("BTC/USD", candles, {"4h": downtrend})

        assert signal is not None
        assert signal.side == OrderSide.SELL


def rising_closes() -> list[float]:
    """A rally with regular pullbacks, so RSI trends up without saturating.

    A perfectly monotonic ramp pins RSI at exactly 100, which makes its SMA 100
    too - and trend_is_bullish() then (correctly) reports "not bullish" because
    the two lines are equal. Real price series pull back; these fixtures do too.
    """
    closes = [100.0]
    for i in range(39):
        closes.append(closes[-1] + (4.0 if i % 3 else -2.0))
    return closes


def falling_closes() -> list[float]:
    """A decline with regular bounces - the mirror of rising_closes()."""
    closes = [200.0]
    for i in range(39):
        closes.append(closes[-1] - (4.0 if i % 3 else -2.0))
    return closes


def reversal_closes() -> list[float]:
    """rising_closes() plus the single sharp down bar that crosses RSI below its SMA."""
    closes = rising_closes()
    return [*closes, closes[-1] - 9.0]


def rsi_lines(closes: list[float], rsi_period: int, ma_period: int) -> tuple[pd.Series, pd.Series]:
    rsi = ta.rsi(pd.Series(closes, dtype=float), length=rsi_period)
    return rsi, ta.sma(rsi, length=ma_period)


class TestRSICrossoverStrategy:
    """Tests for the RSI-vs-its-own-SMA strategy.

    Verifies integration with pandas_ta (right indicator, right periods, right
    min-length gate, right Signal side) rather than re-deriving RSI by hand -
    the crossover arithmetic itself is already covered by TestDetectCrossover
    and TestTrendIsBullish.
    """

    def test_rejects_non_positive_periods(self) -> None:
        with pytest.raises(ValueError, match="rsi_period must be positive"):
            RSICrossoverStrategy(rsi_period=0)
        with pytest.raises(ValueError, match="ma_period must be positive"):
            RSICrossoverStrategy(ma_period=0)

    def test_name_encodes_both_periods(self) -> None:
        assert RSICrossoverStrategy().name == "rsi_crossover_14_14"
        assert RSICrossoverStrategy(rsi_period=7, ma_period=3).name == "rsi_crossover_7_3"

    def test_defaults_match_the_tradingview_rsi_indicator(self) -> None:
        """RSI Length 14, MA Type SMA, MA Length 14 - the charted configuration."""
        strategy = RSICrossoverStrategy()
        assert strategy._rsi_period == 14
        assert strategy._ma_period == 14

    def test_returns_none_below_minimum_candles(self) -> None:
        strategy = RSICrossoverStrategy(rsi_period=5, ma_period=3)
        # needs rsi_period + ma_period + 1 == 9
        short = make_candles([100.0 + i for i in range(8)])
        assert strategy.generate_signal("BTC/USD", short) is None

    def test_buys_while_rsi_sits_above_its_moving_average(self) -> None:
        closes = rising_closes()
        strategy = RSICrossoverStrategy(rsi_period=5, ma_period=3)

        rsi, sma = rsi_lines(closes, 5, 3)
        # sanity: bullish state with no fresh cross, so only a state-based
        # entry can fire here at all
        assert trend_is_bullish(rsi, sma) is True
        assert detect_crossover(rsi, sma) is None

        signal = strategy.generate_signal("BTC/USD", make_candles(closes))
        assert signal is not None
        assert signal.side == OrderSide.BUY
        assert "is above" in signal.reason
        assert signal.strategy == "rsi_crossover_5_3"

    def test_sells_when_rsi_crosses_below_its_moving_average(self) -> None:
        closes = reversal_closes()
        strategy = RSICrossoverStrategy(rsi_period=5, ma_period=3)

        rsi, sma = rsi_lines(closes, 5, 3)
        assert detect_crossover(rsi, sma) == OrderSide.SELL  # sanity

        signal = strategy.generate_signal("BTC/USD", make_candles(closes))
        assert signal is not None
        assert signal.side == OrderSide.SELL
        assert "crossed below" in signal.reason

    def test_no_signal_while_rsi_sits_below_its_moving_average(self) -> None:
        closes = falling_closes()
        strategy = RSICrossoverStrategy(rsi_period=5, ma_period=3)

        rsi, sma = rsi_lines(closes, 5, 3)
        assert trend_is_bullish(rsi, sma) is False
        assert detect_crossover(rsi, sma) is None  # already below, no fresh cross

        assert strategy.generate_signal("BTC/USD", make_candles(closes)) is None

    def test_higher_timeframe_agreement_allows_the_buy(self) -> None:
        rising = make_candles(rising_closes())
        strategy = RSICrossoverStrategy(rsi_period=5, ma_period=3)
        higher = make_candles(rising_closes())

        signal = strategy.generate_signal("BTC/USD", rising, {"4h": higher, "1d": higher})
        assert signal is not None
        assert signal.side == OrderSide.BUY

    def test_entry_timeframe_is_revalidated_when_the_higher_timeframe_turns(self) -> None:
        """A bullish higher timeframe never rescues a no-longer-bullish entry timeframe.

        The realistic failure this guards: the 4h screen goes bullish first and
        the daily is still bearish, so no entry fires. Hours later the daily
        finally turns - but by then the 4h has rolled over. Nothing is latched
        between polls, and trend_is_bullish() on the entry candles is checked
        *before* the higher-timeframe gate, so the stale 4h reading cannot leak
        through: the strategy re-derives both from the candles it is handed on
        every single call.
        """
        strategy = RSICrossoverStrategy(rsi_period=5, ma_period=3)
        entry_now_bearish = make_candles(falling_closes())
        higher_now_bullish = make_candles(rising_closes())

        assert (
            strategy.generate_signal(
                "BTC/USD", entry_now_bearish, {"1d": higher_now_bullish}
            )
            is None
        )

    def test_higher_timeframe_disagreement_blocks_the_buy(self) -> None:
        rising = make_candles(rising_closes())
        strategy = RSICrossoverStrategy(rsi_period=5, ma_period=3)
        falling = make_candles(falling_closes())

        assert strategy.generate_signal("BTC/USD", rising, {"4h": falling}) is None

    def test_exit_is_never_blocked_by_higher_timeframes(self) -> None:
        """An exit must never be harder to trigger than an entry."""
        strategy = RSICrossoverStrategy(rsi_period=5, ma_period=3)
        falling = make_candles(falling_closes())

        signal = strategy.generate_signal(
            "BTC/USD", make_candles(reversal_closes()), {"4h": falling}
        )
        assert signal is not None
        assert signal.side == OrderSide.SELL


class TestRsiSlopeIsPositive:
    """Tests for the higher-timeframe RSI slope guard."""

    def test_true_when_rsi_rose_on_the_last_bar(self) -> None:
        assert rsi_slope_is_positive(pd.Series([50.0, 55.0])) is True

    def test_false_when_rsi_fell_on_the_last_bar(self) -> None:
        assert rsi_slope_is_positive(pd.Series([55.0, 50.0])) is False

    def test_false_when_rsi_is_flat(self) -> None:
        assert rsi_slope_is_positive(pd.Series([50.0, 50.0])) is False

    def test_false_on_insufficient_data(self) -> None:
        assert rsi_slope_is_positive(pd.Series([50.0])) is False
        assert rsi_slope_is_positive(pd.Series([], dtype=float)) is False

    def test_false_during_indicator_warmup(self) -> None:
        assert rsi_slope_is_positive(pd.Series([float("nan"), 50.0])) is False
        assert rsi_slope_is_positive(pd.Series([50.0, float("nan")])) is False


class TestMtfRsiConfirmsBuy:
    """Tests for the RSI strategy's own higher-timeframe confirmation helper."""

    def test_confirms_when_every_timeframe_has_rsi_above_its_average(self) -> None:
        rising = make_candles(rising_closes())
        assert mtf_rsi_confirms_buy({"4h": rising, "1d": rising}, 5, 3) is True

    def test_rejects_when_any_timeframe_has_rsi_below_its_average(self) -> None:
        rising = make_candles(rising_closes())
        falling = make_candles(falling_closes())
        assert mtf_rsi_confirms_buy({"4h": rising, "1d": falling}, 5, 3) is False

    def test_rejects_when_a_timeframe_has_too_few_candles(self) -> None:
        rising = make_candles(rising_closes())
        short = make_candles([100.0, 101.0, 102.0])
        assert mtf_rsi_confirms_buy({"4h": rising, "1d": short}, 5, 3) is False

    def test_empty_dict_is_vacuously_confirmed(self) -> None:
        assert mtf_rsi_confirms_buy({}, 5, 3) is True

    def test_rejects_when_rsi_is_above_its_average_but_declining(self) -> None:
        """The live failure mode this whole change guards against.

        A higher timeframe can sit above its own RSI SMA (bullish by
        trend_is_bullish()) while the RSI has already turned down bar over
        bar - "green but declining". Built by taking a rally and appending a
        single soft pullback bar too shallow to cross the SMA, so the state
        check alone would still confirm.
        """
        closes = rising_closes()
        rsi, sma = rsi_lines(closes, 5, 3)
        assert trend_is_bullish(rsi, sma) is True  # sanity: still "green"

        declining = closes + [closes[-1] - 0.1]
        declining_rsi, declining_sma = rsi_lines(declining, 5, 3)
        # sanity: still above its SMA (state check alone would confirm)...
        assert trend_is_bullish(declining_rsi, declining_sma) is True
        # ...but the RSI itself just turned down bar over bar
        assert declining_rsi.iloc[-1] < declining_rsi.iloc[-2]

        assert mtf_rsi_confirms_buy({"4h": make_candles(declining)}, 5, 3) is False

    def test_confirmation_requires_slope_on_every_timeframe(self) -> None:
        closes = rising_closes()
        declining = closes + [closes[-1] - 0.1]
        rising = make_candles(closes)

        assert (
            mtf_rsi_confirms_buy({"4h": rising, "1d": make_candles(declining)}, 5, 3)
            is False
        )


class TestRsiAndSignalLine:
    """The shared construction used by both the entry and the confirmation."""

    def test_matches_pandas_ta_directly(self) -> None:
        closes = pd.Series([100.0 + (i % 7) * 3 - (i % 5) * 2 for i in range(60)], dtype=float)
        rsi, sma = rsi_and_signal_line(closes, 14, 14)

        pd.testing.assert_series_equal(rsi, ta.rsi(closes, length=14))
        pd.testing.assert_series_equal(sma, ta.sma(ta.rsi(closes, length=14), length=14))
