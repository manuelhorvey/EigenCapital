"""Intraday Session and Market Structure Features.

Phase I-C: Session/market-structure features.

Session boundaries are based on UTC timestamps and represent typical
FX/CFD trading sessions for the Exness broker.
"""

from __future__ import annotations

from datetime import time
from enum import Enum
from typing import Dict, List, Tuple

import numpy as np
import pandas as pd


class Session(Enum):
    """Trading sessions in UTC."""

    ASIAN = "asian"
    LONDON = "london"
    LONDON_OPEN = "london_open"
    LONDON_NY_OVERLAP = "london_ny_overlap"
    NEW_YORK = "new_york"
    NY_CLOSE = "ny_close"
    OFF_HOURS = "off_hours"


# Session boundaries (UTC)
SESSION_TIMES: Dict[Session, Tuple[time, time]] = {
    Session.ASIAN: (time(0, 0), time(7, 0)),
    Session.LONDON: (time(7, 0), time(16, 0)),
    Session.LONDON_OPEN: (time(7, 0), time(8, 0)),
    Session.LONDON_NY_OVERLAP: (time(12, 0), time(16, 0)),
    Session.NEW_YORK: (time(12, 0), time(21, 0)),
    Session.NY_CLOSE: (time(20, 0), time(21, 0)),
    Session.OFF_HOURS: (time(21, 0), time(0, 0)),
}


def classify_session(ts: pd.Timestamp) -> Session:
    """Classify a timestamp into a trading session (UTC)."""
    t = ts.time()

    # London/NY overlap takes priority
    if time(12, 0) <= t < time(16, 0):
        return Session.LONDON_NY_OVERLAP
    # NY close
    if time(20, 0) <= t < time(21, 0):
        return Session.NY_CLOSE
    # NY session
    if time(12, 0) <= t < time(21, 0):
        return Session.NEW_YORK
    # London open
    if time(7, 0) <= t < time(8, 0):
        return Session.LONDON_OPEN
    # London session
    if time(7, 0) <= t < time(16, 0):
        return Session.LONDON
    # Asian session
    if time(0, 0) <= t < time(7, 0):
        return Session.ASIAN
    # Off hours
    return Session.OFF_HOURS


def add_session_features(df: pd.DataFrame) -> pd.DataFrame:
    """Add session classification and time-based features to a DataFrame.

    Requires 'time' column with datetime values.
    """
    df = df.copy()
    if "time" not in df.columns:
        raise ValueError("DataFrame must have 'time' column")

    # Ensure UTC-aware timestamps for consistent classification
    if df["time"].dt.tz is not None:
        df["time_utc"] = df["time"].dt.tz_convert("UTC")
    else:
        df["time_utc"] = df["time"]

    # Session classification
    df["session"] = df["time_utc"].apply(classify_session)
    df["session_name"] = df["session"].apply(lambda s: s.value)

    # Time-based features
    df["hour"] = df["time_utc"].dt.hour
    df["minute"] = df["time_utc"].dt.minute
    df["day_of_week"] = df["time_utc"].dt.dayofweek
    df["is_session_open"] = df["session"].apply(lambda s: s != Session.OFF_HOURS)

    # Session-specific flags
    df["is_asian"] = (df["session"] == Session.ASIAN).astype(int)
    df["is_london"] = (df["session"] == Session.LONDON).astype(int)
    df["is_london_open"] = (df["session"] == Session.LONDON_OPEN).astype(int)
    df["is_ny_overlap"] = (df["session"] == Session.LONDON_NY_OVERLAP).astype(int)
    df["is_new_york"] = (df["session"] == Session.NEW_YORK).astype(int)
    df["is_ny_close"] = (df["session"] == Session.NY_CLOSE).astype(int)
    df["is_off_hours"] = (df["session"] == Session.OFF_HOURS).astype(int)

    # Bars into session (0-indexed within each session block)
    df["bars_into_session"] = df.groupby((df["session"] != df["session"].shift()).cumsum()).cumcount()

    # Drop temp column
    df = df.drop(columns=["time_utc"], errors="ignore")

    return df


def add_realized_volatility_features(
    df: pd.DataFrame,
    windows: List[int] | None = None,
) -> pd.DataFrame:
    """Add realized volatility features at multiple horizons.

    Args:
        df: DataFrame with 'close' column
        windows: list of lookback windows in bars (default: 12, 36, 72, 144)
    """
    df = df.copy()
    windows = windows or [12, 36, 72, 144]  # 1h, 3h, 6h, 12h at M5

    if "close" not in df.columns:
        return df

    log_returns = np.log(df["close"] / df["close"].shift(1))

    for w in windows:
        df[f"rv_{w}"] = log_returns.rolling(w).std() * np.sqrt(288)  # annualized
        df[f"rv_rank_{w}"] = df[f"rv_{w}"].rolling(w * 10).rank(pct=True)

    return df


def add_price_structure_features(df: pd.DataFrame) -> pd.DataFrame:
    """Add price structure features for intraday analysis."""
    df = df.copy()

    if not all(c in df.columns for c in ["open", "high", "low", "close"]):
        return df

    # Range features
    df["bar_range"] = df["high"] - df["low"]
    df["body"] = df["close"] - df["open"]
    df["body_pct"] = df["body"] / df["bar_range"].replace(0, np.nan)
    df["upper_shadow"] = df["high"] - df[["open", "close"]].max(axis=1)
    df["lower_shadow"] = df[["open", "close"]].min(axis=1) - df["low"]

    # Cumulative features within session
    if "session_name" in df.columns:
        df["session_high"] = df.groupby((df["session_name"] != df["session_name"].shift()).cumsum())["high"].cummax()
        df["session_low"] = df.groupby((df["session_name"] != df["session_name"].shift()).cumsum())["low"].cummin()
        df["range_position"] = (df["close"] - df["session_low"]) / (
            (df["session_high"] - df["session_low"]).replace(0, np.nan)
        )

    # Distance from N-bar high/low
    for w in [12, 36, 72]:
        df[f"dist_high_{w}"] = df["high"].rolling(w).max() - df["close"]
        df[f"dist_low_{w}"] = df["close"] - df["low"].rolling(w).min()

    return df
