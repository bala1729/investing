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


def rsi_slope_is_positive(rsi: pd.Series) -> bool:
    """Whether RSI on the most recently completed bar is higher than the bar before.

    Guards a case trend_is_bullish() alone lets through: RSI can sit above its
    SMA (state: bullish) while already rolling over bar to bar. Real case that
    motivated this - a bot restart found the higher timeframe RSI still above
    its SMA but declining, and confirmed an entry moments before that timeframe
    turned. Requiring the slope to be positive too catches the decay a step
    earlier than waiting for the SMA cross.

    Returns False (not None) on insufficient data or a NaN bar, the same
    "unconfirmable blocks rather than passes" convention as the rest of this
    module.
    """
    if len(rsi) < 2:
        return False
    prev_rsi, curr_rsi = rsi.iloc[-2], rsi.iloc[-1]
    if pd.isna(prev_rsi) or pd.isna(curr_rsi):
        return False
    return bool(curr_rsi > prev_rsi)


def mtf_rsi_confirms_buy(
    higher_tf_candles: dict[str, pd.DataFrame], rsi_period: int, ma_period: int
) -> bool:
    """Whether every higher timeframe shows RSI above its moving average *and* rising.

    The other strategies gate entries with the shared mtf_trend_confirms_buy(),
    which compares a fast and a slow price EMA. This one deliberately confirms
    using its *own* signal definition instead: an RSI strategy has no natural
    fast/slow price-EMA pair, so borrowing one would smuggle two arbitrary
    periods into the filter and confirm against an indicator the strategy does
    not otherwise use. Asking "is RSI above its average on the higher timeframe
    too" keeps the confirmation in the same terms as the entry.

    The slope check (see rsi_slope_is_positive()) is layered on top of that
    state check: "above its SMA" alone still confirms a higher timeframe that
    has already turned down but hasn't crossed back below yet.

    Returns False on insufficient candles or during the indicator warmup, so an
    unconfirmable timeframe blocks the entry rather than silently passing it.
    """
    for candles in higher_tf_candles.values():
        if len(candles) < rsi_period + ma_period + 1:
            return False
        rsi, signal_line = rsi_and_signal_line(candles["close"], rsi_period, ma_period)
        if not trend_is_bullish(rsi, signal_line):
            return False
        if not rsi_slope_is_positive(rsi):
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

    def __init__(
        self, rsi_period: int = 14, ma_period: int = 14, exit_margin: float = 0.0
    ) -> None:
        if rsi_period <= 0:
            raise ValueError("rsi_period must be positive")
        if ma_period <= 0:
            raise ValueError("ma_period must be positive")
        if exit_margin < 0:
            raise ValueError("exit_margin cannot be negative")
        name = f"rsi_crossover_{rsi_period}_{ma_period}"
        if exit_margin > 0:
            name += f"_m{exit_margin:g}"
        super().__init__(name=name)
        self._rsi_period = rsi_period
        self._ma_period = ma_period
        self._exit_margin = exit_margin

    @property
    def _min_candles(self) -> int:
        return self._rsi_period + self._ma_period + 1

    def _exit_is_triggered(self, rsi: pd.Series, signal_line: pd.Series) -> bool:
        """Whether the exit condition holds on the most recently closed bar.

        With no margin this is the original fresh bearish cross, kept exactly so
        that `exit_margin=0` reproduces every previously logged result.

        With a margin it becomes a *state* check - "RSI is at least `margin`
        below its SMA" - rather than a cross. That change is forced, not
        stylistic: a margined cross would be unreachable. If RSI slips 0.05
        below the SMA (too shallow to act on) and then falls to 0.5 below on the
        next bar, detect_crossover() reports nothing, because the previous bar
        was already below. The position would be held all the way down with the
        exit permanently disarmed. Asking "is it far enough below now" instead
        fires on the bar the condition is actually met, which is the same reason
        entries are state-based (see trend_is_bullish()).

        Emitting SELL on every bar below the threshold is harmless: callers
        ignore a SELL when no position is open.
        """
        if len(rsi) == 0 or len(signal_line) == 0:
            return False
        if self._exit_margin <= 0:
            return detect_crossover(rsi, signal_line) == OrderSide.SELL
        current_rsi, current_signal = rsi.iloc[-1], signal_line.iloc[-1]
        if pd.isna(current_rsi) or pd.isna(current_signal):
            return False
        return bool(current_signal - current_rsi >= self._exit_margin)

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

        if self._exit_is_triggered(rsi, signal_line):
            return Signal(
                symbol=symbol,
                side=OrderSide.SELL,
                strategy=self.name,
                reason=(
                    f"RSI({self._rsi_period})={rsi.iloc[-1]:.2f} is at least "
                    f"{self._exit_margin:g} below its "
                    f"SMA({self._ma_period})={signal_line.iloc[-1]:.2f}"
                    if self._exit_margin > 0
                    else (
                        f"RSI({self._rsi_period})={rsi.iloc[-1]:.2f} crossed below its "
                        f"SMA({self._ma_period})={signal_line.iloc[-1]:.2f}"
                    )
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
