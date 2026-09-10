"""Variant of RSICrossoverStrategy that exits off the entry timeframe's own
confirmation timeframe instead of its own RSI.

`RSICrossoverStrategy`'s exit (state-based once `exit_margin > 0`, cross-based
at the default 0) is computed from the *entry* timeframe's own RSI/SMA - a `4h`
bot exits on a `4h` signal, a `1h` bot on a `1h` signal. This variant keeps
that strategy's entry unchanged (same state-based entry, same
`mtf_rsi_confirms_buy` higher-timeframe confirmation across every timeframe
`MTF_CONFIRMATION_MAP` lists) but sources the *exit* from just the nearest
confirmation timeframe instead - the same one entry confirmation already
checks, not a separate mechanism: a `4h` entry exits on the daily RSI/SMA
(`MTF_CONFIRMATION_MAP["4h"] = ("1d",)`), a `1h` entry exits on the `4h`
RSI/SMA (`MTF_CONFIRMATION_MAP["1h"][0] == "4h"`). Hold through entry-timeframe
noise; only leave once the confirming timeframe itself has turned.
"""

import pandas as pd

from src.bot.strategies.base import MTF_CONFIRMATION_MAP, Signal, Strategy, trend_is_bullish
from src.bot.strategies.examples.rsi_crossover import mtf_rsi_confirms_buy, rsi_and_signal_line
from src.exchange.executor import OrderSide


class RSIConfirmationExitStrategy(Strategy):
    """Enters like RSICrossoverStrategy; exits only when the entry timeframe's
    *nearest confirmation timeframe* (per `MTF_CONFIRMATION_MAP`) is no longer
    above its own SMA.

    `entry_timeframe` is named explicitly, not inferred from `higher_tf_candles`
    at call time - relying on dict key order would be an implicit, easy-to-break
    contract; naming it explicitly makes which timeframe drives the exit an
    obvious part of how the strategy is configured. Defaults to `"4h"` (this
    account's current live entry timeframe) only so every strategy in the
    registry stays constructible with no arguments, matching every other entry
    there - a caller running a different entry timeframe must still pass it
    explicitly, the same way `scripts/run_bot.py`/`scripts/backtest.py` always
    thread their own `--timeframe` straight through rather than relying on the
    default. Whatever value is used has to be a key `MTF_CONFIRMATION_MAP` maps
    to at least one higher timeframe, since without one there's nothing for
    this variant to exit on at all - checked eagerly, in the constructor, not
    the first time a signal is generated.

    Requires `higher_tf_candles[<exit timeframe>]` to actually exit a position:
    with that data missing, a position that has entered can never leave (the
    exit condition is undecidable, so nothing is emitted - never mistaking
    "unknown" for "true"). Every live bot already supplies every timeframe
    `MTF_CONFIRMATION_MAP` lists (that's what entry confirmation itself needs
    too), so this isn't a new operational requirement; it matters primarily
    for backtests or other callers that might omit `higher_tf_candles`.

    No `exit_margin`: the confirmation timeframe's state check (RSI at or
    below its SMA) is the exit condition directly, not a cross - once sold,
    repeated identical signals on subsequent bars are harmless (ignored by any
    caller that tracks open-position state), the same reasoning
    `RSICrossoverStrategy` documents for its own state-based entry.
    """

    def __init__(
        self,
        entry_timeframe: str = "4h",
        rsi_period: int = 14,
        ma_period: int = 14,
    ) -> None:
        if rsi_period <= 0:
            raise ValueError("rsi_period must be positive")
        if ma_period <= 0:
            raise ValueError("ma_period must be positive")
        higher = MTF_CONFIRMATION_MAP.get(entry_timeframe)
        if not higher:
            raise ValueError(
                f"entry_timeframe={entry_timeframe!r} has no higher timeframe in "
                "MTF_CONFIRMATION_MAP - this strategy needs one to exit on"
            )
        super().__init__(
            name=f"rsi_confirmation_exit_{entry_timeframe}_{rsi_period}_{ma_period}"
        )
        self._rsi_period = rsi_period
        self._ma_period = ma_period
        self._exit_timeframe = higher[0]

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

        exit_candles = (higher_tf_candles or {}).get(self._exit_timeframe)
        if exit_candles is not None and len(exit_candles) >= self._min_candles:
            exit_rsi, exit_sma = rsi_and_signal_line(
                exit_candles["close"], self._rsi_period, self._ma_period
            )
            if not pd.isna(exit_rsi.iloc[-1]) and not pd.isna(exit_sma.iloc[-1]):
                if not trend_is_bullish(exit_rsi, exit_sma):
                    return Signal(
                        symbol=symbol,
                        side=OrderSide.SELL,
                        strategy=self.name,
                        reason=(
                            f"{self._exit_timeframe} RSI({self._rsi_period})="
                            f"{exit_rsi.iloc[-1]:.2f} is at or below its "
                            f"{self._exit_timeframe} SMA({self._ma_period})="
                            f"{exit_sma.iloc[-1]:.2f}"
                        ),
                    )

        rsi, signal_line = rsi_and_signal_line(
            candles["close"], self._rsi_period, self._ma_period
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
