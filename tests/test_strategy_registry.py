"""Tests for the strategy registry shared by the backtest and run_bot CLIs."""

import pytest

from src.bot.strategies.base import Strategy
from src.bot.strategies.examples.rsi_confirmation_exit import RSIConfirmationExitStrategy
from src.bot.strategies.examples.rsi_crossover import RSICrossoverStrategy
from src.bot.strategies.registry import STRATEGIES, build_period_kwargs, create_strategy


class TestStrategiesRegistry:
    def test_every_entry_is_a_strategy_subclass(self) -> None:
        for name, cls in STRATEGIES.items():
            assert issubclass(cls, Strategy), name

    def test_every_entry_is_constructible_with_no_arguments(self) -> None:
        """Both CLIs fall back to a bare constructor when no period flags are passed.

        Includes rsi_confirmation_exit: its entry_timeframe defaults to "4h"
        specifically so this invariant holds for every registry entry, not
        just most of them - see that class's own docstring for why the
        default exists at all despite the strategy's own preference for
        explicit configuration.
        """
        for name, cls in STRATEGIES.items():
            assert isinstance(cls(), Strategy), name

    def test_expected_choices_are_registered(self) -> None:
        assert sorted(STRATEGIES) == [
            "confluence",
            "ema",
            "macd",
            "rsi",
            "rsi_confirmation_exit",
            "sma",
        ]
        assert STRATEGIES["rsi"] is RSICrossoverStrategy
        assert STRATEGIES["rsi_confirmation_exit"] is RSIConfirmationExitStrategy


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

    def test_exit_margin_maps_to_rsi_kwargs(self) -> None:
        assert build_period_kwargs("rsi", exit_margin=1.5) == {"exit_margin": 1.5}

    def test_exit_margin_is_rejected_for_other_strategies(self) -> None:
        with pytest.raises(ValueError, match="--exit-margin only applies to --strategy rsi"):
            build_period_kwargs("ema", exit_margin=1.5)

    def test_rsi_options_map_to_rsi_kwargs(self) -> None:
        assert build_period_kwargs("rsi", rsi_period=7, ma_period=3) == {
            "rsi_period": 7,
            "ma_period": 3,
        }

    @pytest.mark.parametrize("strategy", ["rsi", "rsi_confirmation_exit"])
    @pytest.mark.parametrize("flag", ["fast", "slow"])
    def test_rsi_style_strategies_reject_moving_average_flags(
        self, strategy: str, flag: str
    ) -> None:
        """An RSI lookback is not a "fast moving average" - the flags must not be
        aliased, for either RSI-style strategy."""
        with pytest.raises(ValueError, match=f"does not apply to --strategy {strategy}"):
            build_period_kwargs(strategy, **{flag: 5})  # type: ignore[arg-type]

    @pytest.mark.parametrize("flag", ["rsi_period", "ma_period"])
    @pytest.mark.parametrize("strategy", ["sma", "ema", "macd", "confluence"])
    def test_non_rsi_strategies_reject_rsi_flags(self, strategy: str, flag: str) -> None:
        with pytest.raises(ValueError, match="only applies to --strategy rsi"):
            build_period_kwargs(strategy, **{flag: 14})  # type: ignore[arg-type]

    def test_rsi_confirmation_exit_accepts_rsi_period_and_ma_period(self) -> None:
        """Shares RSICrossoverStrategy's entry vocabulary - only exit_margin,
        which it has no constructor parameter for at all, stays exclusive to
        plain "rsi"."""
        assert build_period_kwargs("rsi_confirmation_exit", rsi_period=7, ma_period=3) == {
            "rsi_period": 7,
            "ma_period": 3,
        }

    def test_rsi_confirmation_exit_rejects_exit_margin(self) -> None:
        with pytest.raises(ValueError, match="--exit-margin only applies to --strategy rsi"):
            build_period_kwargs("rsi_confirmation_exit", exit_margin=2.0)

    def test_entry_timeframe_maps_to_kwargs_only_for_rsi_confirmation_exit(self) -> None:
        assert build_period_kwargs("rsi_confirmation_exit", entry_timeframe="1h") == {
            "entry_timeframe": "1h"
        }

    @pytest.mark.parametrize("strategy", ["sma", "ema", "macd", "rsi", "confluence"])
    def test_entry_timeframe_is_silently_unused_by_other_strategies(self, strategy: str) -> None:
        """Not a user-optional flag like the others - both CLIs always have their
        own --timeframe in hand and thread it through unconditionally regardless
        of --strategy, so this must never raise the way a genuinely mismatched
        flag (e.g. --exit-margin on "ema") does."""
        assert "entry_timeframe" not in build_period_kwargs(strategy, entry_timeframe="4h")


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
        assert create_strategy("rsi", exit_margin=2.0).name == "rsi_crossover_14_14_m2"
        assert (
            create_strategy("rsi_confirmation_exit", entry_timeframe="1h").name
            == "rsi_confirmation_exit_1h_14_14"
        )

    def test_every_registered_strategy_builds_with_no_options(self) -> None:
        for name in STRATEGIES:
            assert isinstance(create_strategy(name), Strategy), name

    def test_propagates_validation_errors(self) -> None:
        with pytest.raises(ValueError, match="does not apply to --strategy rsi"):
            create_strategy("rsi", fast=5)
