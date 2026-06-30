"""MarketDataService — injectable wrapper around data_fetcher operations.

Provides a single entry point for all market data (realtime prices,
historical downloads, live data) with built-in caching and rate limiting
via the underlying data_fetcher module.

Usage:
    service = MarketDataService()
    price = service.get_realtime_price("AAPL")
    prices = service.get_realtime_prices(["AAPL", "MSFT", "GOOG"])
    df = service.get_historical("SPY", period="1y")
"""

import logging
from typing import Any

import pandas as pd
import yfinance as yf

from paper_trading.ops.data_fetcher import (
    _cache_get,
    _cache_set,
    _rate_limit,
    fetch_history,
    fetch_live,
    fetch_realtime_price,
    fetch_ref,
    safe_download,
)

logger = logging.getLogger("quorrin.market_data_service")


class MarketDataService:
    """Centralized market data access with caching and optional batching."""

    def get_realtime_price(self, ticker: str) -> float | None:
        return fetch_realtime_price(ticker)

    def get_realtime_prices(self, tickers: list[str]) -> dict[str, float | None]:
        """Batch-fetch realtime prices for multiple tickers.

        Checks in-memory cache first, then issues a single yfinance
        multi-ticker request (``yf.Tickers``) for any uncached tickers.
        Falls back to individual ``fetch_realtime_price`` per ticker on
        batch failure.
        """
        result: dict[str, float | None] = {}
        uncached: list[str] = []

        for t in tickers:
            cached = _cache_get(f"realtime:{t}")
            if cached is not None and isinstance(cached, (int, float)):
                result[t] = float(cached)
            else:
                uncached.append(t)

        if not uncached:
            return result

        # Single multi-ticker request via yf.Tickers
        try:
            _rate_limit()
            tkrs = yf.Tickers(" ".join(uncached))
            for t in uncached:
                try:
                    tkr = tkrs.tickers[t]
                    if hasattr(tkr, "fast_info"):
                        lp = tkr.fast_info.get("lastPrice")
                    else:
                        lp = getattr(tkr, "last_price", None)
                    if lp is not None and not pd.isna(lp) and lp > 0:
                        price = float(lp)
                        _cache_set(f"realtime:{t}", price, "realtime")
                        result[t] = price
                        continue
                except Exception:
                    pass
                result[t] = None
        except Exception:
            logger.debug("batch realtime price fetch failed, falling back to individual")

        # Fallback for any remaining uncached tickers
        for t in uncached:
            if t not in result or result[t] is None:
                result[t] = fetch_realtime_price(t)

        return result

    def get_historical(self, ticker: str, **kwargs: Any) -> pd.DataFrame:
        return safe_download(ticker, **kwargs)

    def get_live(self, ticker: str, min_days: int = 500) -> pd.DataFrame:
        return fetch_live(ticker, min_days=min_days)

    def get_history(self, ticker: str, years: int = 10) -> pd.DataFrame:
        return fetch_history(ticker, years=years)

    def get_ref(self, ticker: str) -> pd.DataFrame | None:
        return fetch_ref(ticker)


# Module-level default instance (for backward compat / convenience)
_default_service: MarketDataService | None = None


def get_market_data_service() -> MarketDataService:
    global _default_service
    if _default_service is None:
        _default_service = MarketDataService()
    return _default_service
