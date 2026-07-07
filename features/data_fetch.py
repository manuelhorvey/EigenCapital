import logging
import threading
import time
from typing import Any

import pandas as pd

from paper_trading.ops.data_fetcher import fetch_live as _provider_fetch_live

logger = logging.getLogger("eigencapital.data_fetch")

# Fetch ~5 years for training.
# Indicator max lookback is 253 bars; 1250 provides ~1k-bar warmup margin.
_FETCH_PERIOD = "5y"
_FETCH_WARMUP_BUFFER = 1250

# Minimum history rows required for stable indicator computation.
# Must be >= the largest lookback in alpha_features.py (_MAX_INDICATOR_LOOKBACK = 253).
_MIN_HISTORY_ROWS = 253

_MACRO_TICKERS = [
    "DX-Y.NYB",
    "^VIX",
    "^GSPC",
    "CL=F",
    "^TNX",
    "^FVX",
    "^TYX",
    "^IRX",
    "^DE10Y",
    "^UK10Y",
    "^JP10Y",
    "^CH10Y",
    "^AU10Y",
    "^NZ10Y",
    "^CA10Y",
]

# Currency -> benchmark 10-year sovereign yield ticker mapping.
# Each currency maps to its own country's 10-year government bond yield.
# All tickers are FRED-sourced via _FRED_FALLBACK (yfinance fallback when FRED misses).
# US Treasury yields use native yfinance ticker (^TNX); sovereign yields use
# FRED's IRLTLT01{CC}M156N series mapped through internal ticker symbols.
CURRENCY_YIELD_TICKERS: dict[str, str] = {
    "USD": "^TNX",
    "EUR": "^DE10Y",
    "GBP": "^UK10Y",
    "JPY": "^JP10Y",
    "CHF": "^CH10Y",
    "AUD": "^AU10Y",
    "NZD": "^NZ10Y",
    "CAD": "^CA10Y",
}

# Assets that have no meaningful interest rate differential (BTCUSD, GC, CL, IWM, VIX).
# Stored in two formats: ticker-prefix (BTC for BTCUSD) and full ticker for index/macro.
_ZERO_RATE_ASSETS: set[str] = {"BTC", "BTCUSD", "GC", "CL", "IWM", "VIX"}

# Known major currency codes — built from CURRENCY_YIELD_TICKERS keys
_KNOWN_CURRENCIES: set[str] = set(CURRENCY_YIELD_TICKERS.keys())

# FRED API series IDs used as fallback when yfinance fails for macro tickers.
_FRED_FALLBACK: dict[str, str] = {
    "^VIX": "VIXCLS",
    "DX-Y.NYB": "DTWEXBGS",
    "^GSPC": "SP500",
    "CL=F": "DCOILWTICO",
    "^TNX": "DGS10",
    "^FVX": "DGS5",
    "^TYX": "DGS30",
    "^IRX": "DGS3MO",
    # Sovereign 10-year benchmark yields via FRED IRLTLT01{CC}M156N series
    "^DE10Y": "IRLTLT01DEM156N",
    "^UK10Y": "IRLTLT01GBM156N",
    "^JP10Y": "IRLTLT01JPM156N",
    "^CH10Y": "IRLTLT01CHM156N",
    "^AU10Y": "IRLTLT01AUM156N",
    "^NZ10Y": "IRLTLT01NZM156N",
    "^CA10Y": "IRLTLT01CAM156N",
}


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

# Cycle-scoped cache for fetch_asset_data results — keyed by asset name.
# Each cycle increments _cycle_id; stale entries are evicted on access.
# Thread-safe via _cycle_lock.
_cycle_cache: dict[str, tuple[int, Any]] = {}
_cycle_id: int = 0
_cycle_lock: threading.Lock = threading.Lock()


def bump_cycle_id() -> int:
    """Increment the cycle id to invalidate per-asset caches."""
    global _cycle_id
    with _cycle_lock:
        _cycle_id += 1
        return _cycle_id


def _get_cycle_cached(key: str) -> Any | None:
    with _cycle_lock:
        value = _cycle_cache.get(key)
        if value is not None and value[0] == _cycle_id:
            return value[1]
    return None


