"""Example strategy: simple moving-average crossover."""

import pandas as pd
import pandas_ta as ta

from src.bot.strategies.base import Signal, Strategy
from src.exchange.executor import OrderSide


class MovingAverageCrossoverStrategy(Strategy):
    """Buys when the fast SMA crosses above the slow SMA, sells on the reverse cross.

    Requires at least `slow_period + 1` candles to detect a cross — one extra
    candle so the previous bar's fast/slow relationship can be compared against
    the current one.
    """

    def __init__(self, fast_period: int = 10, slow_period: int = 30) -> None:
        if fast_period >= slow_period:
            raise ValueError("fast_period must be less than slow_period")
        super().__init__(name=f"sma_crossover_{fast_period}_{slow_period}")
        self._fast_period = fast_period
        self._slow_period = slow_period

    def generate_signal(self, symbol: str, candles: pd.DataFrame) -> Signal | None:
        if len(candles) < self._slow_period + 1:
            return None

        fast = ta.sma(candles["close"], length=self._fast_period)
        slow = ta.sma(candles["close"], length=self._slow_period)

        prev_fast, prev_slow = fast.iloc[-2], slow.iloc[-2]
        curr_fast, curr_slow = fast.iloc[-1], slow.iloc[-1]

        crossed_up = prev_fast <= prev_slow and curr_fast > curr_slow
        crossed_down = prev_fast >= prev_slow and curr_fast < curr_slow

        if crossed_up:
            return Signal(
                symbol=symbol,
                side=OrderSide.BUY,
                strategy=self.name,
                reason=(
                    f"fast SMA({self._fast_period})={curr_fast:.2f} crossed above "
                    f"slow SMA({self._slow_period})={curr_slow:.2f}"
                ),
            )
        if crossed_down:
            return Signal(
                symbol=symbol,
                side=OrderSide.SELL,
                strategy=self.name,
                reason=(
                    f"fast SMA({self._fast_period})={curr_fast:.2f} crossed below "
                    f"slow SMA({self._slow_period})={curr_slow:.2f}"
                ),
            )
        return None
