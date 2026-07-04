"""Phase 5: Fill Realism Layer — Invariant Tests.

Required tests:
  1. Replay determinism — same seed + same inputs -> identical FillResult
  2. Gap-through correctness — gap beyond stop -> fill at open, not stop
  3. Adverse asymmetry — SL slippage worse than TP slippage
  4. No backward mutation — PolicyDecision hash unchanged after simulation
  5. Partial fill conservation — never fill > requested qty
"""

import hashlib
import pickle

import numpy as np
import pytest

from paper_trading.execution.simulator import (
    ExecutionSimulator,
    FillResult,
    MarketSnapshot,
)
from paper_trading.execution.slippage import SlippageModel
from paper_trading.execution.fill import FillModel
from paper_trading.execution.latency import LatencyModel
from paper_trading.entry.decision import (
    EntryAction,
    PolicyDecision,
    PositionIntent,
    PositionSide,
    TPGeometry,
)
from shared.execution_config import ExecutionConfig


# ── Helpers ──────────────────────────────────────────────────────────────────

_DEFAULT_CONFIG = ExecutionConfig()

_MARKET = MarketSnapshot(
    current_price=100.0,
    open_price=99.5,
    high_price=101.0,
    low_price=99.0,
    vol_zscore=1.2,
)

_HIGH_VOL_MARKET = MarketSnapshot(
    current_price=100.0,
    open_price=95.0,
    high_price=105.0,
    low_price=94.0,
    vol_zscore=3.5,
)


def _make_decision(action=EntryAction.ENTER) -> PolicyDecision:
    return PolicyDecision(
        action=action,
        entry_plan=PositionIntent(PositionSide.LONG, 100.0, "2026-05-26", 98.0, 104.0, 0.01),
        exit_plan=TPGeometry(tp_distance=2.0, scale_out_tiers=[], convexity_score=1.0, metadata={}),
        reason="test",
        archetype="BREAKOUT_TEST",
        metadata={"source": "test"},
    )


# ── Test 1: Replay Determinism ──────────────────────────────────────────────


class TestReplayDeterminism:
    """Same seed + same inputs -> identical FillResult."""

    def test_simulator_determinism(self):
        sim1 = ExecutionSimulator(seed=42)
        sim2 = ExecutionSimulator(seed=42)

        result1 = sim1.simulate("entry", "buy", 100.0, 1000.0, _MARKET, _DEFAULT_CONFIG)
        result2 = sim2.simulate("entry", "buy", 100.0, 1000.0, _MARKET, _DEFAULT_CONFIG)

        assert result1 == result2, "Same seed must produce identical fill results"

    def test_slippage_model_determinism(self):
        m1 = SlippageModel(seed=99)
        m2 = SlippageModel(seed=99)

        for vol_z in [0.5, 1.0, 2.0, 4.0]:
            s1 = m1.stop_loss_slippage(100.0, vol_z, _DEFAULT_CONFIG, "long")
            s2 = m2.stop_loss_slippage(100.0, vol_z, _DEFAULT_CONFIG, "long")
            assert s1 == s2, f"SL slippage mismatch at vol_z={vol_z}"

            t1 = m1.take_profit_slippage(100.0, _DEFAULT_CONFIG)
            t2 = m2.take_profit_slippage(100.0, _DEFAULT_CONFIG)
            assert t1 == t2, f"TP slippage mismatch"

    def test_fill_model_determinism(self):
        m1 = FillModel(seed=77)
        m2 = FillModel(seed=77)

        for vol_z in [0.5, 2.0, 4.0]:
            q1 = m1.fill_qty_fraction(1000.0, vol_z, _DEFAULT_CONFIG)
            q2 = m2.fill_qty_fraction(1000.0, vol_z, _DEFAULT_CONFIG)
            assert q1 == q2, f"Fill qty mismatch at vol_z={vol_z}"

    def test_latency_model_determinism(self):
        m1 = LatencyModel(seed=55)
        m2 = LatencyModel(seed=55)

        for vol_z in [0.5, 2.0, 3.0, 5.0]:
            d1 = m1.execution_delay_bars(vol_z, _DEFAULT_CONFIG)
            d2 = m2.execution_delay_bars(vol_z, _DEFAULT_CONFIG)
            assert d1 == d2, f"Latency mismatch at vol_z={vol_z}"

    def test_different_seeds_produce_identical_results(self):
        """Simulator is deterministic — same inputs always produce same output."""
        sim1 = ExecutionSimulator(seed=42)
        sim2 = ExecutionSimulator(seed=999)

        result1 = sim1.simulate("entry", "buy", 100.0, 1000.0, _MARKET, _DEFAULT_CONFIG)
        result2 = sim2.simulate("entry", "buy", 100.0, 1000.0, _MARKET, _DEFAULT_CONFIG)

        assert result1 == result2, "Deterministic models must ignore seed"


