"""Base strategy interface and shared candle-data helpers."""

import math
from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Any

import pandas as pd
import pandas_ta as ta

from src.exchange.executor import OrderSide

MTF_CONFIRMATION_MAP: dict[str, tuple[str, ...]] = {
    "5m": ("15m", "1h"),
    "15m": ("1h", "4h"),
    "1h": ("4h", "1d"),
    "4h": ("1d",),
    "1d": ("1w", "2w"),
}
"""Entry timeframe -> the higher timeframes that must confirm a BUY.

Standard top-down multi-timeframe analysis: the strategy's own crossover
trigger fires on the entry (primary/--timeframe) candles as always, but a BUY
only goes through if every timeframe listed here independently confirms the
same direction. Timeframes with no entry here (1m, 30m, 1w, 2w) get no
confirmation filtering - single-timeframe behavior, unchanged.

Most entries confirm against both a setup and a trend timeframe. The `4h` entry
is the exception: it confirms against its setup timeframe (`1d`) only, with no
`1w` trend screen. A weekly EMA pair turns over very slowly, so it can stay
bearish for weeks after the daily has turned - vetoing every `4h` entry through
the opening leg of a move, on a timeframe whose whole appeal is engaging early
enough to matter. Confirming against the daily alone keeps the top-down
discipline while letting the entry participate sooner.

Tuple lengths vary by design; every consumer iterates rather than unpacking
positionally."""


@dataclass(frozen=True)
class Signal:
    """A trading signal produced by a strategy."""

    symbol: str
    side: OrderSide
    strategy: str
    reason: str
    confidence: float = 1.0
    exit_fraction: float = 1.0
    """Fraction of the open position a SELL should close. Ignored on BUY.

    Defaults to a full exit so every strategy that never sets this behaves
    exactly as before partial exits existed.
    """

    def __post_init__(self) -> None:
        if not (0 < self.exit_fraction <= 1):
            raise ValueError("exit_fraction must be between 0 (exclusive) and 1 (inclusive)")


def detect_crossover(fast: pd.Series, slow: pd.Series) -> OrderSide | None:
    """Detect whether `fast` crossed `slow` on the most recently completed bar.

    Compares the last two values of each series (both must already be aligned
    to the same candles). Returns OrderSide.BUY for a bullish cross (fast
    moves from at-or-below to above slow), OrderSide.SELL for a bearish cross
    (the reverse), or None if there's no fresh cross or not enough data yet
    (e.g. still inside an indicator's NaN warmup period).
    """
    if len(fast) < 2 or len(slow) < 2:
        return None

    prev_fast, prev_slow = fast.iloc[-2], slow.iloc[-2]
    curr_fast, curr_slow = fast.iloc[-1], slow.iloc[-1]

    if pd.isna(prev_fast) or pd.isna(prev_slow) or pd.isna(curr_fast) or pd.isna(curr_slow):
        return None

    if prev_fast <= prev_slow and curr_fast > curr_slow:
        return OrderSide.BUY
    if prev_fast >= prev_slow and curr_fast < curr_slow:
        return OrderSide.SELL
    return None


def trend_is_bullish(fast: pd.Series, slow: pd.Series) -> bool:
    """Whether `fast` is above `slow` right now - a state, not a fresh cross.

    Entries key off this rather than off detect_crossover() because a crossover
    is a single-bar event that can be lost. If something blocks the trade on the
    exact bar the lines cross - higher-timeframe confirmation not yet satisfied,
    a risk limit, no free balance - a cross-only entry discards the signal
    permanently and sits out the entire move that follows, since the lines never
    cross again on the way up. Asking "is the trend bullish now" instead lets the
    entry happen as soon as whatever was blocking it clears.

    Returns False (not None) during an indicator's NaN warmup, so callers can
    treat it as a plain "no entry".

    Values within floating-point noise of each other count as *not* bullish.
    This matters more than it looks: a rounding artifact is enough to make a
    bare `>` true on flat prices (pandas_ta computes SMA(3) of a constant 100 as
    99.99999999999999, so a dead-flat market reads as an uptrend by 1.4e-14).
    detect_crossover() never had this problem because the same artifact appears
    on both bars it compares, so it cancels; a single-bar state check has
    nothing to cancel against. The tolerance is far below any real price move,
    so it only ever suppresses numerical noise.
    """
    if len(fast) == 0 or len(slow) == 0:
        return False

    curr_fast, curr_slow = fast.iloc[-1], slow.iloc[-1]
    if pd.isna(curr_fast) or pd.isna(curr_slow):
        return False
    if math.isclose(curr_fast, curr_slow, rel_tol=1e-9, abs_tol=0.0):
        return False
    return bool(curr_fast > curr_slow)


