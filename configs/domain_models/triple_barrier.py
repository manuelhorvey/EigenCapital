"""Triple-barrier configuration loader.

Phase 6 of the configuration architecture refactor. Loads
``ASSET_LABEL_PARAMS`` from ``configs/domains/ml/triple_barrier.yaml``
instead of hardcoding in :mod:`features.registry`. Falls back to the
previous hardcoded values when the YAML file is absent (preserves
import-time guarantees for downstream construction).
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
DEFAULT_PATH = REPO_ROOT / "configs" / "domains" / "ml" / "triple_barrier.yaml"


# Historical fallback — drift-detected at import time but risks config
# desync for callers without the YAML in checkout location. Matches
# features.registry.ASSET_LABEL_PARAMS prior to Phase 6.
_LEGACY_FALLBACK: dict[str, dict] = {
    "BTC": {"pt": 1.51, "sl": 0.58, "vol_method": "atr", "atr_period": 7},
    "ES": {"pt": 5.74, "sl": 1.91},
    "NQ": {"pt": 6.12, "sl": 2.04},
    "IWM": {"pt": 2.0, "sl": 2.0},
    "VIX": {"pt": 1.5, "sl": 1.5},
    "EURAUD": {"pt": 1.77, "sl": 0.54, "vol_method": "atr", "atr_period": 14},
    "GC": {"pt": 4.0, "sl": 1.0, "vol_method": "atr", "atr_period": 14},
    "AUDJPY": {"pt": 2.01, "sl": 0.52, "vol_method": "atr", "atr_period": 14},
    "USDCAD": {"pt": 3.90, "sl": 1.30, "vol_method": "atr", "atr_period": 14},
    "CHFJPY": {"pt": 2.0, "sl": 2.0, "vol_method": "atr", "atr_period": 14},
    "EURCAD": {"pt": 2.12, "sl": 0.71, "vol_method": "atr", "atr_period": 14},
    "USDJPY": {"pt": 1.97, "sl": 0.52, "vol_method": "atr", "atr_period": 14},
    "GBPCAD": {"pt": 4.34, "sl": 1.45, "vol_method": "atr", "atr_period": 14},
    "NZDJPY": {"pt": 2.02, "sl": 0.51},
    "CADJPY": {"pt": 1.65, "sl": 0.52},
    "GBPJPY": {"pt": 2.22, "sl": 0.50},
    "USDCHF": {"pt": 3.0, "sl": 0.85},
    "GBPUSD": {"pt": 1.97, "sl": 0.52},
    "EURUSD": {"pt": 1.5, "sl": 3.0},
    "AUDUSD": {"pt": 4.24, "sl": 1.41},
    "NZDUSD": {"pt": 3.87, "sl": 1.29},
    "EURGBP": {"pt": 2.0, "sl": 2.0},
    "EURJPY": {"pt": 2.0, "sl": 2.0},
    "EURCHF": {"pt": 3.0, "sl": 1.0},
    "GBPAUD": {"pt": 3.0, "sl": 1.0},
    "AUDCAD": {"pt": 2.0, "sl": 2.0},
    "AUDNZD": {"pt": 1.0, "sl": 2.0},
    "EURNZD": {"pt": 3.36, "sl": 1.12},
    "GBPNZD": {"pt": 1.0, "sl": 3.0},
    "GBPCHF": {"pt": 2.45, "sl": 0.82},
    "CADCHF": {"pt": 4.0, "sl": 1.0},
    "NZDCAD": {"pt": 5.48, "sl": 1.83},
    "NZDCHF": {"pt": 4.0, "sl": 1.0},
    "AUDCHF": {"pt": 3.5, "sl": 2.75},
    "DJI": {"pt": 4.0, "sl": 0.5},
    "CL": {"pt": 2.0, "sl": 2.0},
}

DEFAULT_VOL_METHOD = "ewm_100"
DEFAULT_ATR_PERIOD = 14


def load_triple_barrier_params(path: Path | None = None) -> dict[str, dict]:
    """Load asset label params from the domain YAML.

    Returns a dict keyed by short asset name. When the YAML file is
    absent (e.g. in stale CI clones), falls back to the legacy hardcoded
    set so downstream :class:`~features.contract.FeatureContract`
    construction still succeeds. The :mod:`tools.check_config_schema`
    validator surfaces drift between this loader and the live
    configs/domains/ml/triple_barrier.yaml asset block.
    """
    path = path or DEFAULT_PATH
    if not path.exists():
        return dict(_LEGACY_FALLBACK)

    data = yaml.safe_load(path.read_text()) or {}
    assets = data.get("assets") or {}
    legacy_block = data.get("legacy") or {}

    default_vol = legacy_block.get("default_vol_method", DEFAULT_VOL_METHOD)
    default_atr = int(legacy_block.get("default_atr_period", DEFAULT_ATR_PERIOD))

    out: dict[str, dict] = {}
    for name, raw in assets.items():
        entry: dict[str, Any] = {"pt": raw["pt"], "sl": raw["sl"]}
        if "vol_method" in raw:
            entry["vol_method"] = raw["vol_method"]
        else:
            entry["vol_method"] = default_vol
        if "atr_period" in raw:
            entry["atr_period"] = raw["atr_period"]
        else:
            entry["atr_period"] = default_atr
        if "note" in raw:
            entry["note"] = raw["note"]
        out[name] = entry
    return out
