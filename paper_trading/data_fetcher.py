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
    delays = [5, 15, 45]
    for attempt, delay in enumerate(delays, 1):
        try:
            df = yf.download(ticker, **kwargs)
            if not df.empty:
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


def fetch_live(ticker: str, min_days: int = 250) -> pd.DataFrame:
    end = datetime.now(tz=ET)
    start = (end - pd.Timedelta(days=min_days)).strftime("%Y-%m-%d")
    df = safe_download(
        ticker,
        start=start,
        end=end.strftime("%Y-%m-%d"),
        auto_adjust=True,
        progress=False,
    )
    if df.empty:
        raise ValueError(f"No live data for {ticker}")
    df = flatten(df)
    df = norm_index(df)
    return df


def fetch_history(ticker: str, years: int = 10) -> pd.DataFrame:
    end = datetime.now(tz=ET)
    start = f"{end.year - years}-01-01"
    df = safe_download(
        ticker,
        start=start,
        end=end.strftime("%Y-%m-%d"),
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