def _set_cycle_cache(key: str, value: Any) -> None:
    with _cycle_lock:
        _cycle_cache[key] = (_cycle_id, value)


def _normalize_index(idx: pd.Index) -> pd.Index:
    """Normalize a DatetimeIndex to UTC midnight."""
    idx = idx.tz_localize("UTC") if idx.tz is None else idx.tz_convert("UTC")
    return idx.normalize()


def _fetch_macro_batch() -> dict[str, pd.Series]:
    """Fetch all macro tickers — FRED API primary, yfinance fallback.

    FRED is the primary source because yfinance has been dropping many
    macro index tickers (^VIX, ^TYX, etc.).  Returns dict of {ticker: Series}
    with UTC-normalized daily indices.
    """
    cached = _macro_cache.get("macro_batch")
    if cached is not None:
        return cached

    logger.debug("fetching macro batch via FRED: %s", _MACRO_TICKERS)

    result: dict[str, pd.Series] = {}

    # FRED API is primary — more reliable than yfinance for macro indices
    for ticker in _MACRO_TICKERS:
        s = _fetch_fred_series(ticker)
        if not s.empty:
            result[ticker] = s

    # yfinance fallback for any ticker FRED could not serve
    missing = [t for t in _MACRO_TICKERS if t not in result]
    if missing:
        import yfinance as yf

        logger.debug("FRED misses — trying yfinance batch: %s", missing)
        try:
            df = yf.download(
                missing,
                period="2y",
                auto_adjust=True,
                progress=False,
                group_by="ticker",
            )
        except (OSError, ValueError, TypeError, KeyError):
            df = pd.DataFrame()

        if not df.empty and isinstance(df.columns, pd.MultiIndex):
            for ticker in missing:
                clean = ticker.replace("=", "-")
                if clean in df.columns.get_level_values(0):
                    series = df[clean]["Close"].squeeze().copy()
                    series.index = _normalize_index(series.index)
                    result[ticker] = series

        # Individual yfinance fallback for any still missing
        for ticker in missing:
            if ticker in result:
                continue
            logger.debug("macro ticker %s — yfinance individual fetch", ticker)
            try:
                s = _fetch_single_series(ticker)
                if not s.empty:
                    result[ticker] = s
            except (OSError, ValueError, TypeError):
                pass

    # Normalise all yield tickers from percentage to decimal
    _yield_tickers = {
        "^TNX",
        "^FVX",
        "^TYX",
        "^IRX",
        "^DE10Y",
        "^UK10Y",
        "^JP10Y",
        "^CH10Y",
        "^AU10Y",
        "^NZ10Y",
        "^CA10Y",
    }
    for yt in _yield_tickers:
        if yt in result and not result[yt].empty:
            result[yt] = result[yt] / 100.0

    _macro_cache.set("macro_batch", result)
    logger.debug("macro batch: %d/%d tickers fetched", len(result), len(_MACRO_TICKERS))
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


def _fetch_fred_series(ticker: str) -> pd.Series:
    """Fetch a single macro series from FRED CSV endpoint (no API key required).

    Uses stdlib urllib — no external dependency beyond pandas.
    """
    import csv
    import io
    import urllib.request

    series_id = _FRED_FALLBACK.get(ticker)
    if series_id is None:
        return pd.Series(dtype=float)
    url = f"https://fred.stlouisfed.org/graph/fredgraph.csv?id={series_id}"
    try:
        with urllib.request.urlopen(url, timeout=15) as resp:
            text = resp.read().decode("utf-8")
        rows = list(csv.DictReader(io.StringIO(text)))
        if not rows:
            return pd.Series(dtype=float)
        cols = list(rows[0].keys())
        date_col = "observation_date" if "observation_date" in cols else cols[0]
        val_col = next((c for c in cols if c != date_col), None)
        if val_col is None:
            return pd.Series(dtype=float)
        dates, values = [], []
        for r in rows:
            try:
                v = float(r[val_col])
            except (ValueError, KeyError):
                continue
            dates.append(r[date_col])
            values.append(v)
        s = pd.Series(values, index=pd.to_datetime(dates), dtype=float, name=ticker)
        s = s.loc[s.index >= "2020-01-01"]
        s.index = _normalize_index(s.index)
        logger.debug("FRED fallback succeeded for %s (%s): %d rows", ticker, series_id, len(s))
        return s
    except (OSError, ValueError, TypeError, KeyError) as exc:
        logger.debug("FRED fallback failed for %s (%s): %s", ticker, series_id, exc)
        return pd.Series(dtype=float)


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


