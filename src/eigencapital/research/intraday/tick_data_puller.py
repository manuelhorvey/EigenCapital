"""Tick Data Puller — real broker tick quotes from MT5 via Wine/RPyC bridge.

Pulls COPY_TICKS_ALL quote ticks (bid/ask/ms timestamps) chunked by day and
aggregates ON THE FLY into M5 microstructure bars so raw tick volume never
accumulates in memory.

IMPORTANT LABELLING: this is BROKER-SPECIFIC MICROSTRUCTURE (Exness quote
flow). It is NOT centralized institutional order flow. All downstream
research must carry that label.

Snapshot policy: raw ticks are NOT persisted (tens of GB). The immutable
snapshot is the aggregated M5 microstructure bar set, hashed into the
manifest together with per-symbol tick counts.
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional, Tuple

import numpy as np
import pandas as pd

logger = logging.getLogger(__name__)

TICK_UNIVERSE = [
    "EURUSDm", "GBPUSDm", "USDJPYm", "AUDUSDm",
    "XAUUSDm", "US500m", "USTECm", "USOILm",
]

BAR_FREQ = "5min"
BARS_PER_DAY = 288  # 24h market / 5min


@dataclass
class TickDataManifest:
    """Frozen snapshot identity for Campaign 7 (broker microstructure)."""

    broker: str
    terminal_id: str
    symbols: List[str]
    info_source: str          # fixed label: broker-specific microstructure
    bar_freq: str
    days_requested: int
    bars_per_symbol: Dict[str, int]
    ticks_per_symbol: Dict[str, int]
    total_ticks: int
    first_bar: str
    last_bar: str
    retrieval_timestamp: str
    snapshot_hash: str

    def to_dict(self) -> Dict[str, Any]:
        return self.__dict__.copy()


def aggregate_tick_chunk(ticks: np.ndarray) -> pd.DataFrame:
    """Aggregate a raw MT5 tick array into M5 microstructure feature bars.

    Features per bar (all backward-looking by construction):
      n_ticks        — tick arrival count (intensity)
      up_frac        — fraction of mid-price upticks
      dn_frac        — fraction of mid-price downticks
      signed_flow    — up_frac − dn_frac (quote-flow imbalance)
      spread_mean_bps, spread_max_bps — bid/ask spread dynamics
      mid_open, mid_close, mid_high, mid_low — mid-price OHLC
      mid_ret        — intra-bar mid return
    """
    if ticks is None or len(ticks) == 0:
        return pd.DataFrame()

    df = pd.DataFrame(ticks.tolist(), columns=ticks.dtype.names)
    ts = pd.to_datetime(df["time_msc"], unit="ms")
    bid = df["bid"].astype(float)
    ask = df["ask"].astype(float)
    valid = (bid > 0) & (ask > 0)
    df = df.loc[valid]
    ts = ts.loc[valid]
    if df.empty:
        return pd.DataFrame()

    bid = df["bid"].astype(float).to_numpy()
    ask = df["ask"].astype(float).to_numpy()
    mid = (bid + ask) / 2.0
    spread_bps = (ask - bid) / mid * 1e4

    tdf = pd.DataFrame(
        {
            "mid": mid,
            "spread_bps": spread_bps,
            "up": np.r_[False, np.diff(mid) > 0].astype(float),
            "dn": np.r_[False, np.diff(mid) < 0].astype(float),
        },
        index=ts,
    )

    g = tdf.resample(BAR_FREQ)
    agg = pd.DataFrame({
        "n_ticks": g["mid"].size(),
        "up_frac": g["up"].mean(),
        "dn_frac": g["dn"].mean(),
        "spread_mean_bps": g["spread_bps"].mean(),
        "spread_max_bps": g["spread_bps"].max(),
        "mid_open": g["mid"].first(),
        "mid_high": g["mid"].max(),
        "mid_low": g["mid"].min(),
        "mid_close": g["mid"].last(),
    })
    agg = agg.dropna(subset=["mid_close"])
    agg["signed_flow"] = agg["up_frac"] - agg["dn_frac"]
    agg["mid_ret"] = agg["mid_close"] / agg["mid_open"] - 1.0
    agg = agg[(agg["n_ticks"] > 0)]
    agg = agg.reset_index()
    agg = agg.rename(columns={agg.columns[0]: "time"})
    return agg


def pull_tick_data(
    symbols: Optional[List[str]] = None,
    host: str = "127.0.0.1",
    port: int = 8001,
    days: int = 365,
    output_dir: str = "data/tick_micro_m5",
) -> Tuple[Dict[str, pd.DataFrame], TickDataManifest]:
    """Pull tick quotes for all symbols; write aggregated M5 bars + manifest.

    Falls back to previously saved CSVs when the bridge is unavailable.
    """
    if symbols is None:
        symbols = TICK_UNIVERSE

    os.makedirs(output_dir, exist_ok=True)

    try:
        from mt5linux import MetaTrader5

        mt5 = MetaTrader5(host=host, port=port)
        if not mt5.initialize():
            raise RuntimeError(f"MT5 connection failed on {host}:{port}")

        all_data: Dict[str, pd.DataFrame] = {}
        bars_info: Dict[str, int] = {}
        ticks_info: Dict[str, int] = {}
        firsts, lasts = [], []
        terminal_id = "unknown"

        try:
            acct = mt5.account_info()
            terminal_id = str(acct.login) if acct else "unknown"
            now = datetime.now()

            for symbol in symbols:
                logger.info(f"Pulling ticks for {symbol} ({days}d)...")
                chunks: List[pd.DataFrame] = []
                total_ticks = 0
                day_start = now - timedelta(days=days)

                cur = day_start
                while cur < now:
                    nxt = min(cur + timedelta(days=1), now)
                    try:
                        tk = mt5.copy_ticks_range(symbol, cur, nxt, mt5.COPY_TICKS_ALL)
                    except Exception:
                        tk = None
                    if tk is not None and len(tk):
                        total_ticks += len(tk)
                        agg = aggregate_tick_chunk(tk)
                        if not agg.empty:
                            chunks.append(agg)
                    cur = nxt

                if not chunks:
                    logger.warning(f"No tick data for {symbol}")
                    continue

                bars = pd.concat(chunks, ignore_index=True)
                bars = (
                    bars.drop_duplicates(subset="time")
                    .sort_values("time")
                    .reset_index(drop=True)
                )
                csv_path = os.path.join(output_dir, f"{symbol}_M5micro.csv")
                bars.to_csv(csv_path, index=False)

                all_data[symbol] = bars
                bars_info[symbol] = len(bars)
                ticks_info[symbol] = total_ticks
                firsts.append(bars["time"].iloc[0])
                lasts.append(bars["time"].iloc[-1])
                logger.info(f"  {symbol}: {total_ticks} ticks → {len(bars)} M5 bars")

        finally:
            mt5.shutdown()

        if not all_data:
            raise RuntimeError("No tick data retrieved from MT5")

        manifest = _build_manifest(
            all_data, bars_info, ticks_info, days, "Exness", terminal_id
        )

    except Exception as e:
        logger.warning(f"MT5 bridge failed ({e}); loading CSV fallback")
        return _load_from_csv(output_dir)

    with open(os.path.join(output_dir, "manifest.json"), "w") as f:
        json.dump(manifest.to_dict(), f, indent=2)

    return all_data, manifest


def _build_manifest(
    all_data: Dict[str, pd.DataFrame],
    bars_info: Dict[str, int],
    ticks_info: Dict[str, int],
    days: int,
    broker: str,
    terminal_id: str,
) -> TickDataManifest:
    total_ticks = sum(ticks_info.values())
    firsts = [df["time"].iloc[0] for df in all_data.values()]
    lasts = [df["time"].iloc[-1] for df in all_data.values()]

    snap = {
        "broker": broker,
        "terminal_id": terminal_id,
        "symbols": sorted(all_data.keys()),
        "bar_freq": BAR_FREQ,
        "bars": bars_info,
        "ticks": ticks_info,
        "total_ticks": total_ticks,
    }
    h = hashlib.sha256(json.dumps(snap, sort_keys=True).encode()).hexdigest()[:16]

    return TickDataManifest(
        broker=broker,
        terminal_id=terminal_id,
        symbols=sorted(all_data.keys()),
        info_source="broker_specific_microstructure_exness_quotes",
        bar_freq=BAR_FREQ,
        days_requested=days,
        bars_per_symbol=bars_info,
        ticks_per_symbol=ticks_info,
        total_ticks=total_ticks,
        first_bar=str(min(firsts)) if firsts else "",
        last_bar=str(max(lasts)) if lasts else "",
        retrieval_timestamp=str(datetime.now()),
        snapshot_hash=h,
    )


def _load_from_csv(
    output_dir: str,
) -> Tuple[Dict[str, pd.DataFrame], TickDataManifest]:
    all_data: Dict[str, pd.DataFrame] = {}
    bars_info: Dict[str, int] = {}
    for sym in TICK_UNIVERSE:
        p = os.path.join(output_dir, f"{sym}_M5micro.csv")
        if os.path.exists(p):
            df = pd.read_csv(p, parse_dates=["time"])
            all_data[sym] = df
            bars_info[sym] = len(df)
    if not all_data:
        raise FileNotFoundError(f"No microstructure bars found in {output_dir}")
    manifest = _build_manifest(all_data, bars_info, {}, 0, "Exness_csv", "csv")
    return all_data, manifest


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    data, m = pull_tick_data(days=365)
    print(f"\nSnapshot: {m.snapshot_hash}")
    print(f"Total ticks: {m.total_ticks:,}")
    print(f"Info source: {m.info_source}")
    for sym, n in m.bars_per_symbol.items():
        print(f"  {sym}: {n} M5 bars ({m.ticks_per_symbol.get(sym, 0):,} ticks)")
