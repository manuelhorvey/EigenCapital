import logging
import threading
import time
from typing import Any

import pandas as pd

from paper_trading.ops.data_fetcher import fetch_live as _provider_fetch_live

logger = logging.getLogger("quantforge.data_fetch")

# Fetch ~5 years for training — tight-SL assets (AUDCHF, ES, NQ, ^DJI)
# need more binary samples to reach the 100 minimum.
# Indicator max lookback is 253 bars; 1250 provides ~1k-bar warmup margin.
_FETCH_PERIOD = "5y"
_FETCH_WARMUP_BUFFER = 1250

# Minimum history rows required for stable indicator computation.
# Must be >= the largest lookback in alpha_features.py (_MAX_INDICATOR_LOOKBACK = 253).
_MIN_HISTORY_ROWS = 253

_MACRO_TICKERS = ["DX-Y.NYB", "^VIX", "^GSPC", "CL=F", "^TNX", "^FVX", "^TYX", "^IRX"]

# Currency -> benchmark yield ticker mapping.
# US Treasury yields at different maturities serve as proxies for
# structurally similar yield levels in other developed economies.
# ^TNX (10Y) = moderate yield (USD, GBP, CAD)
# ^FVX  (5Y) = lower yield  (EUR)
# ^TYX (30Y) = higher yield (AUD, NZD)
# ^IRX (3M)  = near-zero     (JPY, CHF)
CURRENCY_YIELD_TICKERS: dict[str, str] = {
    "USD": "^TNX",
    "EUR": "^FVX",
    "GBP": "^TNX",
    "JPY": "^IRX",
    "CHF": "^IRX",
    "AUD": "^TYX",
    "NZD": "^TYX",
    "CAD": "^TNX",
}

# Assets that have no meaningful interest rate differential (crypto, commodities)
_ZERO_RATE_ASSETS: set[str] = {"BTC", "GC", "CL", "ES", "NQ", "IWM", "VIX", "DJI"}

# Known major currency codes — built from CURRENCY_YIELD_TICKERS keys
_KNOWN_CURRENCIES: set[str] = set(CURRENCY_YIELD_TICKERS.keys())


class _TTLCache:
    """Thread-safe TTL cache for fetched data.

    Default TTL of 300s matches the engine cycle interval so data is
    never stale across cycles but repeated per-asset fetches hit cache.
    """

    def __init__(self, ttl: int = 300):
        self._cache: dict[str, tuple[float, Any]] = {}
        self._lock = threading.Lock()
        self._ttl = ttl

    def get(self, key: str) -> Any | None:
        with self._lock:
            expiry, value = self._cache.get(key, (0.0, None))
            if time.monotonic() < expiry:
                return value
        return None

    def set(self, key: str, value: Any) -> None:
        with self._lock:
            self._cache[key] = (time.monotonic() + self._ttl, value)

    def invalidate(self) -> None:
        with self._lock:
            self._cache.clear()


# Module-level cache shared across all assets in the same cycle.
_macro_cache = _TTLCache(ttl=300)


def _normalize_index(idx: pd.Index) -> pd.Index:
    """Normalize a DatetimeIndex to UTC midnight."""
    idx = idx.tz_localize("UTC") if idx.tz is None else idx.tz_convert("UTC")
    return idx.normalize()


