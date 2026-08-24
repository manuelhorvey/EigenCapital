"""Intraday Data Puller — pulls 5-minute OHLCV bars from MT5 via Wine bridge.

Phase I-A: Data Acquisition and Integrity
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Dict, List, Any, Optional, Tuple

import pandas as pd
import numpy as np

logger = logging.getLogger(__name__)

# Initial intraday universe — 8 instruments
INTRADAY_UNIVERSE = [
    "EURUSDm",  # Deep/liquid FX benchmark
    "GBPUSDm",  # More volatile FX
    "USDJPYm",  # Asian session behavior
    "AUDUSDm",  # Asia-Pacific exposure
    "XAUUSDm",  # High-volatility non-FX
    "US500m",   # Major U.S. index
    "USTECm",   # Higher-beta U.S. index
    "USOILm",   # Commodity dynamics
]

# Excluded initially
EXCLUDED_SYMBOLS = [
    "BTCUSDm", "ETHUSDm",  # Crypto — separate campaign
    "XAGUSDm",  # Redundant with gold initially
    "US30m",    # Redundant with US500/USTEC initially
    "NZDUSDm", "USDCADm", "USDCHFm",  # Add after R1
]

TIMEFRAME_M5 = 5  # MT5 timeframe constant for M5


@dataclass
class IntradayDataManifest:
    """Frozen data snapshot identity for intraday research campaign."""
    broker: str
    terminal_id: str
    symbols: List[str]
    timeframe: str
    bars_per_symbol: Dict[str, int]
    total_bars: int
    first_timestamp: str
    last_timestamp: str
    retrieval_timestamp: str
    missing_bars: int
    duplicate_bars: int
    ohlc_violations: int
    snapshot_hash: str

    def to_dict(self) -> Dict[str, Any]:
        return {
            "broker": self.broker,
            "terminal_id": self.terminal_id,
            "symbols": self.symbols,
            "timeframe": self.timeframe,
            "bars_per_symbol": self.bars_per_symbol,
            "total_bars": self.total_bars,
            "first_timestamp": self.first_timestamp,
            "last_timestamp": self.last_timestamp,
            "retrieval_timestamp": self.retrieval_timestamp,
            "missing_bars": self.missing_bars,
            "duplicate_bars": self.duplicate_bars,
            "ohlc_violations": self.ohlc_violations,
            "snapshot_hash": self.snapshot_hash,
        }


class IntradayDataPuller:
    """Pulls 5-minute OHLCV data from MT5 via Wine/RPyC bridge."""

    def __init__(
        self,
        symbols: Optional[List[str]] = None,
        port: int = 8001,
        max_bars: int = 50000,
    ) -> None:
        self._symbols = symbols or INTRADAY_UNIVERSE
        self._port = port
        self._max_bars = max_bars

    def pull_data(
        self,
        data_dir: str = "data/intraday",
    ) -> Tuple[Dict[str, pd.DataFrame], IntradayDataManifest]:
        """Pull 5-minute bars from MT5 and run integrity checks.

        Returns (data_dict, manifest).
        """
        os.makedirs(data_dir, exist_ok=True)

        try:
            from mt5linux import MetaTrader5
            mt5 = MetaTrader5(port=self._port)
            if not mt5.initialize():
                raise ConnectionError(f"MT5 init failed: {mt5.last_error()}")

            version = mt5.version()
            account_info = mt5.account_info()
            terminal_id = str(account_info.login) if account_info else "unknown"

            data: Dict[str, pd.DataFrame] = {}
            bars_info: Dict[str, int] = {}

            for sym in self._symbols:
                info = mt5.symbol_info(sym)
                if info is None:
                    logger.warning(f"Symbol {sym} not found in MT5")
                    continue

                rates = mt5.copy_rates_from_pos(sym, TIMEFRAME_M5, 0, self._max_bars)
                if rates is None or len(rates) == 0:
                    logger.warning(f"No M5 data for {sym}")
                    continue

                df = pd.DataFrame(rates)
                df["time"] = pd.to_datetime(df["time"], unit="s")
                df = df.sort_values("time").drop_duplicates(subset=["time"]).reset_index(drop=True)

                # Standardize columns
                df = df.rename(columns={"tick_volume": "volume"})
                cols = ["time", "open", "high", "low", "close", "volume"]
                if "spread" in df.columns:
                    cols.append("spread")
                df = df[[c for c in cols if c in df.columns]]

                data[sym] = df
                bars_info[sym] = len(df)

                # Save to CSV
                df.to_csv(f"{data_dir}/{sym}_M5.csv", index=False)

                logger.info(f"  {sym}: {len(df)} bars, {df.time.min()} to {df.time.max()}")

            mt5.shutdown()

        except Exception as e:
            logger.error(f"MT5 bridge failed: {e}")
            # Fallback: try loading from CSV
            return self._load_from_csv(data_dir)

        # Run integrity checks
        all_timestamps = []
        for df in data.values():
            all_timestamps.extend(df["time"].tolist())

        missing, duplicates, ohlc_violations = self._check_integrity(data)

        first_ts = min(all_timestamps) if all_timestamps else datetime.now()
        last_ts = max(all_timestamps) if all_timestamps else datetime.now()
        total_bars = sum(len(df) for df in data.values())

        # Compute snapshot hash
        snapshot_data = {
            "broker": "Exness",
            "terminal_id": terminal_id,
            "symbols": sorted(data.keys()),
            "timeframe": "M5",
            "bars": bars_info,
            "total_bars": total_bars,
        }
        snapshot_hash = hashlib.sha256(
            json.dumps(snapshot_data, sort_keys=True).encode()
        ).hexdigest()[:16]

        manifest = IntradayDataManifest(
            broker="Exness",
            terminal_id=terminal_id,
            symbols=sorted(data.keys()),
            timeframe="M5",
            bars_per_symbol=bars_info,
            total_bars=total_bars,
            first_timestamp=str(first_ts),
            last_timestamp=str(last_ts),
            retrieval_timestamp=str(datetime.now()),
            missing_bars=missing,
            duplicate_bars=duplicates,
            ohlc_violations=ohlc_violations,
            snapshot_hash=snapshot_hash,
        )

        return data, manifest

    def _load_from_csv(
        self, data_dir: str
    ) -> Tuple[Dict[str, pd.DataFrame], IntradayDataManifest]:
        """Load from saved CSV files."""
        data: Dict[str, pd.DataFrame] = {}
        bars_info: Dict[str, int] = {}

        for sym in self._symbols:
            path = f"{data_dir}/{sym}_M5.csv"
            if os.path.exists(path):
                df = pd.read_csv(path)
                if "time" in df.columns:
                    df["time"] = pd.to_datetime(df["time"])
                else:
                    df = pd.read_csv(path, index_col=0)
                    df.index = pd.to_datetime(df.index)
                    df = df.reset_index().rename(columns={df.columns[0]: "time"})
                data[sym] = df
                bars_info[sym] = len(df)

        if not data:
            raise FileNotFoundError(f"No intraday data found in {data_dir}")

        all_timestamps = []
        for df in data.values():
            all_timestamps.extend(df["time"].tolist())

        missing, duplicates, ohlc_violations = self._check_integrity(data)
        total_bars = sum(len(df) for df in data.values())

        first_ts = min(all_timestamps) if all_timestamps else datetime.now()
        last_ts = max(all_timestamps) if all_timestamps else datetime.now()

        snapshot_data = {
            "source": "csv",
            "symbols": sorted(data.keys()),
            "timeframe": "M5",
            "bars": bars_info,
            "total_bars": total_bars,
        }
        snapshot_hash = hashlib.sha256(
            json.dumps(snapshot_data, sort_keys=True).encode()
        ).hexdigest()[:16]

        manifest = IntradayDataManifest(
            broker="Exness_csv",
            terminal_id="csv",
            symbols=sorted(data.keys()),
            timeframe="M5",
            bars_per_symbol=bars_info,
            total_bars=total_bars,
            first_timestamp=str(first_ts),
            last_timestamp=str(last_ts),
            retrieval_timestamp=str(datetime.now()),
            missing_bars=missing,
            duplicate_bars=duplicates,
            ohlc_violations=ohlc_violations,
            snapshot_hash=snapshot_hash,
        )

        return data, manifest

    def _check_integrity(
        self, data: Dict[str, pd.DataFrame]
    ) -> Tuple[int, int, int]:
        """Check for duplicates, gaps, and OHLC violations.

        Returns (missing_bars, duplicate_bars, ohlc_violations).
        """
        total_missing = 0
        total_duplicates = 0
        total_ohlc = 0

        for sym, df in data.items():
            # Duplicate timestamps
            dupes = df["time"].duplicated().sum()
            total_duplicates += int(dupes)

            # OHLC violations: High < Low, or Close outside [Low, High]
            if all(c in df.columns for c in ["open", "high", "low", "close"]):
                hl_violations = (df["high"] < df["low"]).sum()
                close_outside = (
                    (df["close"] < df["low"]) | (df["close"] > df["high"])
                ).sum()
                open_outside = (
                    (df["open"] < df["low"]) | (df["open"] > df["high"])
                ).sum()
                total_ohlc += int(hl_violations + close_outside + open_outside)

            # Gap detection (expected ~288 bars/day for M5, ~6.5h for FX)
            if len(df) > 1:
                times = df["time"].sort_values().values
                diffs = np.diff(times).astype("timedelta64[m]").astype(int)
                # M5 gaps > 60 min suggest missing data (ignoring weekends)
                gaps = (diffs > 60).sum()
                total_missing += int(gaps)

        return total_missing, total_duplicates, total_ohlc
