"""Load historical candles from Kraken's downloadable tick data.

Kraken's public OHLC endpoint caps at ~720 candles per request regardless of
the limit asked for, which makes long backtests impossible and short ones
irreproducible (it always returns the *most recent* candles, so the same
command run twice covers different windows). Kraken separately publishes the
full trade history as downloadable CSVs; this module turns those into candles.

The files are tick-level trades, not candles - headerless CSV rows of
`timestamp,price,volume` - so candles are resampled locally. Output matches
ohlcv_to_dataframe() exactly (UTC DatetimeIndex, open/high/low/close/volume,
oldest first) so it drops straight into Backtester.run().
"""

from datetime import datetime
from pathlib import Path
from typing import Any

import pandas as pd

#: Kraken's OHLC interval for each timeframe, in minutes.
#:
#: Note "2w" is 21600 minutes - *15 days*, not 14. This is Kraken's actual
#: interval, verified against its REST candles, and it matters: pandas'
#: "2W" offset is 14 days anchored on Sunday and would silently produce
#: candles that don't line up with the exchange's.
KRAKEN_INTERVAL_MINUTES: dict[str, int] = {
    "1m": 1,
    "5m": 5,
    "15m": 15,
    "30m": 30,
    "1h": 60,
    "4h": 240,
    "1d": 1440,
    "1w": 10080,
    "2w": 21600,
}

#: Kraken's own ticker codes for assets whose common name differs.
_KRAKEN_ASSET_ALIASES: dict[str, str] = {
    "BTC": "XBT",
    "DOGE": "XDG",
}

_TICK_COLUMNS = ["timestamp", "price", "volume"]
_CANDLE_COLUMNS = ["open", "high", "low", "close", "volume"]

#: Rows per chunk when streaming a tick file. Tuned for files up to ~130M rows
#: (BTC) on a 16GB machine - large enough that the per-chunk resample overhead
#: stays negligible, small enough that a chunk's DataFrame stays well under a GB.
_CHUNK_ROWS = 5_000_000

#: Candles are cached at this timeframe; every coarser one derives from it.
_CACHE_TIMEFRAME = "1m"


def to_kraken_symbol(symbol: str) -> str:
    """Convert a ccxt-style pair to Kraken's data-file naming.

    >>> to_kraken_symbol("BTC/USD")
    'XBTUSD'
    """
    parts = symbol.split("/")
    return "".join(_KRAKEN_ASSET_ALIASES.get(part.upper(), part.upper()) for part in parts)


def _pandas_freq(timeframe: str) -> str:
    """Kraken's interval for `timeframe` as a pandas fixed-frequency string."""
    if timeframe not in KRAKEN_INTERVAL_MINUTES:
        raise ValueError(
            f"Unsupported timeframe {timeframe!r}. "
            f"Valid: {', '.join(KRAKEN_INTERVAL_MINUTES)}"
        )
    return f"{KRAKEN_INTERVAL_MINUTES[timeframe]}min"


def _aggregate_candles(grouped: Any) -> pd.DataFrame:
    """Apply the OHLCV aggregation to an already-grouped/resampled frame.

    Typed loosely because pandas' Resampler and DataFrameGroupBy don't share a
    usable common base, and both support exactly the .agg() call used here.
    """
    aggregated: pd.DataFrame = grouped.agg(
        open=("open", "first"),
        high=("high", "max"),
        low=("low", "min"),
        close=("close", "last"),
        volume=("volume", "sum"),
    )
    return aggregated


def _ticks_to_candles(ticks: pd.DataFrame, timeframe: str) -> pd.DataFrame:
    """Resample one chunk of raw ticks into candles.

    `origin="epoch"` is essential: it buckets on the same absolute grid the
    exchange uses (floor(timestamp / interval)), rather than pandas' default
    of anchoring to the first observation or the start of its day.
    """
    indexed = ticks.set_index(pd.to_datetime(ticks["timestamp"], unit="s", utc=True))
    resampled = indexed.resample(_pandas_freq(timeframe), origin="epoch")
    candles = resampled.agg(
        open=("price", "first"),
        high=("price", "max"),
        low=("price", "min"),
        close=("price", "last"),
        volume=("volume", "sum"),
    )
    # Periods with no trades resample to all-NaN rows; a candle that never
    # traded isn't a candle, so drop them rather than forward-filling a price
    # the market never printed.
    return candles.dropna(subset=["open"])


def load_ticks_as_candles(
    csv_path: Path, timeframe: str, chunk_rows: int = _CHUNK_ROWS
) -> pd.DataFrame:
    """Stream a Kraken tick CSV and resample it into candles.

    Read in chunks because the largest of these files is ~130M rows; holding
    the whole tick history in memory to build candles that are three orders of
    magnitude smaller is unnecessary.
    """
    partials = [
        _ticks_to_candles(chunk, timeframe)
        for chunk in pd.read_csv(
            csv_path,
            header=None,
            names=_TICK_COLUMNS,
            dtype={"timestamp": "int64", "price": "float64", "volume": "float64"},
            chunksize=chunk_rows,
        )
    ]
    # read_csv always yields at least one chunk (empty for an empty file), so
    # partials is never empty and concat is always safe.
    combined = pd.concat(partials)
    # A chunk boundary can fall inside a candle, so the same timestamp may
    # appear at the end of one chunk's output and the start of the next.
    # Re-aggregating merges those without disturbing candles that only ever
    # appeared once.
    return _normalized(_aggregate_candles(combined.groupby(level=0)))