def _fetch_macro_batch() -> dict[str, pd.Series]:
    """Fetch all macro tickers in a single yfinance call.

    Returns dict of {name: Series} with UTC-normalized daily indices.
    """
    import yfinance as yf

    cached = _macro_cache.get("macro_batch")
    if cached is not None:
        return cached

    logger.debug("fetching macro batch: %s", _MACRO_TICKERS)
    df = yf.download(
        _MACRO_TICKERS,
        period=_FETCH_PERIOD,
        auto_adjust=True,
        progress=False,
        group_by="ticker",
    )

    result: dict[str, pd.Series] = {}
    if df.empty:
        logger.warning("macro batch download returned empty — retrying individually")
        for ticker in _MACRO_TICKERS:
            result[ticker] = _fetch_single_series(ticker)
        _macro_cache.set("macro_batch", result)
        return result

    # yfinance with group_by="ticker" returns MultiIndex columns.
    # Handle both MultiIndex and single-column cases.
    if isinstance(df.columns, pd.MultiIndex):
        for ticker in _MACRO_TICKERS:
            clean = ticker.replace("=", "-")
            if clean in df.columns.get_level_values(0):
                series = df[clean]["Close"].squeeze().copy()
                series.index = _normalize_index(series.index)
                result[ticker] = series
    else:
        # Single ticker or fallback — shouldn't happen with multi-ticker download
        for ticker in _MACRO_TICKERS:
            # rename columns to match single-ticker format
            pass  # fallback to individual fetch below

    # Fallback for any ticker that wasn't in the batch result
    for ticker in _MACRO_TICKERS:
        if ticker not in result:
            logger.debug("macro ticker %s not in batch — fetching individually", ticker)
            result[ticker] = _fetch_single_series(ticker)

    # Normalise all yield tickers from percentage to decimal
    _yield_tickers = {"^TNX", "^FVX", "^TYX", "^IRX"}
    for yt in _yield_tickers:
        if yt in result and not result[yt].empty:
            result[yt] = result[yt] / 100.0

    _macro_cache.set("macro_batch", result)
    logger.debug("macro batch: %d tickers fetched", len(result))
    return result


def _fetch_single_series(ticker: str, name: str | None = None) -> pd.Series:
    """Fetch a single yfinance series, return daily 'Close' Series.

    Used as fallback when batch download fails for individual tickers.
    """
    import yfinance as yf

    df = yf.download(ticker, period=_FETCH_PERIOD, auto_adjust=True, progress=False)
    if df.empty:
        logger.warning("single fetch returned empty for %s", ticker)
        return pd.Series(dtype=float)
    s = df["Close"].squeeze().copy()
    s.index = _normalize_index(s.index)
    if name:
        s.name = name
    return s


def fetch_yf_series(ticker: str, name: str, period: str | None = None) -> pd.Series:
    """Fetch a single yfinance series, return daily 'Close' with UTC index.

    Uses the macro cache if the ticker is a known macro ticker.
    Falls back to individual fetch for per-asset tickers.
    """
    period = period or _FETCH_PERIOD

    # Check macro cache for shared tickers
    if ticker in _MACRO_TICKERS:
        macro = _macro_cache.get("macro_batch")
        if macro is not None and ticker in macro:
            s = macro[ticker].copy()
            s.name = name
            return s

    return _fetch_single_series(ticker, name=name)