def fetch_cot_features(
    price_index: pd.DatetimeIndex,
) -> pd.DataFrame:
    """Load COT positioning features aligned to price_index.

    Returns DataFrame with columns per FX pair (e.g. EURUSD_cot_z).
    Returns empty DataFrame if COT data is unavailable.
    """
    try:
        from data.loaders.cot_loader import FX_COT_CONTRACTS, align_cot_to_daily, get_contract_series, load_cot_weekly
        from features.cot_features import build_cot_features

        cot_weekly = _get_cycle_cached("cot_weekly_raw")
        if cot_weekly is None:
            cot_weekly = load_cot_weekly()
            _set_cycle_cache("cot_weekly_raw", cot_weekly)
        if cot_weekly.empty:
            return pd.DataFrame()

        result = pd.DataFrame(index=price_index)
        for symbol in FX_COT_CONTRACTS:
            series = get_contract_series(cot_weekly, symbol)
            if series is None or series.empty:
                continue
            aligned = align_cot_to_daily(series, price_index)
            feats = build_cot_features(aligned)
            if feats.empty:
                continue
            if "lev_net_cot_index" in feats.columns:
                val = feats["lev_net_cot_index"].reindex(price_index, method="ffill")
                result[f"{symbol}_cot_z"] = val.fillna(0.0)
            if "lev_net_change_4w" in feats.columns:
                val = feats["lev_net_change_4w"].reindex(price_index, method="ffill")
                result[f"{symbol}_cot_change_4w"] = val.fillna(0.0)

        return result
    except (OSError, ValueError, TypeError, KeyError) as exc:
        logger.debug("COT features unavailable: %s", exc)
        return pd.DataFrame()


