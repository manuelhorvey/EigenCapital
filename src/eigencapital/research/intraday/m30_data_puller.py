"""Intraday M30 Data Puller — pulls 30-minute bars from MT5 via Wine/RPyC bridge.

Uses chunked copy_rates_from_pos to maximize available history.
MT5 typically provides ~50K M30 bars per symbol (~4 years).
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Dict, List, Tuple

import pandas as pd

logger = logging.getLogger(__name__)

M30_UNIVERSE = [
    "EURUSDm",
    "GBPUSDm",
    "USDJPYm",
    "AUDUSDm",
    "XAUUSDm",
    "US500m",
    "USTECm",
    "USOILm",
]

CHUNK_SIZE = 10000
MAX_BARS = 100000  # ~4+ years of M30 data
TIMEFRAME_M30 = 30  # MT5 timeframe constant for M30


@dataclass
class M30DataManifest:
    """Frozen data snapshot identity for Campaign 5 (30M research)."""

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
    zero_volume_bars: int
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
            "zero_volume_bars": self.zero_volume_bars,
            "snapshot_hash": self.snapshot_hash,
        }


def _check_integrity(data: Dict[str, pd.DataFrame]) -> Tuple[int, int, int, int]:
    """Check for duplicates, gaps, OHLC violations, and zero-volume bars."""
    total_missing = 0
    total_duplicates = 0
    total_ohlc = 0
    total_zero_vol = 0

    for sym, df in data.items():
        total_duplicates += int(df["time"].duplicated().sum())

        if "tick_volume" in df.columns:
            total_zero_vol += int((df["tick_volume"] == 0).sum())

        if all(c in df.columns for c in ["open", "high", "low", "close"]):
            hl_violations = (df["high"] < df["low"]).sum()
            close_outside = ((df["close"] < df["low"]) | (df["close"] > df["high"])).sum()
            total_ohlc += int(hl_violations + close_outside)

        if len(df) > 1:
            times = df["time"].sort_values().values
            diffs = pd.Series(times).diff().dt.total_seconds().dropna()
            # M30 gaps > 3 hours suggest missing data (ignoring weekends/holidays)
            gaps = (diffs > 10800).sum()
            total_missing += int(gaps)

    return total_missing, total_duplicates, total_ohlc, total_zero_vol


def _build_manifest(
    all_data: Dict[str, pd.DataFrame],
    bars_info: Dict[str, int],
    broker: str,
    terminal_id: str,
) -> M30DataManifest:
    """Compute integrity stats and build the frozen manifest."""
    missing, duplicates, ohlc, zero_vol = _check_integrity(all_data)

    all_timestamps: List[pd.Timestamp] = []
    for df in all_data.values():
        all_timestamps.extend(df["time"].tolist())

    total_bars = sum(len(df) for df in all_data.values())
    first_ts = min(all_timestamps) if all_timestamps else datetime.now()
    last_ts = max(all_timestamps) if all_timestamps else datetime.now()

    snapshot_data = {
        "broker": broker,
        "terminal_id": terminal_id,
        "symbols": sorted(all_data.keys()),
        "timeframe": "M30",
        "bars": bars_info,
        "total_bars": total_bars,
    }
    snapshot_hash = hashlib.sha256(json.dumps(snapshot_data, sort_keys=True).encode()).hexdigest()[:16]

    return M30DataManifest(
        broker=broker,
        terminal_id=terminal_id,
        symbols=sorted(all_data.keys()),
        timeframe="M30",
        bars_per_symbol=bars_info,
        total_bars=total_bars,
        first_timestamp=str(first_ts),
        last_timestamp=str(last_ts),
        retrieval_timestamp=str(datetime.now()),
        missing_bars=missing,
        duplicate_bars=duplicates,
        ohlc_violations=ohlc,
        zero_volume_bars=zero_vol,
        snapshot_hash=snapshot_hash,
    )


def pull_m30_data(
    symbols: List[str] | None = None,
    host: str = "127.0.0.1",
    port: int = 8001,
    output_dir: str = "data/intraday_m30",
) -> Tuple[Dict[str, pd.DataFrame], M30DataManifest]:
    """Pull M30 OHLCV data from MT5 for all symbols (CSV fallback on failure)."""
    if symbols is None:
        symbols = M30_UNIVERSE

    os.makedirs(output_dir, exist_ok=True)

    try:
        from mt5linux import MetaTrader5

        mt5 = MetaTrader5(host=host, port=port)
        if not mt5.initialize():
            raise RuntimeError(f"MT5 connection failed on {host}:{port}")

        all_data: Dict[str, pd.DataFrame] = {}
        bars_info: Dict[str, int] = {}

        try:
            account_info = mt5.account_info()
            terminal_id = str(account_info.login) if account_info else "unknown"

            for symbol in symbols:
                logger.info(f"Pulling M30 data for {symbol}...")
                all_frames: List[pd.DataFrame] = []

                for offset in range(0, MAX_BARS, CHUNK_SIZE):
                    rates = mt5.copy_rates_from_pos(symbol, TIMEFRAME_M30, offset, CHUNK_SIZE)
                    if rates is None or len(rates) == 0:
                        break
                    all_frames.append(pd.DataFrame(rates.tolist(), columns=rates.dtype.names))

                if not all_frames:
                    logger.warning(f"No M30 data for {symbol}")
                    continue

                df = pd.concat(all_frames, ignore_index=True)
                df["time"] = pd.to_datetime(df["time"], unit="s")
                df = df.drop_duplicates(subset="time").sort_values("time").reset_index(drop=True)

                logger.info(f"  {symbol}: {len(df)} M30 bars | {df['time'].iloc[0]} → {df['time'].iloc[-1]}")

                csv_path = os.path.join(output_dir, f"{symbol}_M30.csv")
                df.to_csv(csv_path, index=False)

                all_data[symbol] = df
                bars_info[symbol] = len(df)

        finally:
            mt5.shutdown()

        if not all_data:
            raise RuntimeError("No M30 data retrieved from MT5")

        manifest = _build_manifest(all_data, bars_info, "Exness", terminal_id)

    except Exception as e:
        logger.warning(f"MT5 bridge failed ({e}), loading from CSV fallback")
        return _load_from_csv(output_dir)

    manifest_path = os.path.join(output_dir, "manifest.json")
    with open(manifest_path, "w") as f:
        json.dump(manifest.to_dict(), f, indent=2)

    return all_data, manifest


def _load_from_csv(
    data_dir: str,
) -> Tuple[Dict[str, pd.DataFrame], M30DataManifest]:
    """Load from saved CSV files."""
    all_data: Dict[str, pd.DataFrame] = {}
    bars_info: Dict[str, int] = {}

    for sym in M30_UNIVERSE:
        csv_path = os.path.join(data_dir, f"{sym}_M30.csv")
        if os.path.exists(csv_path):
            df = pd.read_csv(csv_path)
            if "time" in df.columns:
                df["time"] = pd.to_datetime(df["time"])
            else:
                df = pd.read_csv(csv_path, index_col=0)
                df.index = pd.to_datetime(df.index)
                df = df.reset_index().rename(columns={df.columns[0]: "time"})
            all_data[sym] = df
            bars_info[sym] = len(df)

    if not all_data:
        raise FileNotFoundError(f"No M30 data found in {data_dir}")

    manifest = _build_manifest(all_data, bars_info, "Exness_csv", "csv")
    return all_data, manifest


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    data, manifest = pull_m30_data()
    print(f"\nSnapshot: {manifest.snapshot_hash}")
    print(f"Total bars: {manifest.total_bars}")
    for sym, n in manifest.bars_per_symbol.items():
        print(f"  {sym}: {n}")
