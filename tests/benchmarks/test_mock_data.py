"""Tests for benchmarks/mock_data — synthetic market data fixture."""

import numpy as np
import pandas as pd
import pytest

from benchmarks.mock_data import MockDataFixture


@pytest.fixture
def mock():
    return MockDataFixture(tickers=["EURUSD=X", "USDJPY=X"], n_bars=100, seed=42)


class TestMockDataFixture:
    def test_generates_ohlcv_for_all_tickers(self, mock):
        assert len(mock._ohlcv) == 7  # 2 user tickers + 5 macro tickers
        assert "EURUSD=X" in mock._ohlcv
        assert "USDJPY=X" in mock._ohlcv

    def test_ohlcv_has_required_columns(self, mock):
        df = mock._ohlcv["EURUSD=X"]
        for col in ["Open", "High", "Low", "Close", "Volume"]:
            assert col in df.columns

    def test_ohlcv_has_correct_length(self, mock):
        df = mock._ohlcv["EURUSD=X"]
        assert len(df) == 100

    def test_close_prices_are_positive(self, mock):
        df = mock._ohlcv["EURUSD=X"]
        assert (df["Close"] > 0).all()

    def test_high_gte_open_and_close(self, mock):
        df = mock._ohlcv["EURUSD=X"]
        assert (df["High"] >= df[["Open", "Close"]].max(axis=1)).all()

    def test_low_lte_open_and_close(self, mock):
        df = mock._ohlcv["EURUSD=X"]
        assert (df["Low"] <= df[["Open", "Close"]].min(axis=1)).all()

    def test_generates_macro_data(self, mock):
        assert "DX-Y.NYB" in mock._ohlcv
        assert "^VIX" in mock._ohlcv
        assert "^GSPC" in mock._ohlcv

    def test_generates_rate_diffs(self, mock):
        assert "EURUSD=X" in mock._rate_diffs.columns
        assert "USDJPY=X" in mock._rate_diffs.columns
        assert len(mock._rate_diffs) == 100

    def test_mock_download_single_ticker(self, mock):
        df = mock._mock_download("EURUSD=X")
        assert isinstance(df, pd.DataFrame)
        assert "Close" in df.columns
        assert len(df) == 100

    def test_mock_download_multi_ticker(self, mock):
        df = mock._mock_download(["EURUSD=X", "USDJPY=X"], group_by="ticker")
        assert isinstance(df, pd.DataFrame)
        # Should return MultiIndex columns
        assert isinstance(df.columns, pd.MultiIndex)

    def test_lookup_ohlcv_fallback(self, mock):
        # Should fallback to first available ticker for unknown
        df = mock._lookup_ohlcv("UNKNOWN=T")
        assert isinstance(df, pd.DataFrame)

    def test_mock_download_multi_without_group_by(self, mock):
        """Multiple tickers without group_by='ticker' returns concat."""
        df = mock._mock_download(["EURUSD=X", "USDJPY=X"])
        assert isinstance(df, pd.DataFrame)

    def test_mock_download_empty_ticker_list(self, mock):
        df = mock._mock_download([], group_by="ticker")
        assert isinstance(df, pd.DataFrame)
        assert df.empty

    def test_mock_ticker_class(self, mock):
        mock.install()
        try:
            import yfinance as yf
            t = yf.Ticker("EURUSD=X")
            assert t.fast_info.get("lastPrice") == 100.0
            hist = t.history()
            assert isinstance(hist, pd.DataFrame)
            assert len(hist) == 100
        finally:
            mock.uninstall()

    def test_install_and_uninstall_roundtrip(self, mock):
        import yfinance as yf
        original_download = yf.download
        mock.install()
        assert yf.download != original_download
        mock.uninstall()
        assert yf.download == original_download

    def test_volumes_are_positive(self, mock):
        df = mock._ohlcv["EURUSD=X"]
        assert (df["Volume"] > 0).all()

    def test_vix_values_clipped(self, mock):
        vix = mock._ohlcv["^VIX"]["Close"]
        assert vix.min() >= 8
        assert vix.max() <= 50
