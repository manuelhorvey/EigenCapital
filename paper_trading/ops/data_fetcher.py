import logging
import os
import threading
import time
from datetime import datetime

import pandas as pd
import pytz
import yfinance as yf

logger = logging.getLogger("quantforge.data_fetcher")

ET = pytz.timezone("US/Eastern")

BASE = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

_STORE: object | None = None


def _get_store():
    global _STORE
    if _STORE is None:
        from paper_trading.state_store import StateStore

        _STORE = StateStore(BASE)
    return _STORE


_MIN_REQUEST_INTERVAL = 1.0
_last_request_time: float = 0.0
_rate_limit_lock = threading.Lock()

_IN_MEMORY_CACHE: dict[str, tuple[pd.DataFrame | float | None, float]] = {}
_IN_MEMORY_TTL: dict[str, float] = {
    "download": 60.0,
    "realtime": 5.0,
}

# Optional MT5 client override — set by engine when mt5 is enabled.
# All module-level fetch functions will use this instead of yfinance.
_mt5_client: object | None = None
_mt5_symbol_map: dict[str, str] = {}
_mt5_client_lock = threading.Lock()
_cache_lock = threading.Lock()


def set_mt5_client(client: object, symbol_map: dict[str, str] | None = None) -> None:
    """Install an MT5 client as the data provider instead of yfinance."""
    with _mt5_client_lock:
        global _mt5_client, _mt5_symbol_map
        _mt5_client = client
        _mt5_symbol_map = symbol_map or {}
    logger.info("MT5 data provider installed — all data fetches will use MT5 bridge")


def _rate_limit() -> None:
    global _last_request_time
    with _rate_limit_lock:
        elapsed = time.monotonic() - _last_request_time
        if elapsed < _MIN_REQUEST_INTERVAL:
            time.sleep(_MIN_REQUEST_INTERVAL - elapsed)
        _last_request_time = time.monotonic()


def _cache_get(key: str) -> pd.DataFrame | float | None:
    with _cache_lock:
        entry = _IN_MEMORY_CACHE.get(key)
        if entry is None:
            return None
        value, expiry = entry
        if time.monotonic() > expiry:
            del _IN_MEMORY_CACHE[key]
            return None
    return value


def _cache_set(key: str, value: pd.DataFrame | float | None, cache_type: str = "download") -> None:
    ttl = _IN_MEMORY_TTL.get(cache_type, 60.0)
    with _cache_lock:
        _IN_MEMORY_CACHE[key] = (value, time.monotonic() + ttl)


def _mt5_get_client() -> object | None:
    """Thread-safe read of the global MT5 client."""
    with _mt5_client_lock:
        return _mt5_client


def _mt5_ensure_connected() -> bool:
    """Ensure the global MT5 client is connected, reconnecting if needed."""
    client = _mt5_get_client()
    if client is None:
        return False
    try:
        return client.ensure_connected()
    except Exception:
        return False


def _mt5_fetch_ohlcv(ticker: str, years: int = 2) -> pd.DataFrame:
    """Fetch OHLCV via MT5 client if installed."""
    client = _mt5_get_client()
    if client is None:
        return pd.DataFrame()
    if not _mt5_ensure_connected():
        return pd.DataFrame()
    try:
        return client.fetch_ohlcv(ticker, years=years)
    except Exception as e:
        logger.warning("MT5 fetch_ohlcv failed for %s: %s", ticker, e)
        return pd.DataFrame()


def _mt5_realtime_price(ticker: str) -> float | None:
    """Fetch realtime price via MT5 client if installed."""
    client = _mt5_get_client()
    if client is None:
        return None
    if not _mt5_ensure_connected():
        return None
    try:
        return client.realtime_mid_price(ticker)
    except Exception as e:
        logger.warning("MT5 realtime_price failed for %s: %s", ticker, e)
        return None


def _check_data_quality(df: pd.DataFrame, ticker: str, source: str = "") -> None:
    try:
        if df.empty:
            return
        label = f"{ticker}[{source}]" if source else ticker

        last_bar = df.index[-1]
        now = datetime.now(tz=last_bar.tz) if hasattr(last_bar, "tz") and last_bar.tz is not None else datetime.now()
        delta = now - last_bar
        days_since = delta.days if hasattr(delta, "days") else delta.total_seconds() / 86400
        if days_since > 4:
            logger.warning("%s: stale data — last bar %s (%.0f days ago)", label, last_bar, days_since)

        close_col = "close" if "close" in df.columns else ("Close" if "Close" in df.columns else None)
        if close_col is not None:
            close_s = df[close_col]
            if isinstance(close_s, pd.DataFrame):
                close_s = close_s.iloc[:, 0]
            nan_streak = close_s.isna().astype(int).groupby(close_s.notna().cumsum()).cumsum()
            max_consec_nan = nan_streak.max() if not nan_streak.empty else 0
            if max_consec_nan >= 3:
                logger.warning("%s: %d consecutive NaN closes detected", label, max_consec_nan)
    except Exception as e:
        logger.warning("%s: data quality check failed: %s", ticker, e)


