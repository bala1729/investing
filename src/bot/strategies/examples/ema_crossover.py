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

from src.bot.strategies.base import (
    Signal,
    Strategy,
    detect_crossover,
    mtf_trend_confirms_buy,
    trend_is_bullish,
)
from src.exchange.executor import OrderSide


class EMACrossoverStrategy(Strategy):
    """Holds while the fast EMA is above the slow EMA, sells when it crosses back below.

    Entry is *state*-based and exit is cross-based, for the reasons described in
    MovingAverageCrossoverStrategy and trend_is_bullish(). A buy is emitted on
    every bullish bar; callers ignore the repeats.

    Requires at least `slow_period + 1` candles - one more than the slow average
    needs, so the previous bar's relationship is available to detect the exit
    cross.
    """

    def __init__(self, fast_period: int = 10, slow_period: int = 30) -> None:
        if fast_period >= slow_period:
            raise ValueError("fast_period must be less than slow_period")
        super().__init__(name=f"ema_crossover_{fast_period}_{slow_period}")
        self._fast_period = fast_period
        self._slow_period = slow_period

    def generate_signal(
        self,
        symbol: str,
        candles: pd.DataFrame,
        higher_tf_candles: dict[str, pd.DataFrame] | None = None,
    ) -> Signal | None:
        if len(candles) < self._slow_period + 1:
            return None

        fast = ta.ema(candles["close"], length=self._fast_period)
        slow = ta.ema(candles["close"], length=self._slow_period)

        if detect_crossover(fast, slow) == OrderSide.SELL:
            return Signal(
                symbol=symbol,
                side=OrderSide.SELL,
                strategy=self.name,
                reason=(
                    f"fast EMA({self._fast_period})={fast.iloc[-1]:.2f} crossed below "
                    f"slow EMA({self._slow_period})={slow.iloc[-1]:.2f}"
                ),
            )

        if not trend_is_bullish(fast, slow):
            return None

        if higher_tf_candles and not mtf_trend_confirms_buy(
            higher_tf_candles, self._fast_period, self._slow_period, use_ema=True
        ):
            return None

        return Signal(
            symbol=symbol,
            side=OrderSide.BUY,
            strategy=self.name,
            reason=(
                f"fast EMA({self._fast_period})={fast.iloc[-1]:.2f} is above "
                f"slow EMA({self._slow_period})={slow.iloc[-1]:.2f}"
            ),
        )
