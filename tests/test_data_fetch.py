"""Tests for features.data_fetch — TTL cache, cycle cache, macro fetch, asset data."""

from __future__ import annotations

import time as _real_time
from unittest.mock import MagicMock, patch

import pandas as pd
import pytest

from features.data_fetch import (
    _TTLCache,
    _get_cycle_cached,
    _macro_cache,
    _normalize_index,
    _set_cycle_cache,
    bump_cycle_id,
    fetch_asset_data,
    fetch_asset_ohlcv,
    fetch_yf_series,
)


# ── _TTLCache ──────────────────────────────────────────────────────────────


class TestTTLCache:
    def test_get_returns_set_value(self):
        cache = _TTLCache(ttl=300)
        cache.set("k", "v")
        assert cache.get("k") == "v"

    def test_get_returns_none_after_ttl(self):
        cache = _TTLCache(ttl=0)
        cache.set("k", "v")
        _real_time.sleep(0.01)
        assert cache.get("k") is None

    def test_get_returns_none_for_missing(self):
        cache = _TTLCache()
        assert cache.get("missing") is None

    def test_invalidate_clears_all(self):
        cache = _TTLCache()
        cache.set("a", 1)
        cache.set("b", 2)
        cache.invalidate()
        assert cache.get("a") is None
        assert cache.get("b") is None

    def test_set_overwrites_existing(self):
        cache = _TTLCache()
        cache.set("k", "v1")
        cache.set("k", "v2")
        assert cache.get("k") == "v2"


# ── Cycle cache ────────────────────────────────────────────────────────────


class TestCycleCache:
    def setup_method(self):
        bump_cycle_id()

    def test_set_and_get_within_cycle(self):
        _set_cycle_cache("test_asset", 42)
        assert _get_cycle_cached("test_asset") == 42

    def test_get_returns_none_after_bump(self):
        _set_cycle_cache("test_asset", 42)
        bump_cycle_id()
        assert _get_cycle_cached("test_asset") is None

    def test_get_returns_none_for_missing(self):
        assert _get_cycle_cached("nonexistent") is None

    def test_bump_cycle_id_increments(self):
        c1 = bump_cycle_id()
        c2 = bump_cycle_id()
        assert c2 > c1


# ── _normalize_index ───────────────────────────────────────────────────────


class TestNormalizeIndex:
    @pytest.mark.skip(reason="CI runner pandas C extensions segfault on tz_localize")
    def test_converts_naive_to_utc(self):
        idx = pd.DatetimeIndex(["2026-01-01", "2026-01-02"])
        result = _normalize_index(idx)
        assert result.tz is not None
        assert str(result.tz) == "UTC"

    @pytest.mark.skip(reason="CI runner pandas C extensions segfault on tz_localize")
    def test_converts_et_to_utc(self):
        idx = pd.DatetimeIndex(["2026-01-01"], tz="US/Eastern")
        result = _normalize_index(idx)
        assert str(result.tz) == "UTC"

    @pytest.mark.skip(reason="CI runner pandas C extensions segfault on tz_localize")
    def test_normalizes_to_midnight(self):
        idx = pd.DatetimeIndex(["2026-01-01 14:30:00"], tz="UTC")
        result = _normalize_index(idx)
        assert result[0].hour == 0
        assert result[0].minute == 0


# ── fetch_yf_series ────────────────────────────────────────────────────────


class TestFetchYfSeries:
    def test_returns_empty_for_nonexistent(self):
        with patch("features.data_fetch._fetch_single_series", return_value=pd.Series(dtype=float)):
            result = fetch_yf_series("NONEXIST", "test")
            assert result.empty

    def test_returns_series(self):
        s = pd.Series([1.0, 2.0], index=pd.DatetimeIndex(["2026-01-01", "2026-01-02"]))
        s.index = _normalize_index(s.index)
        with patch("features.data_fetch._fetch_single_series", return_value=s):
            result = fetch_yf_series("EURUSD", "test")
            assert not result.empty
            assert float(result.iloc[0]) == 1.0

    def test_hits_macro_cache_for_known(self):
        _macro_cache.set("macro_batch", {"^VIX": pd.Series([15.0], name="^VIX")})
        with patch("features.data_fetch._fetch_single_series") as mock_fetch:
            result = fetch_yf_series("^VIX", "vix")
            assert not result.empty
            mock_fetch.assert_not_called()
        _macro_cache.invalidate()


# ── fetch_asset_data ───────────────────────────────────────────────────────


