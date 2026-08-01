"""Base strategy interface and shared candle-data helpers."""

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Any

import pandas as pd

from src.exchange.executor import OrderSide


@dataclass(frozen=True)
class Signal:
    """A trading signal produced by a strategy."""

    symbol: str
    side: OrderSide
    strategy: str
    reason: str
    confidence: float = 1.0


def detect_crossover(fast: pd.Series, slow: pd.Series) -> OrderSide | None:
    """Detect whether `fast` crossed `slow` on the most recently completed bar.

    Compares the last two values of each series (both must already be aligned
    to the same candles). Returns OrderSide.BUY for a bullish cross (fast
    moves from at-or-below to above slow), OrderSide.SELL for a bearish cross
    (the reverse), or None if there's no fresh cross or not enough data yet
    (e.g. still inside an indicator's NaN warmup period).
    """
    if len(fast) < 2 or len(slow) < 2:
        return None

    prev_fast, prev_slow = fast.iloc[-2], slow.iloc[-2]
    curr_fast, curr_slow = fast.iloc[-1], slow.iloc[-1]

    if pd.isna(prev_fast) or pd.isna(prev_slow) or pd.isna(curr_fast) or pd.isna(curr_slow):
        return None

    if prev_fast <= prev_slow and curr_fast > curr_slow:
        return OrderSide.BUY
    if prev_fast >= prev_slow and curr_fast < curr_slow:
        return OrderSide.SELL
    return None


def ohlcv_to_dataframe(ohlcv: list[list[Any]]) -> pd.DataFrame:
    """Convert raw ccxt OHLCV rows into an indexed pandas DataFrame.

    Args:
        ohlcv: Rows of [timestamp_ms, open, high, low, close, volume], as
            returned by KrakenClient.fetch_ohlcv().

    Returns:
        DataFrame with open/high/low/close/volume columns, indexed by UTC
        timestamp, oldest candle first.
    """
    df = pd.DataFrame(ohlcv, columns=["timestamp", "open", "high", "low", "close", "volume"])
    df["timestamp"] = pd.to_datetime(df["timestamp"], unit="ms", utc=True)
    return df.set_index("timestamp")


class Strategy(ABC):
    """Base class for trading strategies.

    A strategy is a pure function from historical candle data to an optional
    trading signal — it does not fetch market data or execute orders itself.
    That keeps strategies trivially unit-testable and reusable for both the
    autonomous bot engine and backtesting.
    """

    def __init__(self, name: str | None = None) -> None:
        self.name = name or type(self).__name__

    @abstractmethod
    def generate_signal(self, symbol: str, candles: pd.DataFrame) -> Signal | None:
        """Analyze candle data and return a trading signal, or None to take no action.

        Args:
            symbol: Trading pair symbol the candles belong to.
            candles: OHLCV data indexed by timestamp, oldest first (see
                ohlcv_to_dataframe).

        Returns:
            A Signal to act on, or None if the strategy has no opinion right now.
        """
        raise NotImplementedError  # pragma: no cover
