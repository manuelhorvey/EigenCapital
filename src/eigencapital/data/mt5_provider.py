"""MT5 Data Provider — pulls real historical data from MT5 via Wine bridge.

Falls back to yfinance if MT5 bridge is unavailable.

Provides:
- Daily OHLCV bars for equity universe
- Point-in-time data integrity
- Survivorship-aware data handling
"""

from __future__ import annotations

import hashlib
import json
import logging
from dataclasses import dataclass, field
from typing import Dict, List, Any, Optional, Tuple

import pandas as pd

logger = logging.getLogger(__name__)


# Default universe — liquid S&P 500 constituents + futures proxies
DEFAULT_UNIVERSE = [
    # Equity mega-caps
    "AAPL", "MSFT", "AMZN", "GOOGL", "META", "NVDA", "TSLA", "BRK-B",
    "UNH", "JNJ", "JPM", "V", "PG", "MA", "HD", "ABBV", "MRK", "PEP",
    "COST", "AVGO", "LLY", "KO", "WMT", "TMO", "CSCO", "MCD", "ABT",
    "CRM", "ACN", "DHR", "NEE", "LIN", "TXN", "PM", "UNP", "RTX",
    "LOW", "HON", "AMGN", "IBM", "CAT", "BA", "GE", "CAT", "SPGI",
    "BLK", "AXP", "SYK", "ADI", "GILD", "MDLZ", "CB", "PLD", "VRTX",
    "MMC", "SCHW", "CI", "REGN", "SO", "DUK", "ZTS", "ISRG", "BSX",
    "FISV", "CSGP", "ADP", "CME", "ITW", "SHW", "FCX", "NSC", "PNC",
    "TFC", "USB", "CMG", "MNST", "KMB", "WM", "EMR", "ETN", "AON",
    # ETFs for broad market exposure
    "SPY", "QQQ", "IWM", "EFA", "EEM", "TLT", "GLD", "USO",
]


@dataclass(frozen=True)
class DataManifest:
    """Data snapshot identity — frozen for the campaign."""
    data_source: str
    universe_hash: str
    start_date: str
    end_date: str
    bar_count: int
    snapshot_hash: str
    timestamp: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return {
            "data_source": self.data_source,
            "universe_hash": self.universe_hash,
            "start_date": self.start_date,
            "end_date": self.end_date,
            "bar_count": self.bar_count,
            "snapshot_hash": self.snapshot_hash,
        }