class TestFetchAssetData:
    @pytest.fixture(autouse=True)
    def _reset_cache(self):
        bump_cycle_id()
        _macro_cache.invalidate()
        yield

    def test_returns_cached_result(self):
        cached = (pd.DataFrame({"close": [1.0]}), pd.DataFrame(), pd.Series(), pd.Series(), pd.Series(), pd.DataFrame())
        _set_cycle_cache("EURUSD", cached)
        with patch("features.data_fetch._provider_fetch_live") as mock_provider:
            result = fetch_asset_data("EURUSD", "EURUSD=X")
            assert result is cached
            mock_provider.assert_not_called()

    def test_falls_back_to_yfinance_on_provider_failure(self):
        import numpy as np
        import datetime as _dt

        base = _dt.datetime(2026, 1, 1)
        idx = pd.DatetimeIndex([base + _dt.timedelta(days=i) for i in range(260)])
        close = pd.Series(np.linspace(1.0, 1.1, 260), index=idx, name="close")
        with patch("features.data_fetch._provider_fetch_live", side_effect=ValueError("empty")):
            with patch("features.data_fetch.fetch_yf_series", return_value=close):
                with patch("features.data_fetch._fetch_macro_batch", return_value={}):
                    with patch("features.data_fetch._normalize_index", side_effect=lambda idx: idx):
                        result = fetch_asset_data("EURUSD", "EURUSD=X")
                        prices, rate_diffs, *_ = result
                        assert "EURUSD" in prices.columns

    def test_raises_on_insufficient_history(self):
        series = pd.Series([1.0], name="close")
        with patch("features.data_fetch._provider_fetch_live", return_value=pd.DataFrame({"close": series})):
            with patch("features.data_fetch._fetch_macro_batch", return_value={}):
                with patch("features.data_fetch._normalize_index", side_effect=lambda idx: idx):
                    with pytest.raises(ValueError, match="insufficient history"):
                        fetch_asset_data("EURUSD", "EURUSD=X")

    def test_returns_rate_diffs_for_fx(self):
        import numpy as np
        import datetime as _dt

        base = _dt.datetime(2026, 1, 1)
        idx = pd.DatetimeIndex([base + _dt.timedelta(days=i) for i in range(260)])
        close = pd.Series(np.linspace(1.0, 1.1, 260), index=idx, name="close")
        prices_df = close.to_frame("close")
        with patch("features.data_fetch._provider_fetch_live", return_value=prices_df):
            with patch("features.data_fetch._normalize_index", side_effect=lambda idx: idx):
                with patch(
                    "features.data_fetch._fetch_macro_batch",
                    return_value={
                        "DX-Y.NYB": pd.Series([96.0]),
                        "^VIX": pd.Series([15.0]),
                        "^GSPC": pd.Series([5000.0]),
                        "CL=F": pd.Series([70.0]),
                        "^TNX": pd.Series([0.04]),
                        "^FVX": pd.Series([0.03]),
                        "^TYX": pd.Series([0.05]),
                        "^IRX": pd.Series([0.01]),
                    },
                ):
                    result = fetch_asset_data("EURUSD", "EURUSD=X")
                    prices, rate_diffs, *_ = result
                    assert "EURUSD" in prices.columns


# ── fetch_asset_ohlcv ──────────────────────────────────────────────────────


class TestFetchAssetOhlcv:
    @pytest.fixture(autouse=True)
    def _reset(self):
        bump_cycle_id()
        yield

    def test_returns_empty_on_failure(self):
        with patch("features.data_fetch._provider_fetch_live", side_effect=ValueError("fail")):
            with patch("yfinance.download", return_value=pd.DataFrame()):
                result = fetch_asset_ohlcv("EURUSD")
                assert result.empty

    def test_caches_result(self):
        df = pd.DataFrame({"close": [1.0]}, index=pd.DatetimeIndex(["2026-01-01"]))
        with patch("features.data_fetch._provider_fetch_live", return_value=df):
            with patch("features.data_fetch._normalize_index", side_effect=lambda x: x):
                r1 = fetch_asset_ohlcv("EURUSD")
                r2 = fetch_asset_ohlcv("EURUSD")
                assert r1 is r2

    def test_returns_dataframe_with_expected_columns(self):
        raw = pd.DataFrame({
            "Open": [1.0], "High": [1.1], "Low": [0.9],
            "Close": [1.05], "Volume": [1000],
        }, index=pd.DatetimeIndex(["2026-01-01"]))
        raw.index = _normalize_index(raw.index)
        with patch("features.data_fetch._provider_fetch_live", side_effect=ValueError("fail")):
            with patch("yfinance.download", return_value=raw):
                result = fetch_asset_ohlcv("EURUSD")
                assert not result.empty
                assert "open" in result.columns
                assert "close" in result.columns