def fetch_asset_data(
    asset_name: str,
    ticker: str,
) -> tuple[pd.DataFrame, pd.DataFrame, pd.Series, pd.Series, pd.Series, pd.DataFrame]:
    """Fetch asset OHLCV + macro data.

    Results are cached within the current engine cycle (see ``bump_cycle_id``).
    """
    cached = _get_cycle_cached(asset_name)
    if cached is not None:
        return cached

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
    except (OSError, ValueError, TypeError) as exc:
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

    prices = close.to_frame(asset_name)

    # Macro data is batch-fetched once per cycle and cached
    logger.debug("  fetching macro (DXY, VIX, SPY, CL=F, TNX)...")
    macro = _fetch_macro_batch()
    dxy = macro.get("DX-Y.NYB", pd.Series(dtype=float))
    vix = macro.get("^VIX", pd.Series(dtype=float))
    spx = macro.get("^GSPC", pd.Series(dtype=float))
    wti = macro.get("CL=F", pd.Series(dtype=float))
    tnx = macro.get("^TNX", pd.Series(dtype=float))

    # Deduplicate indices — yfinance can return duplicate dates on some tickers
    macro_series = {"dxy": dxy, "vix": vix, "spx": spx, "wti": wti, "tnx": tnx}
    for name in macro_series:
        s = macro_series[name]
        if not s.empty and s.index.duplicated().any():
            macro_series[name] = s[~s.index.duplicated(keep="last")]

    dxy, vix, spx, wti, tnx = [macro_series[k] for k in ("dxy", "vix", "spx", "wti", "tnx")]

    # Build common index from non-empty series only — a single failed macro
    # ticker no longer zero-fills the entire batch.
    # TNX uses dropna() because 10Y yield has NaN on non-business days.
    common = close.index
    if common.duplicated().any():
        logger.debug("  deduplicating close index (%d duplicates)", common.duplicated().sum())
        common = common[~common.duplicated(keep="last")]
    for s, dropna in [(dxy, False), (vix, False), (spx, False), (wti, False), (tnx, True)]:
        if not s.empty:
            idx = s.dropna().index if dropna else s.index
            if idx.duplicated().any():
                idx = idx[~idx.duplicated(keep="last")]
            common = common.intersection(idx)

    if common.empty:
        logger.warning(
            "  %s (%s): no overlapping dates between close (%s..%s) and macro — "
            "zero-filling macro data for live inference",
            asset_name,
            ticker,
            close.index.min().date() if not close.empty else "?",
            close.index.max().date() if not close.empty else "?",
        )
        close_idx = close.index
        for s_name, series in [("DXY", dxy), ("VIX", vix), ("SPX", spx), ("WTI", wti), ("TNX", tnx)]:
            if series.empty:
                logger.debug("  zero-filling %s for %s", s_name, asset_name)
        dxy = pd.Series(0.0, index=close_idx) if dxy.empty else dxy
        vix = pd.Series(0.0, index=close_idx) if vix.empty else vix
        spx = pd.Series(0.0, index=close_idx) if spx.empty else spx
        wti = pd.Series(0.0, index=close_idx) if wti.empty else wti
        tnx = pd.Series(0.0, index=close_idx) if tnx.empty else tnx
        common = close_idx

    logger.info(
        "  aligned on %d business days (close range: %s..%s, common range: %s..%s)",
        len(common),
        close.index.min().date() if not close.empty else "?",
        close.index.max().date() if not close.empty else "?",
        common.min().date() if not common.empty else "?",
        common.max().date() if not common.empty else "?",
    )

    prices = prices.loc[common].copy()
    dxy = dxy.reindex(common).ffill().fillna(0.0)
    vix = vix.reindex(common).ffill().fillna(0.0)
    spx = spx.reindex(common).ffill().fillna(0.0)
    wti = wti.reindex(common).ffill().fillna(0.0)
    tnx = tnx.reindex(common).ffill().fillna(0.0)

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
        base_yield = macro.get(base_ticker, tnx)
        if not base_yield.empty:
            base_yield = base_yield[~base_yield.index.duplicated(keep="last")]
        base_yield = base_yield.reindex(common).ffill()
        quote_yield = macro.get(quote_ticker, tnx)
        if not quote_yield.empty:
            quote_yield = quote_yield[~quote_yield.index.duplicated(keep="last")]
        quote_yield = quote_yield.reindex(common).ffill()
        rate_diff_series = base_yield - quote_yield
    else:
        rate_diff_series = pd.Series(0.0, index=common)

    rate_diffs = pd.DataFrame({asset_name: rate_diff_series}, index=common)

    commodities = wti.to_frame("WTI")

    result = (prices, rate_diffs, dxy, vix, spx, commodities)
    _set_cycle_cache(asset_name, result)
    return result


def fetch_asset_ohlcv(
    ticker: str,
    period: str | None = None,
) -> pd.DataFrame:
    """Fetch OHLCV data with UTC-normalized index.

    Uses the MT5 data provider (when installed) via data_fetcher.fetch_live(),
    falling back to yfinance automatically.

    Results are cached per ticker within the current engine cycle
    (see ``bump_cycle_id``).

    Returns DataFrame with columns: open, high, low, close, volume.
    Index is DatetimeIndex with UTC timezone, normalized to midnight.
    Fetches 500 trading days (~2 years) instead of the legacy 10 years.
    """
    cache_key = f"ohlcv:{ticker}"
    cached = _get_cycle_cached(cache_key)
    if cached is not None:
        return cached

    try:
        df = _provider_fetch_live(ticker, min_days=_FETCH_WARMUP_BUFFER)
        if df.empty:
            raise ValueError("empty DataFrame")
        df.index = _normalize_index(df.index)
        _set_cycle_cache(cache_key, df)
        return df
    except (OSError, ValueError, TypeError) as exc:
        logger.debug(
            "MT5 fetch_live failed for %s: %s — falling back to yfinance",
            ticker,
            exc,
        )

    period = period or _FETCH_PERIOD
    import yfinance as yf

    df = yf.download(ticker, period=period, auto_adjust=False, progress=False)
    if df is None:
        return pd.DataFrame()
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
    _set_cycle_cache(cache_key, df)
    return df
