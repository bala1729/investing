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
from src.bot.strategies.examples.rsi_crossover import RSICrossoverStrategy

STRATEGIES: dict[str, type[Strategy]] = {
    "sma": MovingAverageCrossoverStrategy,
    "ema": EMACrossoverStrategy,
    "macd": MACDCrossoverStrategy,
    "rsi": RSICrossoverStrategy,
    "confluence": HeikinAshiConfluenceStrategy,
}


def build_period_kwargs(
    strategy: str,
    *,
    fast: int | None = None,
    slow: int | None = None,
    signal: int | None = None,
    rsi_period: int | None = None,
    ma_period: int | None = None,
) -> dict[str, int]:
    """Translate CLI period options into constructor kwargs for `strategy`.

    The strategies do not share one parameter vocabulary: the crossover ones
    take fast_period/slow_period, macd adds signal_period, and rsi takes
    rsi_period/ma_period instead - an RSI lookback is not a "fast moving
    average", so reusing --fast for it would misdescribe what the number does.

    Options that do not apply to the selected strategy raise ValueError rather
    than being silently dropped or forwarded into a TypeError from the
    constructor, so a mistyped command fails with a message naming the flag.
    """
    if strategy == "rsi":
        for flag, value in (("--fast", fast), ("--slow", slow)):
            if value is not None:
                raise ValueError(
                    f"{flag} does not apply to --strategy rsi; "
                    "use --rsi-period and --ma-period instead."
                )
    else:
        for flag, value in (("--rsi-period", rsi_period), ("--ma-period", ma_period)):
            if value is not None:
                raise ValueError(f"{flag} only applies to --strategy rsi, not {strategy}.")

    if signal is not None and strategy != "macd":
        raise ValueError(f"--signal only applies to --strategy macd, not {strategy}.")

    period_kwargs: dict[str, int] = {}
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
    return period_kwargs


def create_strategy(
    strategy: str,
    *,
    fast: int | None = None,
    slow: int | None = None,
    signal: int | None = None,
    rsi_period: int | None = None,
    ma_period: int | None = None,
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
    )
    strategy_cls: Any = STRATEGIES[strategy]
    built: Strategy = strategy_cls(**period_kwargs)
    return built
