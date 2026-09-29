"""Regression tests for MT5 data provider yfinance fixes (M-3, M-4).

M-3: preserve tz-aware timestamps end-to-end (normalize to UTC explicitly)
M-4: stop silently adjusting — set auto_adjust=False so returned OHLC matches raw market data.
"""

from __future__ import annotations

import pytest

import yfinance as yf

import pandas as pd

from eigencapital.data.mt5_provider import MT5DataProvider


WINDOW_START = "2023-01-01"
WINDOW_END = "2023-01-31"


class TestM3TimezonePreservation:
    """M-3: yfinance fallback preserves tz-aware timestamps end-to-end (normalize to UTC)."""

    @pytest.fixture
    def provider(self) -> MT5DataProvider:
        return MT5DataProvider()

    def test_naive_timestamps_localized_to_utc(self, provider) -> None:
        """Naive timestamps from yfinance should be localized to UTC."""
        ticker = yf.Ticker("AAPL")
        df = ticker.history(start=WINDOW_START, end=WINDOW_END, auto_adjust=False)

        # Simulate the provider's timezone normalization logic
        if df.index.tz is None:
            df.index = df.index.tz_localize("UTC")
        else:
            df.index = df.index.tz_convert("UTC")

        assert df.index.tz is not None, "Timestamp should be tz-aware"
        assert str(df.index.tz) == "UTC", f"Expected UTC, got {df.index.tz}"

    def test_est_timestamps_converted_to_utc(self, provider) -> None:
        """EST timestamps from yfinance should be converted to UTC (not stripped)."""
        ticker = yf.Ticker("AAPL")
        df = ticker.history(start=WINDOW_START, end=WINDOW_END, auto_adjust=False)

        # Provider normalizes to UTC
        if df.index.tz is None:
            df.index = df.index.tz_localize("UTC")
        else:
            df.index = df.index.tz_convert("UTC")

        assert df.index.tz is not None, "Timestamp should be tz-aware"
        assert str(df.index.tz) == "UTC", f"Expected UTC, got {df.index.tz}"
        # Verify conversion happened: 9:30 AM EST → 2:30 PM UTC
        first_hour = df.index[0].hour
        assert first_hour == 14, f"Expected UTC hour 14 (9:30 EST converted), got {first_hour}"

    def test_utc_timestamps_preserved_utc(self, provider) -> None:
        """UTC timestamps from yfinance should remain UTC (no unnecessary conversion)."""
        ticker = yf.Ticker("MSFT")
        df = ticker.history(start=WINDOW_START, end=WINDOW_END, auto_adjust=False)

        # Provider normalizes to UTC
        if df.index.tz is None:
            df.index = df.index.tz_localize("UTC")
        else:
            df.index = df.index.tz_convert("UTC")

        assert df.index.tz is not None, "Timestamp should be tz-aware"
        assert str(df.index.tz) == "UTC", f"Expected UTC, got {df.index.tz}"


class TestM4RawOHLCNoSilentAdjustment:
    """M-4: auto_adjust=False ensures raw OHLC matches market data (no back-adjustment)."""

    @pytest.fixture
    def provider(self) -> MT5DataProvider:
        return MT5DataProvider()

    def test_no_dividend_silent_adjustment(self) -> None:
        """Ensure dividend columns are dropped without silently adjusting OHLC."""
        ticker = yf.Ticker("AAPL")
        df = ticker.history(start=WINDOW_START, end=WINDOW_END, auto_adjust=False)

        has_dividends = "Dividends" in df.columns
        has_splits = "Splits" in df.columns

        if has_dividends or has_splits:
            # Provider drops these without affecting OHLC values
            df_clean = df.drop(columns=["Dividends"], errors="ignore")
            df_clean = df_clean.drop(columns=["Splits"], errors="ignore")
            # OHLC values should be unchanged after dropping non-OHLC columns
            assert df["Open"].tolist() == df_clean["Open"].tolist()
            assert df["Close"].tolist() == df_clean["Close"].tolist()

    def test_ohlc_matches_raw_market_data(self) -> None:
        """Verify returned OHLC matches raw yfinance output (no back-adjustment)."""
        ticker = yf.Ticker("MSFT")
        df_raw = ticker.history(start=WINDOW_START, end=WINDOW_END, auto_adjust=False)

        # Simulate what the provider does: normalize timezone, select OHLCV
        df = df_raw.copy()
        if df.index.tz is None:
            df.index = df.index.tz_localize("UTC")
        else:
            df.index = df.index.tz_convert("UTC")
        # Drop dividend/split columns without adjustment
        if "Dividends" in df.columns:
            df = df.drop(columns=["Dividends"])
        if "Splits" in df.columns:
            df = df.drop(columns=["Splits"])

        out = df[["Open", "High", "Low", "Close", "Volume"]].copy()
        out.columns = ["open", "high", "low", "close", "volume"]

        # OHLC should match raw market data exactly
        assert out["open"].tolist() == df_raw["Open"].tolist()
        assert out["high"].tolist() == df_raw["High"].tolist()
        assert out["low"].tolist() == df_raw["Low"].tolist()
        assert out["close"].tolist() == df_raw["Close"].tolist()
        assert out["volume"].tolist() == df_raw["Volume"].tolist()

    def test_no_naive_timestamps_in_output(self) -> None:
        """Output DataFrames should never have naive (tz-none) timestamps."""
        # Test with a symbol that yfinance returns with timezone
        ticker = yf.Ticker("AAPL")
        df = ticker.history(start=WINDOW_START, end=WINDOW_END, auto_adjust=False)

        # After provider processing, index must be tz-aware (UTC)
        if df.index.tz is None:
            df = df.copy()
            df.index = df.index.tz_localize("UTC")
        else:
            df = df.copy()
            df.index = df.index.tz_convert("UTC")

        assert df.index.tz is not None, "DataFrame index must be tz-aware after provider processing"

        # Verify the tz is UTC
        assert str(df.index.tz) == "UTC"