import logging
import os
import time
from datetime import datetime

import pandas as pd
import pytz
import yfinance as yf

from paper_trading.state_store import StateStore

logger = logging.getLogger("quantforge.data_fetcher")

ET = pytz.timezone("US/Eastern")

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_STORE = StateStore(BASE)

_MIN_REQUEST_INTERVAL = 1.0
_last_request_time: float = 0.0

_IN_MEMORY_CACHE: dict[str, tuple[pd.DataFrame | float | None, float]] = {}
_IN_MEMORY_TTL: dict[str, float] = {
    "download": 60.0,
    "realtime": 5.0,
}


def _rate_limit() -> None:
    global _last_request_time
    elapsed = time.monotonic() - _last_request_time
    if elapsed < _MIN_REQUEST_INTERVAL:
        time.sleep(_MIN_REQUEST_INTERVAL - elapsed)
    _last_request_time = time.monotonic()


def _cache_get(key: str) -> pd.DataFrame | float | None:
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
    _IN_MEMORY_CACHE[key] = (value, time.monotonic() + ttl)


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
    return _STORE.cache_path(ticker)


def safe_download(ticker: str, **kwargs) -> pd.DataFrame:
    cache_key = f"download:{ticker}:{hash(frozenset(kwargs.items()))}"
    cached = _cache_get(cache_key)
    if cached is not None and isinstance(cached, pd.DataFrame) and not cached.empty:
        return cached
    delays = [5, 15, 45]
    for attempt, delay in enumerate(delays, 1):
        try:
            _rate_limit()
            df = yf.download(ticker, **kwargs)
            if not df.empty:
                _cache_set(cache_key, df, "download")
                _STORE.save_cache(ticker, df)
                return df
            logger.warning(f"{ticker} empty response attempt {attempt}/3")
        except Exception as e:
            logger.warning(f"{ticker} download error attempt {attempt}/3: {e}")
        if attempt < len(delays):
            time.sleep(delay)
    logger.error(f"{ticker} failed after 3 attempts — using cached data")
    df = _STORE.load_cache(ticker)
    if df is not None:
        logger.info(f"{ticker} using cached data from {_STORE.cache_path(ticker)}")
        return df
    logger.error(f"{ticker} no cached data available")
    return pd.DataFrame()


def fetch_realtime_price(ticker: str) -> float | None:
    cache_key = f"realtime:{ticker}"
    cached = _cache_get(cache_key)
    if cached is not None and isinstance(cached, (int, float)):
        return float(cached)
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


def fetch_live(ticker: str, min_days: int = 250) -> pd.DataFrame:
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
