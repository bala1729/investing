"""The strategy registry shared by scripts/backtest.py and scripts/run_bot.py.

Both CLIs offer the same --strategy choices and the same period flags, so the
mapping and the flag validation live here rather than being duplicated (and
drifting) between two scripts.

Deliberately free of argparse: the public helpers take plain optional ints and
raise ValueError, leaving each CLI to decide how to surface the failure. That
keeps the validation directly unit-testable without constructing a parser.
"""

from typing import Any

from src.bot.strategies.base import Strategy
from src.bot.strategies.examples.ema_crossover import EMACrossoverStrategy
from src.bot.strategies.examples.heikin_ashi_confluence import HeikinAshiConfluenceStrategy
from src.bot.strategies.examples.macd_crossover import MACDCrossoverStrategy
from src.bot.strategies.examples.moving_average_crossover import MovingAverageCrossoverStrategy
from src.bot.strategies.examples.rsi_confirmation_exit import RSIConfirmationExitStrategy
from src.bot.strategies.examples.rsi_crossover import RSICrossoverStrategy

STRATEGIES: dict[str, type[Strategy]] = {
    "sma": MovingAverageCrossoverStrategy,
    "ema": EMACrossoverStrategy,
    "macd": MACDCrossoverStrategy,
    "rsi": RSICrossoverStrategy,
    "confluence": HeikinAshiConfluenceStrategy,
    "rsi_confirmation_exit": RSIConfirmationExitStrategy,
}


# Strategies that take rsi_period/ma_period instead of fast/slow. Two entries,
# not just "rsi", because RSIConfirmationExitStrategy shares that same
# RSI-vs-its-own-SMA vocabulary for its entry side - only exit_margin (below)
# stays exclusive to "rsi", since the confirmation-exit variant has no
# equivalent constructor parameter at all.
_RSI_STYLE_STRATEGIES = {"rsi", "rsi_confirmation_exit"}


def build_period_kwargs(
    strategy: str,
    *,
    fast: int | None = None,
    slow: int | None = None,
    signal: int | None = None,
    rsi_period: int | None = None,
    ma_period: int | None = None,
    exit_margin: float | None = None,
    entry_timeframe: str | None = None,
) -> dict[str, int | float | str]:
    """Translate CLI period options into constructor kwargs for `strategy`.

    The strategies do not share one parameter vocabulary: the crossover ones
    take fast_period/slow_period, macd adds signal_period, and the RSI-style
    ones take rsi_period/ma_period instead - an RSI lookback is not a "fast
    moving average", so reusing --fast for it would misdescribe what the
    number does.

    Options that do not apply to the selected strategy raise ValueError rather
    than being silently dropped or forwarded into a TypeError from the
    constructor, so a mistyped command fails with a message naming the flag.

    `entry_timeframe` is the one exception to that rule, deliberately: it is
    not a user-optional CLI flag the way the others are, it is the same
    `--timeframe` every strategy already gets at the fetch-candles call site -
    both CLIs should always thread it straight through here unconditionally,
    regardless of which strategy was selected, so raising when it "doesn't
    apply" would just make every other `--strategy` choice fail on an argument
    the caller never chose to pass. Consumed only by strategies that declare
    an `entry_timeframe` constructor parameter; silently unused otherwise.
    """
    if strategy in _RSI_STYLE_STRATEGIES:
        for flag, value in (("--fast", fast), ("--slow", slow)):
            if value is not None:
                raise ValueError(
                    f"{flag} does not apply to --strategy {strategy}; "
                    "use --rsi-period and --ma-period instead."
                )
    else:
        for rsi_flag, rsi_value in (("--rsi-period", rsi_period), ("--ma-period", ma_period)):
            if rsi_value is not None:
                raise ValueError(f"{rsi_flag} only applies to --strategy rsi, not {strategy}.")

    if exit_margin is not None and strategy != "rsi":
        raise ValueError(f"--exit-margin only applies to --strategy rsi, not {strategy}.")

    if signal is not None and strategy != "macd":
        raise ValueError(f"--signal only applies to --strategy macd, not {strategy}.")

    period_kwargs: dict[str, int | float | str] = {}
    if fast is not None:
        period_kwargs["fast_period"] = fast
    if slow is not None:
        period_kwargs["slow_period"] = slow
    if signal is not None:
        period_kwargs["signal_period"] = signal
    if rsi_period is not None:
        period_kwargs["rsi_period"] = rsi_period
    if ma_period is not None:
        period_kwargs["ma_period"] = ma_period
    if exit_margin is not None:
        period_kwargs["exit_margin"] = exit_margin
    if entry_timeframe is not None and strategy == "rsi_confirmation_exit":
        period_kwargs["entry_timeframe"] = entry_timeframe
    return period_kwargs


def create_strategy(
    strategy: str,
    *,
    fast: int | None = None,
    slow: int | None = None,
    signal: int | None = None,
    rsi_period: int | None = None,
    ma_period: int | None = None,
    exit_margin: float | None = None,
    entry_timeframe: str | None = None,
) -> Strategy:
    """Validate the period options for `strategy` and construct it.

    The registry is deliberately heterogeneous - each strategy takes a different
    set of period arguments - so no single static signature describes
    `STRATEGIES[strategy](...)`. The constructor call is therefore made through
    Any, and correctness is enforced by build_period_kwargs() (which rejects any
    option that does not apply) plus a test that round-trips every strategy
    through both functions. Confining the dynamic call to this one place keeps
    the two CLIs fully typed.
    """
    period_kwargs = build_period_kwargs(
        strategy,
        fast=fast,
        slow=slow,
        signal=signal,
        rsi_period=rsi_period,
        ma_period=ma_period,
        exit_margin=exit_margin,
        entry_timeframe=entry_timeframe,
    )
    strategy_cls: Any = STRATEGIES[strategy]
    built: Strategy = strategy_cls(**period_kwargs)
    return built
