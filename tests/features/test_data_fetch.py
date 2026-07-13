"""Tests for features.data_fetch — TTL cache, cycle cache, macro fetch, asset data."""

from __future__ import annotations

import time as _real_time
from unittest.mock import patch

import numpy as np
import pandas as pd
import pytest

from features.data_fetch import (
    _TTLCache,
    _fetch_fred_series,
    _fetch_macro_batch,
    _fetch_single_series,
    _get_cycle_cached,
    _KNOWN_CURRENCIES,
    _macro_cache,
    _normalize_index,
    _set_cycle_cache,
    _ZERO_RATE_ASSETS,
    bump_cycle_id,
    CURRENCY_YIELD_TICKERS,
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
    def test_converts_naive_to_utc(self):
        idx = pd.to_datetime(pd.Index(["2026-01-01", "2026-01-02"]))
        result = _normalize_index(idx)
        assert result.tz is not None
        assert str(result.tz) == "UTC"

    def test_converts_et_to_utc(self):
        idx = pd.to_datetime(pd.Index(["2026-01-01"]), utc=True).tz_convert("US/Eastern")
        result = _normalize_index(idx)
        assert str(result.tz) == "UTC"

    def test_normalizes_to_midnight(self):
        idx = pd.to_datetime(pd.Index(["2026-01-01 14:30:00"]), utc=True)
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


# ── _fetch_fred_series ──────────────────────────────────────────────────────


class TestFetchFredSeries:
    CSV_OK = b"observation_date,value\n2020-01-02,1.50\n2020-01-03,1.52\n"

    def test_parses_csv_successfully(self):
        with patch("urllib.request.urlopen") as mock_urlopen:
            mock_urlopen.return_value.__enter__.return_value.read.return_value = self.CSV_OK
            result = _fetch_fred_series("^TNX")
        assert not result.empty
        assert len(result) == 2
        assert result.iloc[0] == 1.50

    def test_returns_empty_for_unknown_ticker(self):
        result = _fetch_fred_series("NONEXIST")
        assert result.empty

    def test_returns_empty_on_network_error(self):
        with patch("urllib.request.urlopen", side_effect=OSError("timeout")):
            result = _fetch_fred_series("^TNX")
        assert result.empty

    def test_no_longer_filters_before_2020(self):
        # Previously FRED responses were truncated to >=2020-01-01, capping
        # macro history at ~6y. Dropped that constraint so retrain + walk-
        # forward can use the same wide range the live engine sees. Both
        # dates now get through.
        csv = b"observation_date,value\n2019-12-01,1.00\n2020-01-02,1.50\n"
        with patch("urllib.request.urlopen") as mock_urlopen:
            mock_urlopen.return_value.__enter__.return_value.read.return_value = csv
            result = _fetch_fred_series("^TNX")
        assert len(result) == 2
        assert result.iloc[0] == 1.0
        assert result.iloc[-1] == 1.5

    def test_skips_empty_rows(self):
        csv = b"observation_date,value\n2020-01-02,1.50\n2020-01-03,\n2020-01-04,1.55\n"
        with patch("urllib.request.urlopen") as mock_urlopen:
            mock_urlopen.return_value.__enter__.return_value.read.return_value = csv
            result = _fetch_fred_series("^TNX")
        assert not result.empty
        assert len(result) == 2  # empty value skipped

    def test_handles_no_date_column_variants(self):
        csv = b"DATE,VAL\n2020-01-02,1.50\n2020-01-03,1.52\n"
        with patch("urllib.request.urlopen") as mock_urlopen:
            mock_urlopen.return_value.__enter__.return_value.read.return_value = csv
            result = _fetch_fred_series("^DE10Y")
        assert not result.empty


# ── _fetch_macro_batch ──────────────────────────────────────────────────────


class TestFetchMacroBatch:
    def setup_method(self):
        _macro_cache.invalidate()

    def test_returns_cached_on_subsequent_call(self):
        with patch("features.data_fetch._fetch_fred_series", return_value=pd.Series(dtype=float)):
            with patch("features.data_fetch._fetch_single_series", return_value=pd.Series(dtype=float)):
                r1 = _fetch_macro_batch()
                r2 = _fetch_macro_batch()
        assert r1 is r2

    def test_fred_fills_some_tickers(self):
        """When FRED serves some tickers but not others, missing go through yfinance."""
        def _fred_side_effect(ticker):
            if ticker == "^TNX":
                return pd.Series([0.04, 0.05], index=pd.DatetimeIndex(["2026-01-02", "2026-01-05"]), name="^TNX")
            return pd.Series(dtype=float)

        with patch("features.data_fetch._fetch_fred_series", side_effect=_fred_side_effect):
            with patch("features.data_fetch._fetch_single_series", return_value=pd.Series([15.0], name="^VIX")):
                with patch("yfinance.download", return_value=pd.DataFrame()):
                    result = _fetch_macro_batch()
        assert "^TNX" in result
        # ^TNX should be divided by 100
        assert result["^TNX"].iloc[0] == 0.0004  # 0.04 / 100

    def test_yield_tickers_none_handled_gracefully(self):
        for ticker in ["^TNX", "^FVX", "^DE10Y", "^UK10Y"]:
            with patch("features.data_fetch._fetch_fred_series", return_value=pd.Series(dtype=float)):
                with patch("features.data_fetch._fetch_single_series", return_value=pd.Series(dtype=float)):
                    with patch("yfinance.download", return_value=pd.DataFrame()):
                        result = _fetch_macro_batch()
            if ticker in result:
                assert result[ticker].empty or result[ticker].iloc[0] != result[ticker].iloc[0] * 100


# ── fetch_asset_data rate_diff edge cases ────────────────────────────────────


class TestFetchAssetDataRateDiff:
    """Tests for fetch_asset_data() rate_diff construction with edge cases."""

    @pytest.fixture(autouse=True)
    def _reset(self):
        bump_cycle_id()
        _macro_cache.invalidate()
        yield

    def _make_engine(self, n=260):
        import datetime as _dt
        base = _dt.datetime(2026, 1, 1)
        idx = pd.DatetimeIndex([base + _dt.timedelta(days=i) for i in range(n)])
        close = pd.Series(np.linspace(1.0, 1.1, n), index=idx, name="close")
        return idx, close

    def test_rate_diff_zero_for_non_fx(self):
        """BTC, GC etc should get rate_diff = 0."""
        idx, close = self._make_engine()
        prices_df = close.to_frame("close")
        with patch("features.data_fetch._provider_fetch_live", return_value=prices_df):
            with patch("features.data_fetch._normalize_index", side_effect=lambda x: x):
                with patch("features.data_fetch._fetch_macro_batch", return_value={}):
                    result = fetch_asset_data("BTCUSD", "BTC-USD")
        _, rate_diffs, *_ = result
        assert (rate_diffs.values == 0.0).all()

    def test_rate_diff_for_fx_pair(self):
        """6-char asset with both currencies known -> rate_diff computed."""
        idx, close = self._make_engine()
        prices_df = close.to_frame("close")
        # Macro series must share date range with close for alignment
        macro = {
            "^TNX": pd.Series([0.04] * len(idx), index=idx),
            "^DE10Y": pd.Series([0.02] * len(idx), index=idx),
            "^VIX": pd.Series([15.0] * len(idx), index=idx),
            "^GSPC": pd.Series([5000.0] * len(idx), index=idx),
            "CL=F": pd.Series([70.0] * len(idx), index=idx),
        }
        with patch("features.data_fetch._provider_fetch_live", return_value=prices_df):
            with patch("features.data_fetch._normalize_index", side_effect=lambda x: x):
                with patch("features.data_fetch._fetch_macro_batch", return_value=macro):
                    result = fetch_asset_data("EURUSD", "EURUSD=X")
        _, rate_diffs, *_ = result
        # EUR is ^DE10Y (0.02), USD is ^TNX (0.04) -> rate_diff = -0.02
        assert not rate_diffs.empty
        last_val = rate_diffs.iloc[-1, 0]
        assert abs(last_val - (-0.02)) < 1e-6

    def test_rate_diff_falls_back_to_tnx_when_yield_missing(self):
        """When a currency's yield ticker is not in macro, falls back to ^TNX."""
        idx, close = self._make_engine()
        prices_df = close.to_frame("close")
        macro = {
            "^TNX": pd.Series([0.04] * len(idx), index=idx),
            "^DE10Y": pd.Series([0.02] * len(idx), index=idx),
            "^VIX": pd.Series([15.0] * len(idx), index=idx),
            "^GSPC": pd.Series([5000.0] * len(idx), index=idx),
            "CL=F": pd.Series([70.0] * len(idx), index=idx),
            # ^UK10Y intentionally missing
        }
        with patch("features.data_fetch._provider_fetch_live", return_value=prices_df):
            with patch("features.data_fetch._normalize_index", side_effect=lambda x: x):
                with patch("features.data_fetch._fetch_macro_batch", return_value=macro):
                    result = fetch_asset_data("GBPUSD", "GBPUSD=X")
        _, rate_diffs, *_ = result
        # GBP ^UK10Y missing -> falls back to ^TNX (0.04)
        # USD is ^TNX (0.04) -> rate_diff ~ 0.0
        last_val = rate_diffs.iloc[-1, 0]
        assert abs(last_val) < 1e-6

    def test_rate_diff_zero_for_short_asset_name(self):
        """Assets with name shorter than 6 chars get 0 rate_diff."""
        idx, close = self._make_engine()
        prices_df = close.to_frame("close")
        with patch("features.data_fetch._provider_fetch_live", return_value=prices_df):
            with patch("features.data_fetch._normalize_index", side_effect=lambda x: x):
                with patch("features.data_fetch._fetch_macro_batch", return_value={}):
                    result = fetch_asset_data("GC", "GC=F")
        _, rate_diffs, *_ = result
        assert (rate_diffs.values == 0.0).all()

    def test_rate_diff_zero_when_currency_not_known(self):
        """Asset with unknown currency prefix gets 0 rate_diff."""
        idx, close = self._make_engine()
        prices_df = close.to_frame("close")
        with patch("features.data_fetch._provider_fetch_live", return_value=prices_df):
            with patch("features.data_fetch._normalize_index", side_effect=lambda x: x):
                with patch("features.data_fetch._fetch_macro_batch", return_value={}):
                    result = fetch_asset_data("XXXYYY", "XXXYYY=X")
        _, rate_diffs, *_ = result
        assert (rate_diffs.values == 0.0).all()


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
