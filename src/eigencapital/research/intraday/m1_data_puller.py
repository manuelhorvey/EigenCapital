"""Intraday M1 Data Puller — pulls 1-minute bars from MT5 via Wine/RPyC bridge.

Uses chunked copy_rates_from_pos to maximize available history.
MT5 typically provides ~100K M1 bars per symbol (~3 months).
"""

from __future__ import annotations

import logging
import os
from typing import Dict, List, Optional

import pandas as pd

logger = logging.getLogger(__name__)

# M1 universe — same 8 instruments as M5 Campaign 1/2
M1_UNIVERSE = [
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
MAX_BARS = 200000  # ~6 months of M1 data


def pull_m1_data(
    symbols: Optional[List[str]] = None,
    host: str = "127.0.0.1",
    port: int = 8001,
    output_dir: str = "data/intraday_m1",
) -> Dict[str, pd.DataFrame]:
    """Pull M1 OHLCV data from MT5 for all symbols.

    Uses chunked requests to maximize available history.
    Returns dict of symbol -> DataFrame with columns:
        time, open, high, low, close, tick_volume, spread, real_volume
    """
    if symbols is None:
        symbols = M1_UNIVERSE

    os.makedirs(output_dir, exist_ok=True)

    from mt5linux import MetaTrader5

    mt5 = MetaTrader5(host=host, port=port)
    if not mt5.initialize():
        raise RuntimeError(f"MT5 connection failed on {host}:{port}")

    all_data: Dict[str, pd.DataFrame] = {}

    try:
        for symbol in symbols:
            logger.info(f"Pulling M1 data for {symbol}...")
            all_frames: List[pd.DataFrame] = []

            for offset in range(0, MAX_BARS, CHUNK_SIZE):
                rates = mt5.copy_rates_from_pos(
                    symbol, mt5.TIMEFRAME_M1, offset, CHUNK_SIZE
                )
                if rates is None or len(rates) == 0:
                    break
                all_frames.append(
                    pd.DataFrame(rates.tolist(), columns=rates.dtype.names)
                )

            if not all_frames:
                logger.warning(f"No M1 data for {symbol}")
                continue

            df = pd.concat(all_frames, ignore_index=True)
            df["time"] = pd.to_datetime(df["time"], unit="s")
            df = (
                df.drop_duplicates(subset="time")
                .sort_values("time")
                .reset_index(drop=True)
            )

            logger.info(
                f"  {symbol}: {len(df)} M1 bars | "
                f"{df['time'].iloc[0]} → {df['time'].iloc[-1]}"
            )

            # Save to CSV
            csv_path = os.path.join(output_dir, f"{symbol}_M1.csv")
            df.to_csv(csv_path, index=False)

            all_data[symbol] = df

    finally:
        mt5.shutdown()

    return all_data


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    data = pull_m1_data()
    for sym, df in data.items():
        print(f"{sym}: {len(df)} bars")