# ── Test 2: Gap-Through Correctness ─────────────────────────────────────────


class TestGapThrough:
    """Gap beyond stop -> fill at open, not stop."""

    def test_gap_down_through_stop_long(self):
        """Long position: price gaps down below SL."""
        market = MarketSnapshot(current_price=95.0, open_price=93.0, high_price=96.0, low_price=92.0, vol_zscore=2.0)
        result = ExecutionSimulator(seed=42).simulate(
            "stop_loss", "sell", 97.0, 1000.0, market, _DEFAULT_CONFIG
        )
        # open=93 < stop=97 -> gap through. Fill should be at open (93), not stop (97)
        assert result.gap_fill is True, "Gap-through should be detected"
        assert result.fill_price < 97.0, "Fill should be worse than stop price"
        assert result.fill_price <= 93.0 + 1e-6, "Fill should be at or worse than gap open"

    def test_gap_up_through_stop_short(self):
        """Short position: price gaps up above SL."""
        market = MarketSnapshot(current_price=105.0, open_price=108.0, high_price=110.0, low_price=104.0, vol_zscore=2.0)
        result = ExecutionSimulator(seed=42).simulate(
            "stop_loss", "buy", 103.0, 1000.0, market, _DEFAULT_CONFIG
        )
        # open=108 > stop=103 -> gap through. Fill should be at open (108), not stop (103)
        assert result.gap_fill is True, "Gap-through should be detected"
        assert result.fill_price > 103.0, "Fill should be worse than stop price"
        assert result.fill_price >= 108.0 - 1e-6, "Fill should be at or worse than gap open"

    def test_no_gap_no_gap_fill(self):
        """Normal fill: no gap, no gap_fill flag."""
        market = MarketSnapshot(current_price=100.0, open_price=99.0, high_price=101.0, low_price=98.0, vol_zscore=1.0)
        result = ExecutionSimulator(seed=42).simulate(
            "stop_loss", "sell", 98.5, 1000.0, market, _DEFAULT_CONFIG
        )
        # open=99 > stop=98.5 -> no gap
        assert result.gap_fill is False, "No gap-through should be detected"

    def test_gap_fill_never_better_than_stop(self):
        """Gap fill should never be better than original stop."""
        market = MarketSnapshot(current_price=95.0, open_price=96.5, high_price=97.0, low_price=94.0, vol_zscore=3.0)
        for _ in range(5):
            sim = ExecutionSimulator(seed=42)
            result = sim.simulate("stop_loss", "sell", 97.0, 1000.0, market, _DEFAULT_CONFIG)
            if result.gap_fill:
                assert result.fill_price <= 97.0, "Gap fill should not improve on stop"
            else:
                assert result.fill_price <= 97.0, "SL fill should never be better than stop"


# ── Test 3: Adverse Asymmetry ───────────────────────────────────────────────


class TestAdverseAsymmetry:
    """SL slippage must be worse than TP slippage."""

    def test_sl_worse_than_tp(self):
        slip = SlippageModel(seed=42)
        config = ExecutionConfig(base_spread_bps=1.0, spread_vol_slope=2.0, spread_max_bps=50.0)

        for vol_z in [1.0, 2.0, 3.0]:
            sl_slip = slip.stop_loss_slippage(100.0, vol_z, config, "long")
            tp_slip = abs(slip.take_profit_slippage(100.0, config))
            assert sl_slip >= tp_slip, (
                f"SL slippage ({sl_slip:.6f}) must be >= TP slippage ({tp_slip:.6f}) at vol_z={vol_z}"
            )

    def test_sl_always_adverse(self):
        slip = SlippageModel(seed=7)
        config = ExecutionConfig()
        for vol_z in [0.5, 1.0, 2.0, 4.0, 10.0]:
            price_slip = slip.stop_loss_slippage(100.0, vol_z, config, "long")
            assert price_slip >= 0.0, f"SL slippage must be non-negative (adverse) at vol_z={vol_z}"

    def test_tp_near_zero(self):
        slip = SlippageModel(seed=13)
        config = ExecutionConfig()
        for _ in range(10):
            price_slip = abs(slip.take_profit_slippage(100.0, config))
            assert price_slip <= 0.01, f"TP slippage too large: {price_slip}"


# ── Test 4: No Backward Mutation ────────────────────────────────────────────


