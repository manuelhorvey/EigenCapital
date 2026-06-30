import json
import logging
from dataclasses import asdict, dataclass
from datetime import datetime

import numpy as np
import pandas as pd

logger = logging.getLogger("quorrin.liquidity_regime")


@dataclass
class LiquidityRegimeSnapshot:
    timestamp: str
    regime: str
    volume_z: float
    amihud_z: float
    spread_est_bps: float
    sl_mult: float
    size_scalar: float
    halted: bool = False


def compute_liquidity_features(df: pd.DataFrame, window: int = 21, min_samples: int = 60) -> dict[str, float]:
    close = df["close"].ffill()
    volume = df["volume"].replace(0, np.nan).ffill()
    high = df["high"].ffill()
    low = df["low"].ffill()

    if len(close) < min_samples:
        logger.warning(
            "Liquidity features: insufficient data (%d rows < %d min_samples), returning neutral",
            len(close),
            min_samples,
        )
        return {"volume_z": 0.0, "amihud_z": 0.0, "spread_est_bps": 0.0}
    if len(close) < window + 2:
        return {"volume_z": 0.0, "amihud_z": 0.0, "spread_est_bps": 0.0}

    returns = close.pct_change().replace([np.inf, -np.inf], 0.0).fillna(0.0)

    dollar_vol = volume * close
    with np.errstate(divide="ignore", invalid="ignore"):
        amihud = (returns.abs() / dollar_vol).replace([np.inf, -np.inf], 0.0).fillna(0.0)

    vol_mean = volume.rolling(window, min_periods=10).mean()
    vol_std = volume.rolling(window, min_periods=10).std().replace(0, 1.0)
    volume_z = ((volume - vol_mean) / vol_std).iloc[-1]
    if np.isnan(volume_z) or np.isinf(volume_z):
        volume_z = 0.0

    amihud_mean = amihud.rolling(window, min_periods=10).mean()
    amihud_std = amihud.rolling(window, min_periods=10).std().replace(0, 1e-12)
    amihud_z = ((amihud - amihud_mean) / amihud_std).iloc[-1]
    if np.isnan(amihud_z) or np.isinf(amihud_z):
        amihud_z = 0.0

    dp = np.log(high / low).replace([np.inf, -np.inf], 0.0).fillna(0.0)
    dp_sq = dp**2

    alpha = dp_sq.rolling(2).sum().iloc[-1] if len(dp_sq) >= 2 else 0.0
    spread = 2 * (np.exp(np.clip(alpha, -5, 5)) - 1) if alpha < 0 else 0.0
    spread_bps = float(spread * 10_000) if not np.isnan(spread) else 0.0

    return {
        "volume_z": round(float(volume_z), 4),
        "amihud_z": round(float(amihud_z), 4),
        "spread_est_bps": round(spread_bps, 2),
    }


def classify_liquidity_regime(
    features: dict[str, float],
    vol_thin_threshold: float = -1.5,
    vol_stressed_threshold: float = -3.0,
    amihud_high_threshold: float = 1.5,
    amihud_stressed_threshold: float = 4.0,
) -> str:
    vz = features.get("volume_z", 0.0)
    az = features.get("amihud_z", 0.0)

    if vz <= vol_stressed_threshold or az >= amihud_stressed_threshold:
        return "STRESSED"
    if vz <= vol_thin_threshold or az >= amihud_high_threshold:
        return "THIN"
    return "NORMAL"


def liquidity_governance_scalars(
    regime: str,
    features: dict[str, float] | None = None,
    thin_sl_widen_pct: float = 15.0,
    thin_size_reduce_pct: float = 15.0,
    stressed_sl_widen_pct: float = 30.0,
    stressed_size_reduce_pct: float = 30.0,
) -> dict:
    base = {"sl_mult": 1.0, "size_scalar": 1.0, "halted": False}
    if regime == "THIN":
        base["sl_mult"] = 1.0 + thin_sl_widen_pct / 100.0
        base["size_scalar"] = 1.0 - thin_size_reduce_pct / 100.0
    elif regime == "STRESSED":
        base["sl_mult"] = 1.0 + stressed_sl_widen_pct / 100.0
        base["size_scalar"] = 1.0 - stressed_size_reduce_pct / 100.0
        base["halted"] = True
    return base


def load_liquidity_json(path: str) -> LiquidityRegimeSnapshot | None:
    try:
        with open(path) as f:
            data = json.load(f)
        return LiquidityRegimeSnapshot(**data)
    except (FileNotFoundError, json.JSONDecodeError, TypeError):
        return None


def save_liquidity_json(path: str, snapshot: LiquidityRegimeSnapshot) -> None:
    with open(path, "w") as f:
        json.dump(asdict(snapshot), f, indent=2, default=str)


def neutral_liquidity() -> LiquidityRegimeSnapshot:
    return LiquidityRegimeSnapshot(
        timestamp=datetime.now().isoformat(),
        regime="NORMAL",
        volume_z=0.0,
        amihud_z=0.0,
        spread_est_bps=0.0,
        sl_mult=1.0,
        size_scalar=1.0,
    )