def resample_candles(candles: pd.DataFrame, timeframe: str) -> pd.DataFrame:
    """Aggregate finer candles up into a coarser timeframe.

    Exact, not approximate: a coarse candle's open/high/low/close/volume are
    recoverable from its constituent finer candles, so deriving 1h from cached
    1m data gives the same result as resampling the underlying ticks to 1h.
    """
    if candles.empty:
        return _empty_candles()
    resampled = candles.resample(_pandas_freq(timeframe), origin="epoch")
    return _normalized(_aggregate_candles(resampled).dropna(subset=["open"]))


def _normalized(candles: pd.DataFrame) -> pd.DataFrame:
    """Give candles a canonical index so results don't depend on how they were built.

    resample() stamps a freq on the index when it happens to see a single
    contiguous block, but the concat/groupby path (used once the input spans
    more than one chunk) does not - so identical data could come back with
    different index metadata purely as an artifact of file size. Empty periods
    are dropped anyway, which makes the index genuinely irregular, so a freq
    would be a lie either way.
    """
    # Rebuilding from the raw values is what drops the freq - it can't be
    # unset in place, since the property is read-only.
    source = pd.DatetimeIndex(candles.index)
    candles.index = pd.DatetimeIndex(source.to_numpy(), tz="UTC", name="timestamp")
    return candles


def _empty_candles() -> pd.DataFrame:
    empty = pd.DataFrame(
        {column: pd.Series(dtype="float64") for column in _CANDLE_COLUMNS},
        index=pd.DatetimeIndex([], tz="UTC", name="timestamp"),
    )
    return empty


def tick_file_for(data_dir: Path, symbol: str) -> Path:
    """Path of the tick CSV for `symbol` inside `data_dir`."""
    return data_dir / f"{to_kraken_symbol(symbol)}.csv"


def _cache_file_for(cache_dir: Path, symbol: str) -> Path:
    return cache_dir / f"{to_kraken_symbol(symbol)}_{_CACHE_TIMEFRAME}.csv.gz"


def load_base_candles(data_dir: Path, symbol: str, cache_dir: Path | None = None) -> pd.DataFrame:
    """Load (and cache) the 1-minute candles for `symbol`.

    Resampling the full tick history takes seconds, but every timeframe would
    otherwise pay that cost again, so the 1-minute result is cached and each
    tick file is read at most once.
    """
    # Consult the cache before the source file: once candles are cached the
    # multi-gigabyte tick CSV is no longer needed, so requiring it would force
    # people to keep 45GB around to re-run a backtest.
    cache_path = _cache_file_for(cache_dir, symbol) if cache_dir is not None else None
    if cache_path is not None and cache_path.exists():
        cached = pd.read_csv(cache_path, index_col="timestamp", parse_dates=["timestamp"])
        cached.index = pd.DatetimeIndex(cached.index)
        if cached.index.tz is None:
            cached.index = cached.index.tz_localize("UTC")
        return _normalized(cached)

    tick_path = tick_file_for(data_dir, symbol)
    if not tick_path.exists():
        raise FileNotFoundError(
            f"No Kraken tick data for {symbol} at {tick_path}. "
            f"Check --data-dir, or use --data-source rest to fetch from the API instead."
        )

    candles = load_ticks_as_candles(tick_path, _CACHE_TIMEFRAME)
    if cache_path is not None:
        cache_path.parent.mkdir(parents=True, exist_ok=True)
        candles.to_csv(cache_path)
    return candles


def load_candles(
    data_dir: Path,
    symbol: str,
    timeframe: str,
    start: datetime | None = None,
    end: datetime | None = None,
    cache_dir: Path | None = None,
) -> pd.DataFrame:
    """Load historical candles for `symbol` at `timeframe` from local tick data.

    Args:
        data_dir: Directory holding Kraken's downloaded tick CSVs.
        symbol: ccxt-style pair, e.g. "BTC/USD".
        timeframe: One of KRAKEN_INTERVAL_MINUTES.
        start: Drop candles before this instant (inclusive) if given.
        end: Drop candles after this instant (inclusive) if given.
        cache_dir: Where to cache resampled 1-minute candles. No caching if None.

    Returns:
        OHLCV candles indexed by UTC timestamp, oldest first - the same shape
        ohlcv_to_dataframe() produces for REST-fetched data.
    """
    base = load_base_candles(data_dir, symbol, cache_dir=cache_dir)
    candles = base if timeframe == _CACHE_TIMEFRAME else resample_candles(base, timeframe)

    if start is not None:
        candles = candles[candles.index >= _as_utc(start)]
    if end is not None:
        candles = candles[candles.index <= _as_utc(end)]
    return candles


def _as_utc(moment: datetime) -> pd.Timestamp:
    """Normalize a datetime to a UTC Timestamp, whether or not it carries a tz.

    Passing tz= to pd.Timestamp() raises when the input is already tz-aware, so
    naive inputs get localized and aware ones get converted.
    """
    timestamp = pd.Timestamp(moment)
    if timestamp.tz is None:
        return timestamp.tz_localize("UTC")
    return timestamp.tz_convert("UTC")