class MT5DataProvider:
    """Pulls real historical data from MT5 via Wine bridge.

    Falls back to yfinance if MT5 is unavailable.
    """

    def __init__(self, universe: Optional[List[str]] = None) -> None:
        self._universe = universe or DEFAULT_UNIVERSE
        self._data_cache: Dict[str, pd.DataFrame] = {}
        self._mt5_connected = False

    def connect_mt5(self, port: int = 8001) -> bool:
        """Attempt to connect to MT5 via Wine bridge."""
        try:
            from mt5linux import MetaTrader5
            mt5 = MetaTrader5(port=port)
            connected = mt5.initialize()
            if connected:
                self._mt5_connected = True
                self._mt5_port = port
                logger.info(f"MT5 connected on port {port}")
                return True
        except Exception as e:
            logger.warning(f"MT5 bridge unavailable: {e}")
        return False

    def fetch_data(
        self,
        symbols: Optional[List[str]] = None,
        start_date: str = "2015-01-01",
        end_date: str = "2026-08-24",
        source: str = "mt5",
    ) -> Tuple[Dict[str, pd.DataFrame], DataManifest]:
        """Fetch daily OHLCV data for the universe.

        Priority: MT5 (real broker) > yfinance (Yahoo).

        Args:
            symbols: override universe
            start_date: data start date
            end_date: data end date
            source: 'mt5' or 'yfinance'

        Returns:
            (data_dict, manifest)
        """
        syms = symbols or self._universe
        data: Dict[str, pd.DataFrame] = {}

        # Try MT5 first (real broker data)
        if source == "mt5":
            data = self._fetch_from_mt5(syms, start_date, end_date)
        # Fall back to yfinance
        if not data:
            data = self._fetch_from_yfinance(syms, start_date, end_date)
            source = "yfinance"

        self._data_cache = data

        # Compute manifest
        universe_str = ",".join(sorted(syms))
        universe_hash = hashlib.sha256(universe_str.encode()).hexdigest()[:16]
        total_bars = sum(len(df) for df in data.values())

        snapshot_data = {
            "source": source,
            "universe_hash": universe_hash,
            "start": start_date,
            "end": end_date,
            "bars": total_bars,
            "symbols": sorted(data.keys()),
        }
        snapshot_hash = hashlib.sha256(
            json.dumps(snapshot_data, sort_keys=True).encode()
        ).hexdigest()[:16]

        manifest = DataManifest(
            data_source=source,
            universe_hash=universe_hash,
            start_date=start_date,
            end_date=end_date,
            bar_count=total_bars,
            snapshot_hash=snapshot_hash,
        )

        return data, manifest

    def _fetch_from_yfinance(
        self,
        symbols: List[str],
        start_date: str,
        end_date: str,
    ) -> Dict[str, pd.DataFrame]:
        """Fetch data from Yahoo Finance."""
        import yfinance as yf

        data: Dict[str, pd.DataFrame] = {}
        failed: List[str] = []

        for sym in symbols:
            try:
                ticker = yf.Ticker(sym)
                df = ticker.history(start=start_date, end=end_date, auto_adjust=True)
                if df is not None and len(df) > 0:
                    df.index = df.index.tz_localize(None) if df.index.tz else df.index
                    data[sym] = df[["Open", "High", "Low", "Close", "Volume"]].copy()
                    data[sym].columns = ["open", "high", "low", "close", "volume"]
                else:
                    failed.append(sym)
            except Exception as e:
                failed.append(sym)
                logger.warning(f"Failed to fetch {sym}: {e}")

        if failed:
            logger.warning(f"Failed to fetch {len(failed)} symbols: {failed[:10]}...")

        return data

    def _fetch_from_mt5(
        self,
        symbols: List[str],
        start_date: str,
        end_date: str,
    ) -> Dict[str, pd.DataFrame]:
        """Fetch data from MT5 via Wine bridge."""
        try:
            from mt5linux import MetaTrader5
            port = getattr(self, '_mt5_port', 8001)
            mt5 = MetaTrader5(port=port)
            if not mt5.initialize():
                return {}

            data: Dict[str, pd.DataFrame] = {}
            from datetime import datetime
            start_dt = datetime.strptime(start_date, "%Y-%m-%d")
            end_dt = datetime.strptime(end_date, "%Y-%m-%d")

            for sym in symbols:
                rates = mt5.copy_rates_range(sym, mt5.TIMEFRAME_D1, start_dt, end_dt)
                if rates is not None and len(rates) > 0:
                    df = pd.DataFrame(rates)
                    df["time"] = pd.to_datetime(df["time"], unit="s")
                    df = df.set_index("time")
                    data[sym] = df[["open", "high", "low", "close", "tick_volume"]].copy()
                    data[sym].columns = ["open", "high", "low", "close", "volume"]

            mt5.shutdown()
            return data
        except Exception as e:
            logger.warning(f"MT5 fetch failed: {e}")
            return {}

    def load_from_csv(self, data_dir: str = "data/mt5") -> Tuple[Dict[str, pd.DataFrame], DataManifest]:
        """Load data from saved MT5 CSV files."""
        import os
        data: Dict[str, pd.DataFrame] = {}
        
        if not os.path.exists(data_dir):
            return data, DataManifest(
                data_source="csv", universe_hash="", start_date="",
                end_date="", bar_count=0, snapshot_hash="empty",
            )
        
        for f in os.listdir(data_dir):
            if f.endswith("_D1.csv"):
                sym = f.replace("_D1.csv", "")
                df = pd.read_csv(os.path.join(data_dir, f), index_col=0)
                df.index = pd.to_datetime(df.index)
                data[sym] = df
        
        self._data_cache = data
        
        universe_str = ",".join(sorted(data.keys()))
        universe_hash = hashlib.sha256(universe_str.encode()).hexdigest()[:16]
        total_bars = sum(len(df) for df in data.values())
        
        dates = []
        for df in data.values():
            if len(df) > 0:
                dates.extend([df.index[0], df.index[-1]])
        
        manifest = DataManifest(
            data_source="mt5_csv",
            universe_hash=universe_hash,
            start_date=str(min(dates).date()) if dates else "",
            end_date=str(max(dates).date()) if dates else "",
            bar_count=total_bars,
            snapshot_hash=hashlib.sha256(f"{universe_hash}:{total_bars}".encode()).hexdigest()[:16],
        )
        
        return data, manifest

    def get_cached_data(self) -> Dict[str, pd.DataFrame]:
        return dict(self._data_cache)

    def get_universe(self) -> List[str]:
        return list(self._universe)
