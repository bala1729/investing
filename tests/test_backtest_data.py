"""Tests for building candles from Kraken's downloadable tick data.

Everything here builds tiny synthetic tick CSVs in tmp_path - nothing depends
on the multi-gigabyte real data directory, so the suite still runs in CI.
"""

from datetime import UTC, datetime
from pathlib import Path

import pandas as pd
import pytest

from src.backtest.data import (
    KRAKEN_INTERVAL_MINUTES,
    load_base_candles,
    load_candles,
    load_ticks_as_candles,
    resample_candles,
    to_kraken_symbol,
)

MINUTE = 60


def write_ticks(path: Path, ticks: list[tuple[int, float, float]]) -> Path:
    """Write raw (timestamp, price, volume) rows in Kraken's headerless CSV format."""
    path.write_text("\n".join(f"{ts},{price},{volume}" for ts, price, volume in ticks) + "\n")
    return path


def epoch(
    year: int, month: int, day: int, hour: int = 0, minute: int = 0, second: int = 0
) -> int:
    return int(datetime(year, month, day, hour, minute, second, tzinfo=UTC).timestamp())


class TestToKrakenSymbol:
    def test_maps_btc_to_kraken_xbt_ticker(self) -> None:
        assert to_kraken_symbol("BTC/USD") == "XBTUSD"

    def test_maps_doge_to_kraken_xdg_ticker(self) -> None:
        assert to_kraken_symbol("DOGE/EUR") == "XDGEUR"

    def test_passes_through_assets_without_an_alias(self) -> None:
        assert to_kraken_symbol("SOL/USD") == "SOLUSD"
        assert to_kraken_symbol("ETH/USD") == "ETHUSD"

    def test_uppercases_input(self) -> None:
        assert to_kraken_symbol("sol/usd") == "SOLUSD"


class TestKrakenIntervals:
    def test_two_week_interval_is_fifteen_days_not_fourteen(self) -> None:
        """Kraken's "2w" is really 21600 minutes = 15 days.

        Verified against its REST candles: consecutive 2w timestamps are
        spaced exactly 15 days apart. pandas' own "2W" offset is 14 days
        anchored on Sunday, so using it would silently produce candles that
        don't line up with the exchange's.
        """
        assert KRAKEN_INTERVAL_MINUTES["2w"] == 21600
        assert KRAKEN_INTERVAL_MINUTES["2w"] / 1440 == 15

    def test_one_week_interval_is_seven_days(self) -> None:
        assert KRAKEN_INTERVAL_MINUTES["1w"] == 10080
        assert KRAKEN_INTERVAL_MINUTES["1w"] / 1440 == 7


