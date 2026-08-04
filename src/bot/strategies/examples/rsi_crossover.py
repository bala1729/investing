"""Example strategy: RSI crossing its own moving average.

RSI (Relative Strength Index) is an oscillator bounded 0-100 that measures the
size of recent gains against recent losses. It is most often traded at its
extremes ("oversold below 30, overbought above 70"), but that use fights strong
trends - RSI can sit pinned above 70 for the entire length of a rally, so a
mechanical "sell at 70" exits the best moves early.

This strategy instead trades RSI against a moving average *of the RSI itself*,
the way TradingView's built-in RSI indicator draws it. Both lines live in the
same 0-100 space, so their crossover is a momentum-of-momentum signal: RSI
rising above its own average means buying pressure is accelerating relative to
its own recent norm, wherever the absolute level happens to be. That makes it
threshold-free and equally willing to enter at RSI 45 or RSI 75.

The trade-off is that it gives up RSI's mean-reversion edge: it will happily
buy an already-overbought market, and in a choppy range the two lines cross
constantly. Compare it against the price-based crossovers with
scripts/backtest.py rather than assuming an oscillator is inherently better.
"""

import pandas as pd
import pandas_ta as ta

from src.bot.strategies.base import (
    Signal,
    Strategy,
    detect_crossover,
    trend_is_bullish,
)
from src.exchange.executor import OrderSide


def rsi_and_signal_line(
    close: pd.Series, rsi_period: int, ma_period: int
) -> tuple[pd.Series, pd.Series]:
    """Compute the RSI and the simple moving average drawn over it.

    Shared by the entry logic and the higher-timeframe confirmation so both
    read "bullish" from exactly the same construction; returned as a pair
    rather than recomputed at each call site so the two can never drift apart.
    """
    rsi = ta.rsi(close, length=rsi_period)
    return rsi, ta.sma(rsi, length=ma_period)


def mtf_rsi_confirms_buy(
    higher_tf_candles: dict[str, pd.DataFrame], rsi_period: int, ma_period: int
) -> bool:
    """Whether every higher timeframe also shows RSI above its moving average.

    The other strategies gate entries with the shared mtf_trend_confirms_buy(),
    which compares a fast and a slow price EMA. This one deliberately confirms
    using its *own* signal definition instead: an RSI strategy has no natural
    fast/slow price-EMA pair, so borrowing one would smuggle two arbitrary
    periods into the filter and confirm against an indicator the strategy does
    not otherwise use. Asking "is RSI above its average on the higher timeframe
    too" keeps the confirmation in the same terms as the entry.

    Returns False on insufficient candles or during the indicator warmup, so an
    unconfirmable timeframe blocks the entry rather than silently passing it.
    """
    for candles in higher_tf_candles.values():
        if len(candles) < rsi_period + ma_period + 1:
            return False
        rsi, signal_line = rsi_and_signal_line(candles["close"], rsi_period, ma_period)
        if not trend_is_bullish(rsi, signal_line):
            return False
    return True


class RSICrossoverStrategy(Strategy):
    """Holds while RSI is above its moving average, sells when it crosses back below.

    Entry is *state*-based and exit is cross-based, for the reasons described in
    trend_is_bullish(). A buy is emitted on every bar where RSI sits above its
    average; callers ignore the repeats.

    Needs `rsi_period + ma_period + 1` candles before it can produce a signal:
    RSI itself is undefined for the first `rsi_period` bars, its moving average
    needs a further `ma_period` RSI values to smooth, and one extra bar on top
    so the previous bar's relationship can be compared against the current one.
    """

    def __init__(self, rsi_period: int = 14, ma_period: int = 14) -> None:
        if rsi_period <= 0:
            raise ValueError("rsi_period must be positive")
        if ma_period <= 0:
            raise ValueError("ma_period must be positive")
        super().__init__(name=f"rsi_crossover_{rsi_period}_{ma_period}")
        self._rsi_period = rsi_period
        self._ma_period = ma_period

    @property
    def _min_candles(self) -> int:
        return self._rsi_period + self._ma_period + 1

    def generate_signal(
        self,
        symbol: str,
        candles: pd.DataFrame,
        higher_tf_candles: dict[str, pd.DataFrame] | None = None,
    ) -> Signal | None:
        if len(candles) < self._min_candles:
            return None

        rsi, signal_line = rsi_and_signal_line(
            candles["close"], self._rsi_period, self._ma_period
        )

        if detect_crossover(rsi, signal_line) == OrderSide.SELL:
            return Signal(
                symbol=symbol,
                side=OrderSide.SELL,
                strategy=self.name,
                reason=(
                    f"RSI({self._rsi_period})={rsi.iloc[-1]:.2f} crossed below its "
                    f"SMA({self._ma_period})={signal_line.iloc[-1]:.2f}"
                ),
            )

        if not trend_is_bullish(rsi, signal_line):
            return None

        if higher_tf_candles and not mtf_rsi_confirms_buy(
            higher_tf_candles, self._rsi_period, self._ma_period
        ):
            return None

        return Signal(
            symbol=symbol,
            side=OrderSide.BUY,
            strategy=self.name,
            reason=(
                f"RSI({self._rsi_period})={rsi.iloc[-1]:.2f} is above its "
                f"SMA({self._ma_period})={signal_line.iloc[-1]:.2f}"
            ),
        )
