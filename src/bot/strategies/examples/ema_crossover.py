"""Example strategy: exponential moving-average crossover.

Same crossover logic as MovingAverageCrossoverStrategy, but using an EMA
instead of an SMA for both the fast and slow lines. An EMA weights recent
candles more heavily, so it reacts faster to new price moves and lags less
than an SMA of the same period — at the cost of being noisier and more prone
to whipsaws in choppy/ranging markets. Which one performs better is asset-
and timeframe-dependent; compare them with scripts/backtest.py rather than
assuming either is universally superior.
"""

import pandas as pd
import pandas_ta as ta

from src.bot.strategies.base import Signal, Strategy, detect_crossover
from src.exchange.executor import OrderSide


class EMACrossoverStrategy(Strategy):
    """Buys when the fast EMA crosses above the slow EMA, sells on the reverse cross.

    Requires at least `slow_period + 1` candles to detect a cross — one extra
    candle so the previous bar's fast/slow relationship can be compared against
    the current one.
    """

    def __init__(self, fast_period: int = 10, slow_period: int = 30) -> None:
        if fast_period >= slow_period:
            raise ValueError("fast_period must be less than slow_period")
        super().__init__(name=f"ema_crossover_{fast_period}_{slow_period}")
        self._fast_period = fast_period
        self._slow_period = slow_period

    def generate_signal(self, symbol: str, candles: pd.DataFrame) -> Signal | None:
        if len(candles) < self._slow_period + 1:
            return None

        fast = ta.ema(candles["close"], length=self._fast_period)
        slow = ta.ema(candles["close"], length=self._slow_period)

        side = detect_crossover(fast, slow)
        if side is None:
            return None

        direction = "above" if side == OrderSide.BUY else "below"
        return Signal(
            symbol=symbol,
            side=side,
            strategy=self.name,
            reason=(
                f"fast EMA({self._fast_period})={fast.iloc[-1]:.2f} crossed {direction} "
                f"slow EMA({self._slow_period})={slow.iloc[-1]:.2f}"
            ),
        )