class TestLoadTicksAsCandles:
    def test_aggregates_ohlcv_within_a_bucket(self, tmp_path: Path) -> None:
        base = epoch(2024, 1, 1, 0, 0)
        path = write_ticks(
            tmp_path / "T.csv",
            [
                (base + 0, 100.0, 1.0),
                (base + 10, 105.0, 2.0),  # high
                (base + 20, 95.0, 3.0),  # low
                (base + 30, 102.0, 4.0),  # close
            ],
        )

        candles = load_ticks_as_candles(path, "1m")

        assert len(candles) == 1
        row = candles.iloc[0]
        assert row["open"] == 100.0
        assert row["high"] == 105.0
        assert row["low"] == 95.0
        assert row["close"] == 102.0
        assert row["volume"] == 10.0

    def test_splits_ticks_across_buckets(self, tmp_path: Path) -> None:
        base = epoch(2024, 1, 1, 0, 0)
        path = write_ticks(
            tmp_path / "T.csv",
            [(base, 100.0, 1.0), (base + MINUTE, 200.0, 2.0), (base + 2 * MINUTE, 300.0, 3.0)],
        )

        candles = load_ticks_as_candles(path, "1m")

        assert len(candles) == 3
        assert list(candles["close"]) == [100.0, 200.0, 300.0]

    def test_periods_without_trades_are_omitted_not_filled(self, tmp_path: Path) -> None:
        """A candle that never traded isn't a candle.

        Forward-filling would invent a price the market never printed, and
        indicators would then treat it as real data.
        """
        base = epoch(2024, 1, 1, 0, 0)
        path = write_ticks(
            tmp_path / "T.csv", [(base, 100.0, 1.0), (base + 5 * MINUTE, 110.0, 1.0)]
        )

        candles = load_ticks_as_candles(path, "1m")

        assert len(candles) == 2
        assert (candles.index[1] - candles.index[0]) == pd.Timedelta(minutes=5)

    def test_candle_split_across_chunk_boundary_is_merged(self, tmp_path: Path) -> None:
        """A chunk boundary can fall inside a candle.

        With chunked reading the same timestamp appears at the end of one
        chunk's output and the start of the next; without re-aggregating, the
        candle would be duplicated and its OHLCV split across both rows.
        """
        base = epoch(2024, 1, 1, 0, 0)
        path = write_ticks(
            tmp_path / "T.csv",
            [
                (base + 0, 100.0, 1.0),
                (base + 10, 105.0, 1.0),
                (base + 20, 95.0, 1.0),
                (base + 30, 102.0, 1.0),
            ],
        )

        chunked = load_ticks_as_candles(path, "1m", chunk_rows=2)
        whole = load_ticks_as_candles(path, "1m")

        assert len(chunked) == 1
        assert not chunked.index.duplicated().any()
        pd.testing.assert_frame_equal(chunked, whole)

    def test_buckets_align_to_the_epoch_grid_not_the_first_tick(self, tmp_path: Path) -> None:
        """Buckets must sit on the exchange's absolute grid.

        A tick at 00:04:30 belongs to the 00:00 five-minute candle, not to a
        candle that starts wherever the data happens to begin.
        """
        base = epoch(2024, 1, 1, 0, 4) + 30
        path = write_ticks(tmp_path / "T.csv", [(base, 100.0, 1.0)])

        candles = load_ticks_as_candles(path, "5m")

        assert candles.index[0] == pd.Timestamp("2024-01-01 00:00:00", tz="UTC")

    def test_weekly_buckets_land_on_krakens_thursday_anchor(self, tmp_path: Path) -> None:
        """Epoch-floor weekly bucketing anchors on Thursday (epoch 0 was a Thursday).

        This reproduces Kraken's own weekly candle timestamps; a Sunday- or
        Monday-anchored week would not.
        """
        path = write_ticks(tmp_path / "T.csv", [(epoch(2026, 8, 1, 12, 0), 100.0, 1.0)])

        candles = load_ticks_as_candles(path, "1w")

        assert candles.index[0] == pd.Timestamp("2026-07-30", tz="UTC")
        assert candles.index[0].day_name() == "Thursday"

    def test_two_week_buckets_match_krakens_fifteen_day_grid(self, tmp_path: Path) -> None:
        path = write_ticks(tmp_path / "T.csv", [(epoch(2026, 8, 1, 12, 0), 100.0, 1.0)])

        candles = load_ticks_as_candles(path, "2w")

        # Kraken's REST 2w candle covering this instant starts 2026-07-21
        assert candles.index[0] == pd.Timestamp("2026-07-21", tz="UTC")

    def test_empty_tick_file_produces_empty_candles(self, tmp_path: Path) -> None:
        path = tmp_path / "T.csv"
        path.write_text("")

        candles = load_ticks_as_candles(path, "1m")

        assert candles.empty
        assert list(candles.columns) == ["open", "high", "low", "close", "volume"]

    def test_rejects_unknown_timeframe(self, tmp_path: Path) -> None:
        path = write_ticks(tmp_path / "T.csv", [(epoch(2024, 1, 1), 100.0, 1.0)])

        with pytest.raises(ValueError, match="Unsupported timeframe"):
            load_ticks_as_candles(path, "3h")


class TestResampleCandles:
    def test_deriving_a_coarser_timeframe_matches_resampling_ticks_directly(
        self, tmp_path: Path
    ) -> None:
        """The whole caching strategy rests on this being exact."""
        base = epoch(2024, 1, 1, 0, 0)
        ticks = [(base + i * 20, 100.0 + (i % 7), 1.0) for i in range(60)]
        path = write_ticks(tmp_path / "T.csv", ticks)

        from_ticks = load_ticks_as_candles(path, "5m")
        from_minutes = resample_candles(load_ticks_as_candles(path, "1m"), "5m")

        pd.testing.assert_frame_equal(from_ticks, from_minutes)

    def test_empty_input_produces_empty_output(self) -> None:
        empty = resample_candles(pd.DataFrame(), "1h")

        assert empty.empty
        assert list(empty.columns) == ["open", "high", "low", "close", "volume"]


