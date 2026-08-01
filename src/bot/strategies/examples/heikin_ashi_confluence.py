"""Example strategy: EMA crossover on Heikin Ashi candles, confirmed by MACD/RSI/Bollinger Bands."""

import pandas as pd
import pandas_ta as ta

from src.bot.strategies.base import Signal, Strategy, detect_crossover, mtf_trend_confirms_buy
from src.exchange.executor import OrderSide


def _first_column_starting_with(df: pd.DataFrame, prefix: str) -> pd.Series:
    """Return the first column whose name starts with `prefix`.

    pandas_ta's exact column suffixes vary with the parameters passed (e.g.
    Bollinger Band columns repeat the std multiplier: "BBU_20_2.0_2.0") -
    matching by prefix instead of a hardcoded full name avoids depending on
    that exact, version-sensitive formatting.
    """
    return df[next(c for c in df.columns if c.startswith(prefix))]


def _confirms_buy(
    macd_line: float,
    macd_signal: float,
    rsi: float,
    rsi_overbought: float,
    close: float,
    bb_upper: float,
) -> bool:
    """Whether MACD, RSI, and Bollinger Bands all confirm a bullish EMA crossover.

    A pure function of the already-computed scalar values (rather than
    inlined in generate_signal) specifically so each condition is directly
    unit-testable without needing to construct a price series that isolates
    one indicator - these indicators are naturally correlated (e.g. RSI
    overbought and price-above-upper-band tend to co-occur), so hand-crafting
    real market data that trips exactly one filter at a time isn't practical.
    """
    macd_bullish = macd_line > macd_signal
    not_overbought = rsi < rsi_overbought
    not_extended = close < bb_upper
    return macd_bullish and not_overbought and not_extended


class HeikinAshiConfluenceStrategy(Strategy):
    """Buys on an EMA crossover confirmed by MACD, RSI, and Bollinger Bands - all on
    Heikin Ashi candles rather than raw OHLC, which smooths out some of the
    noise a fast EMA pair would otherwise react to.

    Entry requires confluence - the trigger (EMA crossover) plus three
    independent filters all agreeing on the same bar:
      - EMA(fast_period) crosses above EMA(slow_period) (the trigger)
      - MACD line is above its signal line (momentum confirms the trend)
      - RSI is below the overbought threshold (not already extended)
      - close is below the upper Bollinger Band (not already outside the
        normal volatility range)

    Exit is intentionally NOT filtered: a bearish EMA crossover alone closes
    the position, since an exit should never be harder to trigger than an
    entry (risk management protects capital, it shouldn't trap you in a
    losing position waiting for MACD/RSI/BB to also agree).
    """

    def __init__(
        self,
        fast_period: int = 5,
        slow_period: int = 10,
        macd_fast: int = 12,
        macd_slow: int = 26,
        macd_signal: int = 9,
        rsi_period: int = 14,
        rsi_overbought: float = 70.0,
        bb_period: int = 20,
        bb_std: float = 2.0,
    ) -> None:
        if fast_period >= slow_period:
            raise ValueError("fast_period must be less than slow_period")
        if macd_fast >= macd_slow:
            raise ValueError("macd_fast must be less than macd_slow")
        if not (0 < rsi_overbought <= 100):
            raise ValueError("rsi_overbought must be between 0 (exclusive) and 100")
        super().__init__(name=f"ha_confluence_{fast_period}_{slow_period}")
        self._fast_period = fast_period
        self._slow_period = slow_period
        self._macd_fast = macd_fast
        self._macd_slow = macd_slow
        self._macd_signal = macd_signal
        self._rsi_period = rsi_period
        self._rsi_overbought = rsi_overbought
        self._bb_period = bb_period
        self._bb_std = bb_std

    @property
    def _min_candles(self) -> int:
        warmup = max(
            self._slow_period,
            self._macd_slow + self._macd_signal,
            self._rsi_period,
            self._bb_period,
        )
        return warmup + 1

    def generate_signal(
        self,
        symbol: str,
        candles: pd.DataFrame,
        higher_tf_candles: dict[str, pd.DataFrame] | None = None,
    ) -> Signal | None:
        if len(candles) < self._min_candles:
            return None

        ha = ta.ha(candles["open"], candles["high"], candles["low"], candles["close"])
        ha_close = ha["HA_close"]

        ema_fast = ta.ema(ha_close, length=self._fast_period)
        ema_slow = ta.ema(ha_close, length=self._slow_period)
        side = detect_crossover(ema_fast, ema_slow)
        if side is None:
            return None

        if side == OrderSide.SELL:
            return Signal(
                symbol=symbol,
                side=OrderSide.SELL,
                strategy=self.name,
                reason=(
                    f"HA EMA({self._fast_period})={ema_fast.iloc[-1]:.2f} crossed below "
                    f"HA EMA({self._slow_period})={ema_slow.iloc[-1]:.2f}"
                ),
            )

        macd_df = ta.macd(
            ha_close, fast=self._macd_fast, slow=self._macd_slow, signal=self._macd_signal
        )
        macd_line = _first_column_starting_with(macd_df, "MACD_")
        macd_signal_line = _first_column_starting_with(macd_df, "MACDs_")

        rsi = ta.rsi(ha_close, length=self._rsi_period)

        bbands = ta.bbands(
            ha_close, length=self._bb_period, lower_std=self._bb_std, upper_std=self._bb_std
        )
        bb_upper = _first_column_starting_with(bbands, "BBU_")

        if not _confirms_buy(
            macd_line=macd_line.iloc[-1],
            macd_signal=macd_signal_line.iloc[-1],
            rsi=rsi.iloc[-1],
            rsi_overbought=self._rsi_overbought,
            close=ha_close.iloc[-1],
            bb_upper=bb_upper.iloc[-1],
        ):
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
                f"HA EMA({self._fast_period}) crossed above HA EMA({self._slow_period}), "
                f"confirmed by MACD bullish ({macd_line.iloc[-1]:.2f} > "
                f"{macd_signal_line.iloc[-1]:.2f}), RSI {rsi.iloc[-1]:.1f} < "
                f"{self._rsi_overbought}, and HA close below upper Bollinger Band "
                f"{bb_upper.iloc[-1]:.2f}"
            ),
        )
