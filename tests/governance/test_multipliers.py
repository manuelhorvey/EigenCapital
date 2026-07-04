"""Tests for governance multiplier computation.

Covers the TP-multiplier bug fix: narrative_sl_mult and liquidity_sl_mult
must NOT propagate to effective_tp, since they are SL-specific governance
multipliers (widens SL during risk-off, not TP).
"""

from paper_trading.governance.multipliers import compute_effective_multipliers


def test_tp_not_scaled_by_sl_multipliers():
    """effective_tp must be invariant under narrative_sl_mult / liquidity_sl_mult.

    The reviewer finding (2026-06-25) showed that compute_effective_multipliers
    was multiplying TP by SL-specific multipliers, silently widening TP whenever
    governance widened SL for risk-off conditions.
    """
    result_a = compute_effective_multipliers(
        base_sl=2.0,
        base_tp=2.5,
        validity_state="YELLOW",
        regime_geometry={},
        narrative_sl_mult=1.0,
        liquidity_sl_mult=1.0,
        narrative_size_scalar=1.0,
        liquidity_size_scalar=1.0,
    )
    result_b = compute_effective_multipliers(
        base_sl=2.0,
        base_tp=2.5,
        validity_state="YELLOW",
        regime_geometry={},
        narrative_sl_mult=2.0,  # doubled — should NOT affect TP
        liquidity_sl_mult=3.0,  # tripled — should NOT affect TP
        narrative_size_scalar=1.0,
        liquidity_size_scalar=1.0,
    )

    # SL should differ (wider SL)
    assert result_b[0] != result_a[0], "SL multipliers must affect effective_sl"

    # TP must be identical — untouched by SL-specific multipliers
    assert result_b[1] == result_a[1], (
        f"TP must NOT be affected by SL multipliers: tp_a={result_a[1]} tp_b={result_b[1]}"
    )


def test_tp_scaled_by_regime_geometry():
    """effective_tp must respond to regime tp_mult (the intended path)."""
    result = compute_effective_multipliers(
        base_sl=2.0,
        base_tp=2.5,
        validity_state="STRESSED",
        regime_geometry={"STRESSED": {"sl_mult": 1.5, "tp_mult": 2.0}},
        narrative_sl_mult=1.0,
        liquidity_sl_mult=1.0,
        narrative_size_scalar=1.0,
        liquidity_size_scalar=1.0,
    )
    # tp = 2.5 * 2.0 = 5.0  (regime tp_mult=2.0 applied)
    assert result[1] == 5.0, f"Expected TP=5.0, got {result[1]}"


def test_sl_scaled_by_narrative_and_liquidity():
    """effective_sl must respond to both regime, narrative, and liquidity."""
    result = compute_effective_multipliers(
        base_sl=2.0,
        base_tp=2.5,
        validity_state="STRESSED",
        regime_geometry={"STRESSED": {"sl_mult": 1.5, "tp_mult": 2.0}},
        narrative_sl_mult=2.0,
        liquidity_sl_mult=3.0,
        narrative_size_scalar=1.0,
        liquidity_size_scalar=0.5,
    )
    # sl = 2.0 * 1.5 * 2.0 * 3.0 = 18.0, capped at 10.0
    assert result[0] == 10.0, f"Expected SL=10.0 (capped), got {result[0]}"


def test_default_geometry_when_state_not_found():
    """Unknown validity states should fall back to 1.0 multipliers."""
    result = compute_effective_multipliers(
        base_sl=2.0,
        base_tp=2.5,
        validity_state="UNKNOWN_STATE",
        regime_geometry={},
        narrative_sl_mult=1.0,
        liquidity_sl_mult=1.0,
        narrative_size_scalar=1.0,
        liquidity_size_scalar=1.0,
    )
    assert result[0] == 2.0, f"Expected SL=2.0, got {result[0]}"
    assert result[1] == 2.5, f"Expected TP=2.5, got {result[1]}"