def fetch_asset_data(
    asset_name: str,
    ticker: str,
) -> tuple[pd.DataFrame, pd.DataFrame, pd.Series, pd.Series, pd.Series, pd.DataFrame]:
    """Fetch asset OHLCV + macro data.

    Per-asset close uses the MT5 data provider (when installed) via
    data_fetcher.fetch_live(), falling back to yfinance automatically.
    Macro tickers (DXY, VIX, SPX, WTI, TNX) are batch-fetched from yfinance
    once per cycle and cached — these are slow-moving indices where the
    T-1 staleness is acceptable.

    Returns (prices, rate_diffs, dxy, vix, spx, commodities).
    prices: DataFrame with 'close' column
    rate_diffs: DataFrame with asset_name column (approximated from 10Y yield)
    dxy, vix, spx: Series
    commodities: DataFrame with 'WTI' column
    """
    # Per-asset close via MT5 provider (falls back to yfinance automatically).
    # fetch_live returns US/Eastern index; normalise to UTC midnight to
    # align with macro data from yfinance.
    logger.info("  fetching %s (%s) ...", asset_name, ticker)
    try:
        raw = _provider_fetch_live(ticker, min_days=_FETCH_WARMUP_BUFFER)
        if raw.empty:
            raise ValueError("empty DataFrame")
        close = raw["close"].copy()
        close.index = _normalize_index(close.index)
    except Exception as exc:
        logger.debug(
            "MT5 fetch_live failed for %s (%s): %s — falling back to yfinance",
            asset_name,
            ticker,
            exc,
        )
        close = fetch_yf_series(ticker, f"{asset_name}_close")

    if len(close) < _MIN_HISTORY_ROWS:
        raise ValueError(
            f"{asset_name} ({ticker}): insufficient history ({len(close)} rows, need >= {_MIN_HISTORY_ROWS})"
        )

    prices = close.to_frame("close")

    # Macro data is batch-fetched once per cycle and cached
    logger.debug("  fetching macro (DXY, VIX, SPY, CL=F, TNX)...")
    macro = _fetch_macro_batch()
    dxy = macro.get("DX-Y.NYB", pd.Series(dtype=float))
    vix = macro.get("^VIX", pd.Series(dtype=float))
    spx = macro.get("^GSPC", pd.Series(dtype=float))
    wti = macro.get("CL=F", pd.Series(dtype=float))
    tnx = macro.get("^TNX", pd.Series(dtype=float))

    common = close.index.intersection(dxy.index).intersection(vix.index).intersection(spx.index).intersection(wti.index)
    common = common.intersection(tnx.dropna().index)
    logger.info(
        "  aligned on %d business days (close range: %s..%s, common range: %s..%s)",
        len(common),
        close.index.min().date() if not close.empty else "?",
        close.index.max().date() if not close.empty else "?",
        common.min().date() if not common.empty else "?",
        common.max().date() if not common.empty else "?",
    )
    if common.empty:
        raise ValueError(
            f"{asset_name} ({ticker}): no overlapping dates between asset close "
            f"({close.index.min().date() if not close.empty else '?'}.."
            f"{close.index.max().date() if not close.empty else '?'}) "
            f"and macro data — possible stale/delayed macro update"
        )

    prices = prices.loc[common].copy()
    dxy = dxy.reindex(common).ffill()
    vix = vix.reindex(common).ffill()
    spx = spx.reindex(common).ffill()
    wti = wti.reindex(common).ffill()
    tnx = tnx.reindex(common).ffill()

    # ── Real rate differentials —───────────────────────────────────
    # Parse asset name into base/quote currencies for FX pairs.
    # For non-FX assets (BTC, GC, etc.) rate_diff = 0.
    asset_upper = asset_name.upper()
    base_ccy: str | None = None
    quote_ccy: str | None = None
    if (
        asset_upper not in _ZERO_RATE_ASSETS
        and len(asset_upper) == 6
        and asset_upper[:3] in _KNOWN_CURRENCIES
        and asset_upper[3:] in _KNOWN_CURRENCIES
    ):
        base_ccy = asset_upper[:3]
        quote_ccy = asset_upper[3:]

    if base_ccy is not None and quote_ccy is not None:
        base_ticker = CURRENCY_YIELD_TICKERS[base_ccy]
        quote_ticker = CURRENCY_YIELD_TICKERS[quote_ccy]
        base_yield = macro.get(base_ticker, tnx).reindex(common).ffill()
        quote_yield = macro.get(quote_ticker, tnx).reindex(common).ffill()
        rate_diff_series = base_yield - quote_yield
    else:
        rate_diff_series = pd.Series(0.0, index=common)

    rate_diffs = pd.DataFrame({asset_name: rate_diff_series}, index=common)

    commodities = wti.to_frame("WTI")

    return prices, rate_diffs, dxy, vix, spx, commodities


def fetch_asset_ohlcv(
    ticker: str,
    period: str | None = None,
) -> pd.DataFrame:
    """Fetch OHLCV data with UTC-normalized index.

    Uses the MT5 data provider (when installed) via data_fetcher.fetch_live(),
    falling back to yfinance automatically.

    Returns DataFrame with columns: open, high, low, close, volume.
    Index is DatetimeIndex with UTC timezone, normalized to midnight.
    Fetches 500 trading days (~2 years) instead of the legacy 10 years.
    """
    try:
        df = _provider_fetch_live(ticker, min_days=_FETCH_WARMUP_BUFFER)
        if df.empty:
            raise ValueError("empty DataFrame")
        df.index = _normalize_index(df.index)
        return df
    except Exception as exc:
        logger.debug(
            "MT5 fetch_live failed for %s: %s — falling back to yfinance",
            ticker,
            exc,
        )

    period = period or _FETCH_PERIOD
    import yfinance as yf

    df = yf.download(ticker, period=period, auto_adjust=True, progress=False)
    if df.empty:
        return pd.DataFrame()
    if isinstance(df.columns, pd.MultiIndex):
        df.columns = [c[0] for c in df.columns]
    df = df.rename(
        columns={
            "Open": "open",
            "High": "high",
            "Low": "low",
            "Close": "close",
            "Volume": "volume",
        }
    )
    df.index = _normalize_index(df.index)
    return df
