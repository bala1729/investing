"""Example strategy: simple moving-average crossover."""

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


class MovingAverageCrossoverStrategy(Strategy):
    """Holds while the fast SMA is above the slow SMA, sells when it crosses back below.

    Entry is *state*-based: any bar where the fast SMA sits above the slow one is
    a buy, not just the bar they cross on. Exit stays cross-based, since a
    position can only be closed once. See trend_is_bullish() for why - in short,
    a cross is a one-bar event, so anything that blocks the trade on that exact
    bar (higher-timeframe confirmation, a risk limit, no free balance) would
    otherwise forfeit the whole move that follows.

    A buy is therefore emitted on every bullish bar, and callers are expected to
    ignore the repeats: TradingEngine skips a BUY for a symbol it already holds,
    and Backtester does the same.

    Requires at least `slow_period + 1` candles - one more than the slow average
    needs, so the previous bar's relationship is available to detect the exit
    cross.
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

        if detect_crossover(fast, slow) == OrderSide.SELL:
            return Signal(
                symbol=symbol,
                side=OrderSide.SELL,
                strategy=self.name,
                reason=(
                    f"fast SMA({self._fast_period})={fast.iloc[-1]:.2f} crossed below "
                    f"slow SMA({self._slow_period})={slow.iloc[-1]:.2f}"
                ),
            )

        if not trend_is_bullish(fast, slow):
            return None

        if higher_tf_candles and not mtf_trend_confirms_buy(
            higher_tf_candles, self._fast_period, self._slow_period, use_ema=False
        ):
            return None

        return Signal(
            symbol=symbol,
            side=OrderSide.BUY,
            strategy=self.name,
            reason=(
                f"fast SMA({self._fast_period})={fast.iloc[-1]:.2f} is above "
                f"slow SMA({self._slow_period})={slow.iloc[-1]:.2f}"
            ),
        )