class TestLoadCandles:
    @pytest.fixture
    def data_dir(self, tmp_path: Path) -> Path:
        directory = tmp_path / "ticks"
        directory.mkdir()
        base = epoch(2024, 1, 1, 0, 0)
        write_ticks(
            directory / "SOLUSD.csv",
            [(base + i * MINUTE, 100.0 + i, 1.0) for i in range(120)],
        )
        return directory

    def test_output_shape_matches_ohlcv_to_dataframe(self, data_dir: Path) -> None:
        candles = load_candles(data_dir, "SOL/USD", "1h")

        assert list(candles.columns) == ["open", "high", "low", "close", "volume"]
        assert isinstance(candles.index, pd.DatetimeIndex)
        assert candles.index.tz is not None
        assert candles.index.is_monotonic_increasing

    def test_start_and_end_filter_the_window(self, data_dir: Path) -> None:
        window = load_candles(
            data_dir,
            "SOL/USD",
            "1m",
            start=datetime(2024, 1, 1, 0, 30, tzinfo=UTC),
            end=datetime(2024, 1, 1, 0, 59, tzinfo=UTC),
        )

        assert len(window) == 30
        assert window.index[0] == pd.Timestamp("2024-01-01 00:30", tz="UTC")
        assert window.index[-1] == pd.Timestamp("2024-01-01 00:59", tz="UTC")

    def test_accepts_naive_datetimes_as_utc(self, data_dir: Path) -> None:
        aware = load_candles(
            data_dir, "SOL/USD", "1m", start=datetime(2024, 1, 1, 1, 0, tzinfo=UTC)
        )
        naive = load_candles(data_dir, "SOL/USD", "1m", start=datetime(2024, 1, 1, 1, 0))

        pd.testing.assert_frame_equal(aware, naive)

    def test_window_outside_the_data_yields_no_candles(self, data_dir: Path) -> None:
        empty = load_candles(data_dir, "SOL/USD", "1h", start=datetime(2030, 1, 1, tzinfo=UTC))

        assert empty.empty

    def test_missing_symbol_file_names_the_expected_path(self, data_dir: Path) -> None:
        with pytest.raises(FileNotFoundError, match="XBTUSD.csv"):
            load_candles(data_dir, "BTC/USD", "1h")

    def test_cache_is_written_then_reused(self, data_dir: Path, tmp_path: Path) -> None:
        cache_dir = tmp_path / "cache"

        first = load_candles(data_dir, "SOL/USD", "1h", cache_dir=cache_dir)
        cache_file = cache_dir / "SOLUSD_1m.csv.gz"
        assert cache_file.exists()

        # Deleting the source proves the second read comes from the cache alone.
        (data_dir / "SOLUSD.csv").unlink()
        second = load_base_candles(data_dir, "SOL/USD", cache_dir=cache_dir)

        pd.testing.assert_frame_equal(first, resample_candles(second, "1h"))

    def test_cache_without_timezone_info_is_read_as_utc(
        self, data_dir: Path, tmp_path: Path
    ) -> None:
        """A cache whose timestamps carry no offset is still interpreted as UTC.

        Our own writer always emits tz-aware timestamps, but a hand-edited or
        older cache might not, and silently treating those as local time would
        shift every candle.
        """
        cache_dir = tmp_path / "cache"
        cache_dir.mkdir()
        expected = load_base_candles(data_dir, "SOL/USD", cache_dir=None)
        naive = expected.copy()
        naive.index = pd.DatetimeIndex(expected.index).tz_localize(None)
        naive.to_csv(cache_dir / "SOLUSD_1m.csv.gz")

        loaded = load_base_candles(data_dir, "SOL/USD", cache_dir=cache_dir)

        assert pd.DatetimeIndex(loaded.index).tz is not None
        pd.testing.assert_frame_equal(loaded, expected)

    def test_cached_candles_round_trip_unchanged(self, data_dir: Path, tmp_path: Path) -> None:
        cache_dir = tmp_path / "cache"

        uncached = load_base_candles(data_dir, "SOL/USD", cache_dir=None)
        load_base_candles(data_dir, "SOL/USD", cache_dir=cache_dir)  # writes cache
        cached = load_base_candles(data_dir, "SOL/USD", cache_dir=cache_dir)

        pd.testing.assert_frame_equal(uncached, cached)