def flatten(df: pd.DataFrame) -> pd.DataFrame:
    if isinstance(df.columns, pd.MultiIndex):
        df.columns = [c[0] for c in df.columns]
    return df.rename(
        columns={
            "Close": "close",
            "High": "high",
            "Low": "low",
            "Open": "open",
            "Volume": "volume",
        }
    )


def norm_index(df: pd.DataFrame) -> pd.DataFrame:
    if not isinstance(df.index, pd.DatetimeIndex):
        df.index = pd.to_datetime(df.index)
    idx = df.index
    if idx.tz is not None:
        df.index = idx.tz_convert("US/Eastern")
    else:
        df.index = idx.tz_localize("US/Eastern")
    return df


def _cache_path(ticker: str) -> str:
    return _get_store().cache_path(ticker)


def safe_download(ticker: str, **kwargs) -> pd.DataFrame:
    cache_key = f"download:{ticker}:{hash(frozenset(kwargs.items()))}"
    cached = _cache_get(cache_key)
    if cached is not None and isinstance(cached, pd.DataFrame) and not cached.empty:
        return cached

    # Try MT5 first if provider is installed
    if _mt5_client is not None:
        years = 2  # default
        if "start" in kwargs:
            try:
                start = datetime.strptime(kwargs["start"], "%Y-%m-%d")
                years = max((datetime.now() - start).days / 365, 1)
            except (ValueError, TypeError):
                pass
        df = _mt5_fetch_ohlcv(ticker, years=int(years) + 1)
        if not df.empty:
            _cache_set(cache_key, df, "download")
            _get_store().save_cache(ticker, df)
            _check_data_quality(df, ticker, source="mt5")
            return df

    delays = [5, 15, 45]
    for attempt, delay in enumerate(delays, 1):
        try:
            _rate_limit()
            df = yf.download(ticker, **kwargs)
            if not df.empty:
                _cache_set(cache_key, df, "download")
                _get_store().save_cache(ticker, df)
                _check_data_quality(df, ticker, source="live")
                return df
            logger.warning(f"{ticker} empty response attempt {attempt}/3")
        except Exception as e:
            logger.warning(f"{ticker} download error attempt {attempt}/3: {e}")
        if attempt < len(delays):
            time.sleep(delay)
    logger.error(f"{ticker} failed after 3 attempts — using cached data")
    df = _get_store().load_cache(ticker)
    if df is not None:
        logger.info(f"{ticker} using cached data from {_get_store().cache_path(ticker)}")
        _check_data_quality(df, ticker, source="cache")
        return df
    logger.error(f"{ticker} no cached data available")
    return pd.DataFrame()


def fetch_realtime_price(ticker: str) -> float | None:
    cache_key = f"realtime:{ticker}"
    cached = _cache_get(cache_key)
    if cached is not None and isinstance(cached, (int, float)):
        return float(cached)

    # Try MT5 first if provider is installed
    if _mt5_client is not None:
        price = _mt5_realtime_price(ticker)
        if price is not None:
            _cache_set(cache_key, price, "realtime")
            return price

    try:
        _rate_limit()
        t = yf.Ticker(ticker)
        lp = t.fast_info.get("lastPrice")
        if lp is not None and not pd.isna(lp) and lp > 0:
            _cache_set(cache_key, float(lp), "realtime")
            return float(lp)
    except Exception:
        pass

    try:
        _rate_limit()
        df = yf.download(ticker, period="1d", interval="1m", progress=False)
        if not df.empty:
            df = flatten(df)
            price = float(df["close"].ffill().iloc[-1])
            _cache_set(cache_key, price, "realtime")
            return price
    except Exception:
        pass
    return None


def fetch_live(ticker: str, min_days: int = 500) -> pd.DataFrame:
    start_dt = datetime.now(tz=ET) - pd.Timedelta(days=min_days)
    start = start_dt.strftime("%Y-%m-%d")
    df = safe_download(
        ticker,
        start=start,
        auto_adjust=True,
        progress=False,
    )
    if df.empty:
        raise ValueError(f"No live data for {ticker}")
    df = flatten(df)
    df = norm_index(df)
    return df


def fetch_history(ticker: str, years: int = 10) -> pd.DataFrame:
    start = f"{datetime.now(tz=ET).year - years}-01-01"
    df = safe_download(
        ticker,
        start=start,
        auto_adjust=True,
        progress=False,
    )
    if df.empty:
        raise ValueError(f"No history for {ticker}")
    df = flatten(df)
    df = norm_index(df)
    return df


def fetch_ref(ticker: str) -> pd.DataFrame | None:
    try:
        return fetch_history(ticker, years=10)
    except Exception:
        return None
