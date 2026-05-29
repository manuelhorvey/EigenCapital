"""Synthetic market data fixture mocks at the network boundary.

Substitutes ``fetch_live``, ``fetch_asset_data``, and
``fetch_asset_ohlcv`` with pre-generated random-walk data so the
full feature-build + inference hot path runs without network I/O.
"""

import logging
from typing import Any

import numpy as np
import pandas as pd

logger = logging.getLogger("benchmark.mock_data")

_MACRO_TICKERS = ["DX-Y.NYB", "^VIX", "^GSPC", "CL=F", "^TNX"]


class MockDataFixture:
    """Generates synthetic OHLCV + macro data and monkeypatches fetch functions.

    Usage::

        mock = MockDataFixture(tickers=["EURUSD=X", "USDJPY=X"], n_bars=500)
        mock.install()
        # ... run engine ...
        mock.uninstall()
    """

    def __init__(self, tickers: list[str], n_bars: int = 500, seed: int = 42):
        self._tickers = list(tickers)
        self._n_bars = n_bars
        self._originals: dict[str, Any] = {}
        self._generate(seed)

    # ── Data generation ──────────────────────────────────────────────

    def _generate(self, seed: int) -> None:
        rng = np.random.RandomState(seed)
        dates_utc = pd.date_range(end="2026-05-29", periods=self._n_bars, freq="D", tz="UTC")
        dates_utc = dates_utc.normalize()

        # Per-ticker OHLCV (lowercase columns, US/Eastern index — matches fetch_live)
        dates_et = dates_utc.tz_convert("US/Eastern")
        self._ohlcv: dict[str, pd.DataFrame] = {}
        for ticker in self._tickers:
            drift = rng.uniform(-0.0002, 0.0005)
            log_rets = rng.randn(self._n_bars) * 0.012 + drift
            closes = 100.0 * np.exp(np.cumsum(log_rets))
            opens = closes * np.exp(rng.randn(self._n_bars) * 0.002)
            highs = np.maximum(opens, closes) * (1 + np.abs(rng.randn(self._n_bars)) * 0.003)
            lows = np.minimum(opens, closes) * (1 - np.abs(rng.randn(self._n_bars)) * 0.003)
            volumes = rng.randint(500_000, 5_000_000, self._n_bars)
            self._ohlcv[ticker] = pd.DataFrame(
                {
                    "open": opens,
                    "high": highs,
                    "low": lows,
                    "close": closes,
                    "volume": volumes,
                },
                index=dates_et.copy(),
            )

        # Shared macro series (UTC index, normalised to midnight)
        vix_raw = 15.0 + np.cumsum(rng.randn(self._n_bars) * 0.5)
        vix_raw = np.clip(vix_raw, 8, 50)
        self._macro: dict[str, pd.Series] = {
            "DX-Y.NYB": pd.Series(
                105.0 + np.cumsum(rng.randn(self._n_bars) * 0.05), index=dates_utc, name="close"
            ),
            "^VIX": pd.Series(vix_raw, index=dates_utc, name="close"),
            "^GSPC": pd.Series(
                4500.0 * np.exp(np.cumsum(rng.randn(self._n_bars) * 0.008)), index=dates_utc, name="close"
            ),
            "CL=F": pd.Series(
                75.0 * np.exp(np.cumsum(rng.randn(self._n_bars) * 0.015)), index=dates_utc, name="close"
            ),
            "^TNX": pd.Series(4.0 + np.cumsum(rng.randn(self._n_bars) * 0.02), index=dates_utc, name="close"),
        }

        # Rate diffs: one column per ticker
        self._rate_diffs = pd.DataFrame(
            {t: rng.randn(self._n_bars) * 0.001 for t in self._tickers},
            index=dates_utc,
        )

    # ── Install / uninstall monkeypatches ────────────────────────────

    def install(self) -> None:
        import paper_trading.ops.data_fetcher as fetcher_mod
        import features.data_fetch as data_mod

        self._originals = {
            "fetch_live": fetcher_mod.fetch_live,
            "fetch_asset_data": data_mod.fetch_asset_data,
            "fetch_asset_ohlcv": data_mod.fetch_asset_ohlcv,
        }
        fetcher_mod.fetch_live = self._mock_fetch_live
        data_mod.fetch_asset_data = self._mock_fetch_asset_data
        data_mod.fetch_asset_ohlcv = self._mock_fetch_asset_ohlcv

    def uninstall(self) -> None:
        import paper_trading.ops.data_fetcher as fetcher_mod
        import features.data_fetch as data_mod

        fetcher_mod.fetch_live = self._originals["fetch_live"]
        data_mod.fetch_asset_data = self._originals["fetch_asset_data"]
        data_mod.fetch_asset_ohlcv = self._originals["fetch_asset_ohlcv"]

    # ── Mock fetch implementations ───────────────────────────────────

    def _lookup_ohlcv(self, ticker: str) -> pd.DataFrame:
        df = self._ohlcv.get(ticker)
        if df is not None:
            return df.copy()
        for k, v in self._ohlcv.items():
            if ticker in k or k in ticker:
                return v.copy()
        return next(iter(self._ohlcv.values())).copy()

    def _mock_fetch_live(self, ticker: str, min_days: int = 500) -> pd.DataFrame:
        return self._lookup_ohlcv(ticker)

    def _mock_fetch_asset_data(
        self, asset_name: str, ticker: str
    ) -> tuple[pd.DataFrame, pd.DataFrame, pd.Series, pd.Series, pd.Series, pd.DataFrame]:
        ohlcv = self._lookup_ohlcv(ticker)

        # prices: single-column DataFrame with 'close'
        close = ohlcv["close"].copy()
        close.index = close.index.tz_convert("UTC").normalize()
        prices = close.to_frame("close")

        # Macro series
        dxy = self._macro["DX-Y.NYB"]
        vix = self._macro["^VIX"]
        spx = self._macro["^GSPC"]
        wti = self._macro["CL=F"]
        tnx = self._macro["^TNX"]

        # Align to common index
        common = prices.index.intersection(dxy.index)
        common = common.intersection(vix.index).intersection(spx.index).intersection(wti.index)
        common = common.intersection(tnx.dropna().index)

        prices = prices.loc[common].copy()
        dxy = dxy.reindex(common).ffill()
        vix = vix.reindex(common).ffill()
        spx = spx.reindex(common).ffill()
        wti = wti.reindex(common).ffill()
        tnx = tnx.reindex(common).ffill()

        rng = np.random.default_rng(42)
        rate_diffs = pd.DataFrame(
            {asset_name: tnx * float(rng.uniform(0.5, 1.5))}, index=common,
        )
        commodities = wti.to_frame("WTI")

        return prices, rate_diffs, dxy, vix, spx, commodities

    def _mock_fetch_asset_ohlcv(self, ticker: str, period: str | None = None) -> pd.DataFrame:
        df = self._lookup_ohlcv(ticker)
        df.index = df.index.tz_convert("UTC").normalize()
        return df
