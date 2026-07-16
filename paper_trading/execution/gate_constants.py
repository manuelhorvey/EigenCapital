from __future__ import annotations

import logging
from pathlib import Path
from typing import Any, Final

import yaml

from paper_trading.config_manager import get_config

logger = logging.getLogger("eigencapital.gate_constants")


# ── Directional classification (shadow/observation only) ────────────────────


VALID_TIERS: frozenset[str] = frozenset(
    {"BIDIRECTIONAL", "BUY_STRONG", "SELL_STRONG", "SELL_LEANING"}
)

_DIRECTIONAL_MAP_PATH: Final[Path] = (
    Path(__file__).resolve().parent.parent.parent
    / "configs" / "domains" / "risk" / "directional_map.yaml"
)


def get_directional_classification() -> dict[str, dict[str, Any]]:
    """Return the per-asset directional classification map.

    Loaded directly from ``configs/domains/risk/directional_map.yaml``.
    This is a shadow/observation-only config: the engine LOGS per-asset
    directional constraints but does NOT enforce any direction filter from
    this map. Directional enforcement remains with the SELL_ONLY filter in
    ``SellOnlyConfig`` and the direction-conditional thresholds in
    ``sizing.yaml`` (``min_confidence_buy`` / ``min_confidence_sell``).

    Returns
    -------
    dict
        Keys are asset names (e.g. ``"EURCHF"``). Values are dicts with
        ``tier``, ``depth``, ``notes``, etc. Empty dict if the map is not
        loaded or the file is unavailable.
    """
    try:
        if _DIRECTIONAL_MAP_PATH.exists():
            data = yaml.safe_load(_DIRECTIONAL_MAP_PATH.read_text()) or {}
            return dict(data.get("assets", {}))
    except Exception:
        logger.warning("Could not load directional classification map", exc_info=True)
    return {}


def get_asset_tier(asset_name: str) -> str:
    """Return the directional tier for a single asset.

    Returns
    -------
    str
        One of ``BIDIRECTIONAL``, ``BUY_STRONG``, ``SELL_STRONG``,
        ``SELL_LEANING``, or ``"UNCLASSIFIED"`` if the asset is not
        in the map.
    """
    mapping = get_directional_classification()
    entry = mapping.get(asset_name)
    if entry and isinstance(entry, dict):
        tier = entry.get("tier", "")
        if tier in VALID_TIERS:
            return tier
    return "UNCLASSIFIED"


# ── SELL_ONLY assets (ENFORCED) ────────────────────────────────────────────


def get_sell_only_assets() -> frozenset[str]:
    """Return SELL_ONLY_ASSETS from config.

    The config source of truth lives in the domain tree (``configs/domains/``)
    under ``risk/sizing.yaml`` (``sell_only_assets`` key). Config must be loaded
    before this function is called; if it is not, an error is raised because
    silently falling back would disable the BUY inversion safety filter.

    Raises
    ------
    RuntimeError
        If config is not yet loaded or is missing the sell_only_assets field.
    """
    cfg = get_config()
    if not cfg.sell_only_assets:
        raise RuntimeError("SELL_ONLY_ASSETS not configured. Ensure the domain tree has sell_only_assets defined.")
    return cfg.sell_only_assets


# Legacy compatibility alias — prefer get_sell_only_assets() in new code.
# Kept for backward compat with existing imports; will be removed after
# all callers migrate to the function.
SELL_ONLY_ASSETS: Final[frozenset[str]] = get_sell_only_assets()

SPREAD_TIER_BPS: Final[dict[str, float]] = {
    "fx_major": 10.0,
    "fx_cross": 20.0,
    "indices": 15.0,
    "metals": 20.0,
}

SPREAD_GATE_STALENESS_SECS: Final[int] = 300