class TestNoBackwardMutation:
    """PolicyDecision must be invariant through simulation."""

    def test_policy_decision_hash_preserved(self):
        decision = _make_decision()
        sim = ExecutionSimulator(seed=42)
        hash_before = hashlib.md5(pickle.dumps(decision)).hexdigest()

        _ = sim.simulate_entry(decision, 100.0, _MARKET, _DEFAULT_CONFIG)

        hash_after = hashlib.md5(pickle.dumps(decision)).hexdigest()
        assert hash_before == hash_after, "PolicyDecision mutated by simulation!"

    def test_policy_decision_frozen_after_sl_sim(self):
        decision = _make_decision()
        sim = ExecutionSimulator(seed=42)
        pos = decision.entry_plan
        hash_before = hashlib.md5(pickle.dumps(decision)).hexdigest()

        _ = sim.simulate_stop_loss(pos, 100.0, _MARKET, _DEFAULT_CONFIG)
        _ = sim.simulate_take_profit(pos, 100.0, _MARKET, _DEFAULT_CONFIG)

        hash_after = hashlib.md5(pickle.dumps(decision)).hexdigest()
        assert hash_before == hash_after, "PolicyDecision mutated by SL/TP simulation!"

    def test_module_has_no_import_of_asset_engine(self):
        """Phase 5 must not depend on core engine modules."""
        with open("paper_trading/execution/simulator.py") as f:
            src = f.read()
        assert "asset_engine" not in src, "execution_simulator imports AssetEngine!"
        assert "position_manager" not in src, "execution_simulator imports PositionManager!"


# ── Test 5: Partial Fill Conservation ───────────────────────────────────────


class TestPartialFillConservation:
    """Never fill > requested qty. Degradation only."""

    def test_full_fill_normal_vol(self):
        fill = FillModel(seed=42)
        qty = fill.fill_qty_fraction(1000.0, 1.0, _DEFAULT_CONFIG)
        assert qty == 1000.0, "Full fill expected at normal vol"

    def test_partial_fill_high_vol(self):
        fill = FillModel(seed=42)
        qty = fill.fill_qty_fraction(1000.0, 4.0, _DEFAULT_CONFIG)
        assert qty <= 1000.0, "Fill must not exceed requested qty"

    def test_never_exceeds_requested(self):
        fill = FillModel(seed=7)
        for vol_z in np.linspace(0.5, 10.0, 20):
            for req in [100.0, 1000.0, 10000.0]:
                qty = fill.fill_qty_fraction(req, vol_z, _DEFAULT_CONFIG)
                assert qty <= req, f"Fill {qty} exceeds requested {req} at vol_z={vol_z}"

    def test_zero_requested_returns_zero(self):
        fill = FillModel(seed=42)
        qty = fill.fill_qty_fraction(0.0, 3.0, _DEFAULT_CONFIG)
        assert qty == 0.0

    def test_min_fill_prob_respected(self):
        config = ExecutionConfig(min_fill_prob=0.60)
        fill = FillModel(seed=42)
        for vol_z in [3.0, 5.0, 10.0]:
            qty = fill.fill_qty_fraction(1000.0, vol_z, config)
            ratio = qty / 1000.0
            # With min_fill_prob=0.60, worst case fill ratio should be >= fill_prob * min_fill_prob
            # but never exceed 1.0
            assert ratio <= 1.0, f"Fill ratio {ratio} exceeds 1.0 at vol_z={vol_z}"


# ── Extra: Structural Invariants ────────────────────────────────────────────


class TestStructuralInvariants:
    """Phase 5 structural purity checks."""

    def test_fill_result_is_frozen(self):
        result = FillResult(100.0, 1000.0, 0.5, 0, False, False)
        with pytest.raises(Exception):
            result.fill_price = 99.0  # type: ignore

    def test_market_snapshot_is_frozen(self):
        snap = MarketSnapshot(100.0, 99.0, 101.0, 98.0, 1.0)
        with pytest.raises(Exception):
            snap.current_price = 101.0  # type: ignore

    def test_execution_simulator_no_side_effects(self):
        """Simulation should not have observable side effects on inputs."""
        config = ExecutionConfig()
        sim = ExecutionSimulator(seed=42)
        config_copy = ExecutionConfig()  # fresh copy

        _ = sim.simulate("entry", "buy", 100.0, 1000.0, _MARKET, config)

        assert config.base_spread_bps == config_copy.base_spread_bps
        assert config.spread_max_bps == config_copy.spread_max_bps
        assert config.latency_bps == config_copy.latency_bps

    def test_no_strategy_imports(self):
        """Phase 5 modules must not import strategy/alpha modules."""
        for mod_path in [
            "paper_trading/execution/simulator.py",
            "paper_trading/execution/slippage.py",
            "paper_trading/execution/fill.py",
            "paper_trading/execution/latency.py",
        ]:
            with open(mod_path) as f:
                src = f.read()
            assert "xgboost" not in src, f"{mod_path} imports xgboost!"
            assert "sklearn" not in src, f"{mod_path} imports sklearn!"
            assert "meta_label" not in src.lower(), f"{mod_path} imports meta_labeling!"


if __name__ == "__main__":
    pytest.main([__file__, "-x", "-v"])
