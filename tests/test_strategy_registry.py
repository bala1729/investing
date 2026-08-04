"""Tests for the strategy registry shared by the backtest and run_bot CLIs."""

import pytest

from src.bot.strategies.base import Strategy
from src.bot.strategies.examples.rsi_crossover import RSICrossoverStrategy
from src.bot.strategies.registry import STRATEGIES, build_period_kwargs, create_strategy


class TestStrategiesRegistry:
    def test_every_entry_is_a_strategy_subclass(self) -> None:
        for name, cls in STRATEGIES.items():
            assert issubclass(cls, Strategy), name

    def test_every_entry_is_constructible_with_no_arguments(self) -> None:
        """Both CLIs fall back to a bare constructor when no period flags are passed."""
        for name, cls in STRATEGIES.items():
            assert isinstance(cls(), Strategy), name

    def test_expected_choices_are_registered(self) -> None:
        assert sorted(STRATEGIES) == ["confluence", "ema", "macd", "rsi", "sma"]
        assert STRATEGIES["rsi"] is RSICrossoverStrategy


class TestBuildPeriodKwargs:
    def test_no_options_yields_no_kwargs(self) -> None:
        assert build_period_kwargs("ema") == {}

    def test_fast_and_slow_map_to_period_kwargs(self) -> None:
        assert build_period_kwargs("ema", fast=5, slow=20) == {
            "fast_period": 5,
            "slow_period": 20,
        }

    def test_signal_is_accepted_only_for_macd(self) -> None:
        assert build_period_kwargs("macd", signal=9) == {"signal_period": 9}
        with pytest.raises(ValueError, match="--signal only applies to --strategy macd"):
            build_period_kwargs("ema", signal=9)

    def test_rsi_options_map_to_rsi_kwargs(self) -> None:
        assert build_period_kwargs("rsi", rsi_period=7, ma_period=3) == {
            "rsi_period": 7,
            "ma_period": 3,
        }

    @pytest.mark.parametrize("flag", ["fast", "slow"])
    def test_rsi_rejects_moving_average_flags(self, flag: str) -> None:
        """An RSI lookback is not a "fast moving average" - the flags must not be aliased."""
        with pytest.raises(ValueError, match="does not apply to --strategy rsi"):
            build_period_kwargs("rsi", **{flag: 5})

    @pytest.mark.parametrize("flag", ["rsi_period", "ma_period"])
    @pytest.mark.parametrize("strategy", ["sma", "ema", "macd", "confluence"])
    def test_non_rsi_strategies_reject_rsi_flags(self, strategy: str, flag: str) -> None:
        with pytest.raises(ValueError, match="only applies to --strategy rsi"):
            build_period_kwargs(strategy, **{flag: 14})


class TestCreateStrategy:
    """The public path both CLIs take: validate the options, then construct."""

    def test_kwargs_actually_construct_each_strategy(self) -> None:
        """Guards the mapping end-to-end: a wrong kwarg name would TypeError here.

        create_strategy() builds through Any because the registry is
        heterogeneous, so the type checker cannot catch a bad mapping - this
        test is what does.
        """
        assert create_strategy("ema", fast=5, slow=20).name == "ema_crossover_5_20"
        assert create_strategy("macd", fast=3, slow=8, signal=2).name == "macd_crossover_3_8_2"
        assert create_strategy("rsi", rsi_period=7, ma_period=3).name == "rsi_crossover_7_3"

    def test_every_registered_strategy_builds_with_no_options(self) -> None:
        for name in STRATEGIES:
            assert isinstance(create_strategy(name), Strategy), name

    def test_propagates_validation_errors(self) -> None:
        with pytest.raises(ValueError, match="does not apply to --strategy rsi"):
            create_strategy("rsi", fast=5)
