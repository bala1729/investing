"""Example strategy: simple moving-average crossover."""

import pandas as pd
import pandas_ta as ta

from src.bot.strategies.base import Signal, Strategy, detect_crossover, mtf_trend_confirms_buy
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

    def generate_signal(
        self,
        symbol: str,
        candles: pd.DataFrame,
        higher_tf_candles: dict[str, pd.DataFrame] | None = None,
    ) -> Signal | None:
        if len(candles) < self._slow_period + 1:
            return None

        fast = ta.sma(candles["close"], length=self._fast_period)
        slow = ta.sma(candles["close"], length=self._slow_period)

        side = detect_crossover(fast, slow)
        if side is None:
            return None

        if side == OrderSide.BUY and higher_tf_candles:
            if not mtf_trend_confirms_buy(
                higher_tf_candles, self._fast_period, self._slow_period, use_ema=False
            ):
                return None

        direction = "above" if side == OrderSide.BUY else "below"
        return Signal(
            symbol=symbol,
            side=side,
            strategy=self.name,
            reason=(
                f"fast SMA({self._fast_period})={fast.iloc[-1]:.2f} crossed {direction} "
                f"slow SMA({self._slow_period})={slow.iloc[-1]:.2f}"
            ),
        )
