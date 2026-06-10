"""Single source of truth for governance multiplier computation.

Consolidates the multiplier chain (regime × narrative × liquidity) that was
previously duplicated across 4+ call sites.

Two entry points:
    - compute_effective_multipliers:  full stack including base sl/tp for engine use
    - compute_governance_multipliers: governance-only multipliers for dashboard/API
"""

from __future__ import annotations

_MIN_SIZE_FLOOR = 0.30


def compute_effective_multipliers(
    base_sl: float,
    base_tp: float,
    validity_state: str,
    regime_geometry: dict,
    narrative_sl_mult: float,
    liquidity_sl_mult: float,
    narrative_size_scalar: float,
    liquidity_size_scalar: float,
    min_size_floor: float = _MIN_SIZE_FLOOR,
) -> tuple[float, float, float]:
    """Compute effective SL, TP, and size scalar for position entry.

    Chains all governance layers on top of the base asset multipliers.
    Used by AssetEngine._open_position, _apply_decision, _poll_pending_entries.

    Returns (effective_sl_mult, effective_tp_mult, effective_size_scalar).
    """
    geom = regime_geometry.get(validity_state, {"sl_mult": 1.0, "tp_mult": 1.0})
    effective_sl = base_sl * geom.get("sl_mult", 1.0) * narrative_sl_mult * liquidity_sl_mult
    effective_sl = min(effective_sl, 10.0)
    effective_tp = base_tp * geom.get("tp_mult", 1.0) * narrative_sl_mult * liquidity_sl_mult
    effective_tp = min(effective_tp, 20.0)
    effective_size = max(narrative_size_scalar * liquidity_size_scalar, min_size_floor)
    return effective_sl, effective_tp, effective_size


def compute_governance_multipliers(
    validity_state: str,
    regime_geometry: dict,
    narrative_sl_mult: float,
    liquidity_sl_mult: float,
    narrative_size_scalar: float,
    liquidity_size_scalar: float,
    min_size_floor: float = _MIN_SIZE_FLOOR,
) -> tuple[float, float, float, float, bool]:
    """Compute governance-only multipliers for dashboard / API display.

    Shows the contribution of each governance layer (regime, narrative,
    liquidity) *without* the asset-level base sl/tp multipliers.

    Returns (regime_sl, combined_sl, regime_size, combined_size, floor_active).
    """
    geom = regime_geometry.get(validity_state, {"sl_mult": 1.0, "tp_mult": 1.0})
    regime_sl = geom.get("sl_mult", 1.0)
    regime_size = geom.get("tp_mult", 1.0)
    combined_sl = regime_sl * narrative_sl_mult * liquidity_sl_mult
    raw_size = regime_size * narrative_size_scalar * liquidity_size_scalar
    combined_size = max(raw_size, min_size_floor)
    floor_active = combined_size == min_size_floor
    return regime_sl, combined_sl, regime_size, combined_size, floor_active
