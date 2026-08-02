"""Example strategy: MACD signal-line crossover.

MACD (Moving Average Convergence Divergence) is the difference between a fast
and a slow EMA, smoothed by a "signal" EMA of that difference. Trading its
signal-line crossover is a momentum play rather than a price-level one: the
MACD line crossing above its signal means the fast/slow EMA gap is *widening
bullishly*, which tends to fire earlier than the underlying EMA crossover
itself (the EMAs need to actually cross; MACD only needs their spread to turn).

Earlier is not automatically better - firing sooner also means firing on moves
that never develop. Compare it against EMACrossoverStrategy with
scripts/backtest.py rather than assuming the extra sensitivity pays for itself
after fees.
"""

import pandas as pd
import pandas_ta as ta

from src.bot.strategies.base import (
    Signal,
    Strategy,
    detect_crossover,
    first_column_starting_with,
    mtf_trend_confirms_buy,
)
from src.exchange.executor import OrderSide


class MACDCrossoverStrategy(Strategy):
    """Buys when the MACD line crosses above its signal line, sells on the reverse cross.

    Needs `slow_period + signal_period + 1` candles before it can produce a
    signal: the MACD line itself only becomes defined after `slow_period` bars,
    its signal line needs a further `signal_period` bars of MACD values to
    smooth, and one extra bar on top so the previous bar's relationship can be
    compared against the current one.
    """

    def __init__(
        self,
        fast_period: int = 12,
        slow_period: int = 26,
        signal_period: int = 9,
    ) -> None:
        if fast_period >= slow_period:
            raise ValueError("fast_period must be less than slow_period")
        if signal_period <= 0:
            raise ValueError("signal_period must be positive")
        super().__init__(name=f"macd_crossover_{fast_period}_{slow_period}_{signal_period}")
        self._fast_period = fast_period
        self._slow_period = slow_period
        self._signal_period = signal_period

    @property
    def _min_candles(self) -> int:
        return self._slow_period + self._signal_period + 1

    def generate_signal(
        self,
        symbol: str,
        candles: pd.DataFrame,
        higher_tf_candles: dict[str, pd.DataFrame] | None = None,
    ) -> Signal | None:
        if len(candles) < self._min_candles:
            return None

        macd_df = ta.macd(
            candles["close"],
            fast=self._fast_period,
            slow=self._slow_period,
            signal=self._signal_period,
        )
        macd_line = first_column_starting_with(macd_df, "MACD_")
        signal_line = first_column_starting_with(macd_df, "MACDs_")

        side = detect_crossover(macd_line, signal_line)
        if side is None:
            return None

        # Confirmation uses the strategy's own fast/slow EMA periods on the
        # higher timeframes rather than their MACD: the filter's job is "is the
        # broader trend pointed this way", which a plain EMA relationship answers
        # directly, while a higher-timeframe MACD cross would be a second
        # momentum trigger rather than a trend check.
        if side == OrderSide.BUY and higher_tf_candles:
            if not mtf_trend_confirms_buy(
                higher_tf_candles, self._fast_period, self._slow_period, use_ema=True
            ):
                return None

        direction = "above" if side == OrderSide.BUY else "below"
        return Signal(
            symbol=symbol,
            side=side,
            strategy=self.name,
            reason=(
                f"MACD({self._fast_period},{self._slow_period})="
                f"{macd_line.iloc[-1]:.2f} crossed {direction} its "
                f"signal({self._signal_period})={signal_line.iloc[-1]:.2f}"
            ),
        )