def first_column_starting_with(df: pd.DataFrame, prefix: str) -> pd.Series:
    """Return the first column whose name starts with `prefix`.

    pandas_ta's exact column suffixes vary with the parameters passed (e.g.
    Bollinger Band columns repeat the std multiplier: "BBU_20_2.0_2.0") -
    matching by prefix instead of a hardcoded full name avoids depending on
    that exact, version-sensitive formatting.
    """
    return df[next(c for c in df.columns if c.startswith(prefix))]


def mtf_trend_confirms_buy(
    higher_tf_candles: dict[str, pd.DataFrame],
    fast_period: int,
    slow_period: int,
    use_ema: bool = True,
) -> bool:
    """Whether every higher timeframe in `higher_tf_candles` currently shows fast MA > slow MA.

    Gates an entry signal generated on a strategy's primary (entry) timeframe
    behind confirmation that the higher ("setup"/"trend") timeframes independently
    agree with the bullish direction right now - not a fresh cross on each one
    (higher timeframes cross far less often, so requiring a simultaneous fresh
    cross on all of them would rarely align with a fast-moving entry-timeframe
    trigger), just that the trend is currently pointed the same way. Only meant
    for entries: exits stay unfiltered so risk management is never harder to
    trigger than an entry.
    """
    ma = ta.ema if use_ema else ta.sma
    for candles in higher_tf_candles.values():
        if len(candles) < slow_period + 1:
            return False
        fast = ma(candles["close"], length=fast_period)
        slow = ma(candles["close"], length=slow_period)
        if pd.isna(fast.iloc[-1]) or pd.isna(slow.iloc[-1]):
            return False
        if not (fast.iloc[-1] > slow.iloc[-1]):
            return False
    return True


def ohlcv_to_dataframe(ohlcv: list[list[Any]]) -> pd.DataFrame:
    """Convert raw ccxt OHLCV rows into an indexed pandas DataFrame.

    Args:
        ohlcv: Rows of [timestamp_ms, open, high, low, close, volume], as
            returned by KrakenClient.fetch_ohlcv().

    Returns:
        DataFrame with open/high/low/close/volume columns, indexed by UTC
        timestamp, oldest candle first.
    """
    df = pd.DataFrame(ohlcv, columns=["timestamp", "open", "high", "low", "close", "volume"])
    df["timestamp"] = pd.to_datetime(df["timestamp"], unit="ms", utc=True)
    return df.set_index("timestamp")


class Strategy(ABC):
    """Base class for trading strategies.

    A strategy is a pure function from historical candle data to an optional
    trading signal — it does not fetch market data or execute orders itself.
    That keeps strategies trivially unit-testable and reusable for both the
    autonomous bot engine and backtesting.
    """

    def __init__(self, name: str | None = None) -> None:
        self.name = name or type(self).__name__

    @abstractmethod
    def generate_signal(
        self,
        symbol: str,
        candles: pd.DataFrame,
        higher_tf_candles: dict[str, pd.DataFrame] | None = None,
    ) -> Signal | None:
        """Analyze candle data and return a trading signal, or None to take no action.

        Args:
            symbol: Trading pair symbol the candles belong to.
            candles: OHLCV data indexed by timestamp, oldest first (see
                ohlcv_to_dataframe).
            higher_tf_candles: Optional higher-timeframe OHLCV data, keyed by
                timeframe string, for strategies that apply multi-timeframe
                entry confirmation (see MTF_CONFIRMATION_MAP). None when the
                primary (entry) timeframe has no higher timeframes mapped.

        Returns:
            A Signal to act on, or None if the strategy has no opinion right now.
        """
        raise NotImplementedError  # pragma: no cover
