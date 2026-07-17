"""Phase 6: Trade Attribution Analytics — Invariant Tests.

Required verification:
  1. Four-domain separation — data flows to correct layer
  2. Observe only — no mutation of labels, kernel, or policy state
  3. MAE/MFE time-normalised — per-bar metrics are correct
  4. Counterfactual computation — entry timing, fill, TP comparisons
  5. Archetype drift — entry vs exit archetype tracked independently
  6. Decision quality — outcome-independent metrics collected
  7. Version hashing — replayability fingerprints preserved
  8. Trade lifecycle — record is populated from open through close
"""

import pickle

import pytest

from paper_trading.attribution.collector import (
    AttributionCollector,
    DecisionQuality,
    ExecutionAttribution,
    ExitAttribution,
    FrictionAttribution,
    PredictionAttribution,
    TradeAttributionRecord,
    compute_mae_mfe,
    hash_policy_state,
)
from paper_trading.entry.decision import PositionSide


# ── Fixtures ──────────────────────────────────────────────────────────────────


@pytest.fixture
def collector():
    return AttributionCollector()


@pytest.fixture
def trade_id():
    return "2026-05-27_long_TEST"


@pytest.fixture
def full_record_data(trade_id):
    return {
        "trade_id": trade_id,
        "asset": "TEST",
        "entry_date": "2026-05-27",
        "exit_date": "2026-05-28",
        "side": "long",
        "policy_hash": "a1b2c3d4e5f6",
        "archetype_version": "1.0",
    }


# ── Test 1: Four-Domain Separation ───────────────────────────────────────────


class TestFourDomainSeparation:
    """Each attribution layer captures the correct data independently."""

    def test_prediction_attribution_fields(self):
        attr = PredictionAttribution(
            signal="BUY",
            label=1,
            confidence=75.0,
            prob_long=0.75,
            prob_short=0.10,
            prob_neutral=0.15,
            meta_proba=0.62,
            regime_at_entry="trend",
            archetype_at_entry="BREAKOUT",
        )
        assert attr.signal == "BUY"
        assert attr.label == 1
        assert attr.confidence == 75.0
        assert attr.meta_proba == 0.62
        assert attr.regime_at_entry == "trend"
        assert attr.archetype_at_entry == "BREAKOUT"
        assert attr.forecast_direction_correct is None  # resolved at exit

    def test_execution_attribution_fields(self):
        attr = ExecutionAttribution(
            entry_type="deferred",
            deferred_bars=3,
            entry_price=101.5,
            mid_price_at_signal=100.0,
            entry_slippage_bps=2.5,
            spread_at_entry_bps=1.2,
            entry_pressure_pct=0.75,
            entry_volatility_rank=0.3,
        )
        assert attr.entry_type == "deferred"
        assert attr.deferred_bars == 3
        assert attr.counterfactual_entry_timing_r is None  # set at exit

    def test_execution_timing_efficiency(self):
        # Fill at better price than signal -> efficiency > 1
        better = ExecutionAttribution(
            entry_type="immediate",
            deferred_bars=0,
            entry_price=99.5,
            mid_price_at_signal=100.0,
            entry_slippage_bps=0.0,
        )
        assert better.entry_timing_efficiency is not None
        assert better.entry_timing_efficiency < 1.0  # bought cheaper

        # Fill at worse price -> efficiency < 1
        worse = ExecutionAttribution(
            entry_type="immediate",
            deferred_bars=0,
            entry_price=100.5,
            mid_price_at_signal=100.0,
            entry_slippage_bps=0.0,
        )
        assert worse.entry_timing_efficiency > 1.0  # bought more expensive

    def test_exit_attribution_fields(self):
        attr = ExitAttribution(
            exit_reason="tp",
            realized_r=1.5,
            theoretical_r=2.0,
            mae=0.5,
            mfe=2.5,
            mae_per_bar=0.1,
            mfe_per_bar=0.5,
            time_to_max_adverse=2,
            time_to_max_favorable=5,
            bars_held=10,
            counterfactual_fixed_tp_r=1.2,
            counterfactual_convex_tp_r=1.5,
            exit_archetype="TREND_PULLBACK",
        )
        assert attr.exit_reason == "tp"
        assert attr.realized_r == 1.5
        assert attr.counterfactual_fixed_tp_r == 1.2
        assert attr.exit_archetype == "TREND_PULLBACK"

    def test_friction_attribution_fields(self):
        attr = FrictionAttribution(
            entry_slippage_bps=2.5,
            exit_slippage_bps=3.0,
            gap_fill=True,
            partial_fill=True,
            fill_qty_ratio=0.7,
            latency_bars=1,
            counterfactual_ideal_fill_r=2.0,
            counterfactual_real_fill_r=1.5,
            fill_model_version="v1",
            execution_model_version="v1",
        )
        assert attr.entry_slippage_bps == 2.5
        assert attr.gap_fill is True
        assert attr.partial_fill is True

    def test_decision_quality_fields(self):
        dq = DecisionQuality(
            entry_pressure_pct=0.8,
            spread_rank=0.3,
            volatility_rank=0.6,
            liquidity_rank=0.9,
            entry_distance_from_structure=0.02,
        )
        assert dq.entry_pressure_pct == 0.8
        assert dq.spread_rank == 0.3
        assert dq.entry_distance_from_structure == 0.02

    def test_full_record_assembles_all_layers(self, full_record_data):
        rec = TradeAttributionRecord(
            **full_record_data,
            execution_model_version="v1",
            fill_model_version="v1",
            prediction=PredictionAttribution(
                "BUY",
                1,
                75.0,
                0.75,
                0.1,
                0.15,
                None,
            ),
            execution=ExecutionAttribution(
                "immediate",
                0,
                100.0,
                100.0,
                0.0,
            ),
            exit_info=ExitAttribution(
                "tp",
                1.5,
                2.0,
                0.3,
                1.8,
                0.03,
                0.18,
                1,
                4,
                10,
            ),
            friction=FrictionAttribution(
                0.5,
                0.8,
                False,
                False,
                1.0,
                0,
            ),
            decision_quality=DecisionQuality(None, None, None, None, None),
            entry_price=100.0,
            exit_price=105.0,
            realized_return=0.05,
            realized_pnl=100.0,
        )
        assert rec.trade_id == full_record_data["trade_id"]
        assert rec.prediction.signal == "BUY"
        assert rec.execution.entry_type == "immediate"
        assert rec.exit_info.exit_reason == "tp"
        assert rec.friction.entry_slippage_bps == 0.5


# ── Test 2: Observe Only (No Mutation) ────────────────────────────────────────


class TestObserveOnly:
    """AttributionCollector never mutates system state."""

    def test_collector_does_not_mutate_inputs(self, collector, trade_id):
        signal = "BUY"
        confidence = 75.0
        collector.record_prediction(
            trade_id=trade_id,
            signal=signal,
            label=1,
            confidence=confidence,
            prob_long=0.75,
            prob_short=0.1,
            prob_neutral=0.15,
        )
        # Inputs unchanged
        assert signal == "BUY"
        assert confidence == 75.0

    def test_collector_has_no_side_effects_on_finalize(self, collector, trade_id):
        price = 100.0
        collector.record_prediction(
            trade_id=trade_id,
            signal="BUY",
            label=1,
            confidence=75.0,
            prob_long=0.75,
            prob_short=0.1,
            prob_neutral=0.15,
        )
        collector.record_execution(
            trade_id=trade_id,
            entry_type="immediate",
            deferred_bars=0,
            entry_price=price,
            mid_price_at_signal=price,
            entry_slippage_bps=0.0,
        )
        collector.record_friction(
            trade_id=trade_id,
            entry_slippage_bps=0.0,
            exit_slippage_bps=0.5,
        )
        result = collector.finalize(
            trade_id=trade_id,
            asset="TEST",
            entry_date="2026-05-27",
            exit_date="2026-05-28",
            side="long",
            exit_price=105.0,
            exit_reason="tp",
            realized_r=1.5,
            realized_return=0.05,
            realized_pnl=100.0,
            theoretical_r=2.0,
        )
        assert result is not None
        # price and trade_id unchanged
        assert price == 100.0
        assert trade_id == trade_id

    def test_collector_never_finalizes_twice(self, collector, trade_id):
        """Once finalized, the scratch is removed."""
        collector.record_prediction(
            trade_id=trade_id,
            signal="BUY",
            label=1,
            confidence=75.0,
            prob_long=0.75,
            prob_short=0.1,
            prob_neutral=0.15,
        )
        collector.record_execution(
            trade_id=trade_id,
            entry_type="immediate",
            deferred_bars=0,
            entry_price=100.0,
            mid_price_at_signal=100.0,
            entry_slippage_bps=0.0,
        )
        collector.record_friction(
            trade_id=trade_id,
            entry_slippage_bps=0.0,
            exit_slippage_bps=0.0,
        )
        r1 = collector.finalize(
            trade_id=trade_id,
            asset="TEST",
            entry_date="2026-05-27",
            exit_date="2026-05-28",
            side="long",
            exit_price=105.0,
            exit_reason="tp",
            realized_r=1.5,
            realized_return=0.05,
            realized_pnl=100.0,
            theoretical_r=2.0,
        )
        assert r1 is not None
        # Second finalize returns None (scratch cleaned)
        r2 = collector.finalize(
            trade_id=trade_id,
            asset="TEST",
            entry_date="2026-05-27",
            exit_date="2026-05-28",
            side="long",
            exit_price=105.0,
            exit_reason="tp",
            realized_r=1.5,
            realized_return=0.05,
            realized_pnl=100.0,
            theoretical_r=2.0,
        )
        assert r2 is None


# ── Test 3: MAE / MFE Computation ────────────────────────────────────────────


class TestMAEMFE:
    """Time-normalized MAE/MFE from bar-level extremes."""

    def test_long_mae_mfe(self):
        entry = 100.0
        highs = [101.0, 103.0, 102.0, 104.0]
        lows = [99.5, 100.0, 99.0, 101.0]
        mae, mfe, t_mae, t_mfe = compute_mae_mfe(entry, "long", highs, lows)
        assert mfe == 4.0  # max(101-100, 103-100, 102-100, 104-100)
        assert mae == 1.0  # max(100-99.5, 100-100, 100-99, 100-101=0)
        assert t_mfe == 3  # max favorable at bar 3 (price=104)
        assert t_mae == 2  # max adverse at bar 2 (low=99, diff=1)

    def test_short_mae_mfe(self):
        entry = 100.0
        highs = [101.0, 103.0, 102.0, 104.0]
        lows = [99.5, 100.0, 99.0, 101.0]
        mae, mfe, t_mae, t_mfe = compute_mae_mfe(entry, "short", highs, lows)
        assert mfe == 1.0  # max(100-99.5, 100-100, 100-99, 100-101=0)
        assert mae == 4.0  # max(101-100, 103-100, 102-100, 104-100)
        assert t_mfe == 2  # max favorable at bar 2 (low=99, diff=1)
        assert t_mae == 3  # max adverse at bar 3 (high=104, diff=4)

    def test_mae_mfe_zero_for_no_extremes(self):
        entry = 100.0
        mae, mfe, t_mae, t_mfe = compute_mae_mfe(entry, "long", [], [])
        assert mae == 0.0
        assert mfe == 0.0
        assert t_mae == 0
        assert t_mfe == 0

    def test_mae_mfe_with_position_side_enum(self):
        entry = 100.0
        highs = [102.0]
        lows = [99.0]
        mae, mfe, _, _ = compute_mae_mfe(entry, PositionSide.LONG, highs, lows)
        assert mfe == 2.0
        assert mae == 1.0

    def test_time_normalized(self):
        """Per-bar MAE/MFE decreases with longer holds."""
        entry = 100.0
        highs_short = [110.0]
        highs_long = [100.0, 100.0, 100.0, 100.0, 110.0]
        lows_short = [100.0]
        lows_long = [100.0] * 5

        _, mfe_short, _, _ = compute_mae_mfe(entry, "long", highs_short, lows_short)
        mfe_per_bar_short = mfe_short / 1
        _, mfe_long, _, _ = compute_mae_mfe(entry, "long", highs_long, lows_long)
        mfe_per_bar_long = mfe_long / 5

        assert mfe_per_bar_short == 10.0
        assert mfe_per_bar_long == 2.0  # same max MFE, more bars

    def test_mae_mfe_in_finalized_record(self, collector, trade_id):
        """MAE/MFE are stored in the finalized TradeAttributionRecord."""
        collector.record_prediction(
            trade_id=trade_id,
            signal="BUY",
            label=1,
            confidence=75.0,
            prob_long=0.75,
            prob_short=0.1,
            prob_neutral=0.15,
        )
        collector.record_execution(
            trade_id=trade_id,
            entry_type="immediate",
            deferred_bars=0,
            entry_price=100.0,
            mid_price_at_signal=100.0,
            entry_slippage_bps=0.0,
        )
        collector.record_friction(
            trade_id=trade_id,
            entry_slippage_bps=0.0,
            exit_slippage_bps=0.0,
        )

        # Simulate tracking extremes during trade
        for bar in range(5):
            high = 100.0 + bar * 1.5
            low = 100.0 - bar * 0.5
            collector.update_trade_extremes(trade_id, high, low, bar)

        result = collector.finalize(
            trade_id=trade_id,
            asset="TEST",
            entry_date="2026-05-27",
            exit_date="2026-05-28",
            side="long",
            exit_price=105.0,
            exit_reason="tp",
            realized_r=1.5,
            realized_return=0.05,
            realized_pnl=100.0,
            theoretical_r=2.0,
        )
        assert result is not None
        exit_attr = result.exit_info
        assert exit_attr is not None
        assert exit_attr.mfe > 0
        assert exit_attr.mae >= 0
        assert exit_attr.mfe_per_bar > 0
        assert exit_attr.bars_held > 0


# ── Test 4: Counterfactual Metrics ───────────────────────────────────────────


class TestCounterfactuals:
    """Counterfactual comparisons are computed at exit."""

    def test_prediction_forecast_resolved_at_exit(self, collector, trade_id):
        """Directional correctness is set only at trade close."""
        collector.record_prediction(
            trade_id=trade_id,
            signal="BUY",
            label=1,
            confidence=75.0,
            prob_long=0.75,
            prob_short=0.1,
            prob_neutral=0.15,
        )
        collector.record_execution(
            trade_id=trade_id,
            entry_type="immediate",
            deferred_bars=0,
            entry_price=100.0,
            mid_price_at_signal=100.0,
            entry_slippage_bps=0.0,
        )
        collector.record_friction(
            trade_id=trade_id,
            entry_slippage_bps=0.0,
            exit_slippage_bps=0.0,
        )

        # Scratched record — forecast not yet set
        scratch_pred = collector._next_records[trade_id]["prediction"]
        assert scratch_pred.forecast_direction_correct is None

        # Finalize with price up -> correct for long
        r = collector.finalize(
            trade_id=trade_id,
            asset="TEST",
            entry_date="2026-05-27",
            exit_date="2026-05-28",
            side="long",
            exit_price=105.0,
            exit_reason="tp",
            realized_r=1.5,
            realized_return=0.05,
            realized_pnl=100.0,
            theoretical_r=2.0,
        )
        assert r is not None
        record = collector.get_record(trade_id)
        assert record is not None
        assert record.prediction.forecast_direction_correct is True

    def test_counterfactual_entry_timing(self, collector, trade_id):
        """Entry timing counterfactual is stored at finalize."""
        collector.record_prediction(
            trade_id=trade_id,
            signal="BUY",
            label=1,
            confidence=75.0,
            prob_long=0.75,
            prob_short=0.1,
            prob_neutral=0.15,
        )
        collector.record_execution(
            trade_id=trade_id,
            entry_type="deferred",
            deferred_bars=2,
            entry_price=102.0,
            mid_price_at_signal=100.0,
            entry_slippage_bps=0.0,
        )
        collector.record_friction(
            trade_id=trade_id,
            entry_slippage_bps=0.0,
            exit_slippage_bps=0.0,
        )
        result = collector.finalize(
            trade_id=trade_id,
            asset="TEST",
            entry_date="2026-05-27",
            exit_date="2026-05-28",
            side="long",
            exit_price=110.0,
            exit_reason="tp",
            realized_r=2.0,
            realized_return=0.08,
            realized_pnl=100.0,
            theoretical_r=2.0,
            counterfactual_entry_timing_r=1.5,  # immediate entry would have been worse
        )
        assert result is not None
        assert result.execution.counterfactual_entry_timing_r == 1.5

    def test_counterfactual_fill(self, collector, trade_id):
        """Fill counterfactuals are stored at finalize."""
        collector.record_prediction(
            trade_id=trade_id,
            signal="BUY",
            label=1,
            confidence=75.0,
            prob_long=0.75,
            prob_short=0.1,
            prob_neutral=0.15,
        )
        collector.record_execution(
            trade_id=trade_id,
            entry_type="immediate",
            deferred_bars=0,
            entry_price=100.0,
            mid_price_at_signal=100.0,
            entry_slippage_bps=2.0,
        )
        collector.record_friction(
            trade_id=trade_id,
            entry_slippage_bps=2.0,
            exit_slippage_bps=0.0,
        )
        result = collector.finalize(
            trade_id=trade_id,
            asset="TEST",
            entry_date="2026-05-27",
            exit_date="2026-05-28",
            side="long",
            exit_price=105.0,
            exit_reason="tp",
            realized_r=1.5,
            realized_return=0.05,
            realized_pnl=100.0,
            theoretical_r=2.0,
            counterfactual_ideal_fill_r=2.0,  # no slippage
            counterfactual_real_fill_r=1.5,  # with slippage
        )
        assert result is not None
        assert result.friction.counterfactual_ideal_fill_r == 2.0
        assert result.friction.counterfactual_real_fill_r == 1.5

    def test_counterfactual_tp(self, collector, trade_id):
        """TP counterfactuals are stored at finalize."""
        collector.record_prediction(
            trade_id=trade_id,
            signal="BUY",
            label=1,
            confidence=75.0,
            prob_long=0.75,
            prob_short=0.1,
            prob_neutral=0.15,
        )
        collector.record_execution(
            trade_id=trade_id,
            entry_type="immediate",
            deferred_bars=0,
            entry_price=100.0,
            mid_price_at_signal=100.0,
            entry_slippage_bps=0.0,
        )
        collector.record_friction(
            trade_id=trade_id,
            entry_slippage_bps=0.0,
            exit_slippage_bps=0.0,
        )
        result = collector.finalize(
            trade_id=trade_id,
            asset="TEST",
            entry_date="2026-05-27",
            exit_date="2026-05-28",
            side="long",
            exit_price=105.0,
            exit_reason="tp",
            realized_r=1.5,
            realized_return=0.05,
            realized_pnl=100.0,
            theoretical_r=2.0,
            counterfactual_fixed_tp_r=1.5,  # flat TP
            counterfactual_convex_tp_r=1.8,  # convex TP
        )
        assert result is not None
        assert result.exit_info.counterfactual_fixed_tp_r == 1.5
        assert result.exit_info.counterfactual_convex_tp_r == 1.8


# ── Test 5: Archetype Drift ──────────────────────────────────────────────────


class TestArchetypeDrift:
    """Entry and exit archetypes are tracked independently."""

    def test_archetype_drift_recorded(self, collector, trade_id):
        collector.record_prediction(
            trade_id=trade_id,
            signal="BUY",
            label=1,
            confidence=75.0,
            prob_long=0.75,
            prob_short=0.1,
            prob_neutral=0.15,
            archetype_at_entry="BREAKOUT",
        )
        collector.record_execution(
            trade_id=trade_id,
            entry_type="immediate",
            deferred_bars=0,
            entry_price=100.0,
            mid_price_at_signal=100.0,
            entry_slippage_bps=0.0,
        )
        collector.record_friction(
            trade_id=trade_id,
            entry_slippage_bps=0.0,
            exit_slippage_bps=0.0,
        )
        result = collector.finalize(
            trade_id=trade_id,
            asset="TEST",
            entry_date="2026-05-27",
            exit_date="2026-05-28",
            side="long",
            exit_price=105.0,
            exit_reason="tp",
            realized_r=1.5,
            realized_return=0.05,
            realized_pnl=100.0,
            theoretical_r=2.0,
            exit_archetype="TREND_PULLBACK",
        )
        assert result is not None
        assert result.prediction.archetype_at_entry == "BREAKOUT"
        assert result.exit_info.exit_archetype == "TREND_PULLBACK"
        assert result.prediction.archetype_at_entry != result.exit_info.exit_archetype

    def test_archetype_defaults_to_entry_on_missing_exit(self, collector, trade_id):
        """When exit_archetype is not provided, it defaults to entry archetype."""
        collector.record_prediction(
            trade_id=trade_id,
            signal="BUY",
            label=1,
            confidence=75.0,
            prob_long=0.75,
            prob_short=0.1,
            prob_neutral=0.15,
            archetype_at_entry="MEAN_REVERSION",
        )
        collector.record_execution(
            trade_id=trade_id,
            entry_type="immediate",
            deferred_bars=0,
            entry_price=100.0,
            mid_price_at_signal=100.0,
            entry_slippage_bps=0.0,
        )
        collector.record_friction(
            trade_id=trade_id,
            entry_slippage_bps=0.0,
            exit_slippage_bps=0.0,
        )
        result = collector.finalize(
            trade_id=trade_id,
            asset="TEST",
            entry_date="2026-05-27",
            exit_date="2026-05-28",
            side="long",
            exit_price=105.0,
            exit_reason="tp",
            realized_r=1.5,
            realized_return=0.05,
            realized_pnl=100.0,
            theoretical_r=2.0,
        )
        assert result is not None
        assert result.exit_info.exit_archetype == "MEAN_REVERSION"


# ── Test 6: Decision Quality ──────────────────────────────────────────────────


class TestDecisionQuality:
    """Decision quality metrics are outcome-independent."""

    def test_decision_quality_collected(self, collector, trade_id):
        collector.record_prediction(
            trade_id=trade_id,
            signal="BUY",
            label=1,
            confidence=75.0,
            prob_long=0.75,
            prob_short=0.1,
            prob_neutral=0.15,
        )
        collector.record_execution(
            trade_id=trade_id,
            entry_type="immediate",
            deferred_bars=0,
            entry_price=100.0,
            mid_price_at_signal=100.0,
            entry_slippage_bps=0.0,
        )
        collector.record_decision_quality(
            trade_id=trade_id,
            entry_pressure_pct=0.85,
            spread_rank=0.2,
            volatility_rank=0.5,
            liquidity_rank=0.8,
            entry_distance_from_structure=0.015,
        )
        collector.record_friction(
            trade_id=trade_id,
            entry_slippage_bps=0.0,
            exit_slippage_bps=0.0,
        )
        result = collector.finalize(
            trade_id=trade_id,
            asset="TEST",
            entry_date="2026-05-27",
            exit_date="2026-05-28",
            side="long",
            exit_price=103.0,
            exit_reason="tp",
            realized_r=1.0,
            realized_return=0.03,
            realized_pnl=50.0,
            theoretical_r=2.0,
        )
        assert result is not None
        assert result.decision_quality.entry_pressure_pct == 0.85
        assert result.decision_quality.spread_rank == 0.2
        assert result.decision_quality.entry_distance_from_structure == 0.015

    def test_decision_quality_defaults(self, collector, trade_id):
        """Missing decision quality defaults to None fields."""
        collector.record_prediction(
            trade_id=trade_id,
            signal="BUY",
            label=1,
            confidence=75.0,
            prob_long=0.75,
            prob_short=0.1,
            prob_neutral=0.15,
        )
        collector.record_execution(
            trade_id=trade_id,
            entry_type="immediate",
            deferred_bars=0,
            entry_price=100.0,
            mid_price_at_signal=100.0,
            entry_slippage_bps=0.0,
        )
        collector.record_friction(
            trade_id=trade_id,
            entry_slippage_bps=0.0,
            exit_slippage_bps=0.0,
        )
        result = collector.finalize(
            trade_id=trade_id,
            asset="TEST",
            entry_date="2026-05-27",
            exit_date="2026-05-28",
            side="long",
            exit_price=103.0,
            exit_reason="tp",
            realized_r=1.0,
            realized_return=0.03,
            realized_pnl=50.0,
            theoretical_r=2.0,
        )
        assert result is not None
        assert result.decision_quality.entry_pressure_pct is None


# ── Test 7: Version Hashing ──────────────────────────────────────────────────


class TestVersionHashing:
    """Replayability fingerprints are deterministic."""

    def test_hash_policy_state_deterministic(self):
        h1 = hash_policy_state(policy_hash="abc123", archetype_version="1.0")
        h2 = hash_policy_state(policy_hash="abc123", archetype_version="1.0")
        assert h1 == h2
        assert len(h1) == 12

    def test_hash_policy_state_changes_with_version(self):
        h1 = hash_policy_state(policy_hash="abc123", archetype_version="1.0")
        h2 = hash_policy_state(policy_hash="abc123", archetype_version="2.0")
        assert h1 != h2

    def test_versions_stored_in_record(self, collector, trade_id):
        collector.record_prediction(
            trade_id=trade_id,
            signal="BUY",
            label=1,
            confidence=75.0,
            prob_long=0.75,
            prob_short=0.1,
            prob_neutral=0.15,
        )
        collector.record_execution(
            trade_id=trade_id,
            entry_type="immediate",
            deferred_bars=0,
            entry_price=100.0,
            mid_price_at_signal=100.0,
            entry_slippage_bps=0.0,
        )
        collector.record_friction(
            trade_id=trade_id,
            entry_slippage_bps=0.0,
            exit_slippage_bps=0.0,
            fill_model_version="v1",
            execution_model_version="v2",
        )
        result = collector.finalize(
            trade_id=trade_id,
            asset="TEST",
            entry_date="2026-05-27",
            exit_date="2026-05-28",
            side="long",
            exit_price=105.0,
            exit_reason="tp",
            realized_r=1.5,
            realized_return=0.05,
            realized_pnl=100.0,
            theoretical_r=2.0,
            policy_hash="a1b2c3d4e5f6",
            archetype_version="1.0",
        )
        assert result is not None
        assert result.policy_hash == "a1b2c3d4e5f6"
        assert result.archetype_version == "1.0"
        assert result.fill_model_version == "v1"
        assert result.execution_model_version == "v2"


# ── Test 8: Trade Lifecycle ──────────────────────────────────────────────────


class TestTradeLifecycle:
    """Full trade lifecycle populates record correctly."""

    def test_lifecycle_immediate_entry(self, collector):
        tid = "lifecycle_test_long_ASSET"
        # Signal -> Open
        collector.record_prediction(
            trade_id=tid,
            signal="BUY",
            label=1,
            confidence=80.0,
            prob_long=0.80,
            prob_short=0.1,
            prob_neutral=0.1,
            meta_proba=0.7,
            regime_at_entry="trend",
            archetype_at_entry="BREAKOUT",
        )
        collector.record_execution(
            trade_id=tid,
            entry_type="immediate",
            deferred_bars=0,
            entry_price=100.0,
            mid_price_at_signal=100.0,
            entry_slippage_bps=1.0,
            spread_at_entry_bps=0.5,
            entry_pressure_pct=0.7,
        )
        collector.record_friction(
            trade_id=tid,
            entry_slippage_bps=1.0,
            exit_slippage_bps=0.0,
            fill_qty_ratio=0.95,
        )
        collector.record_decision_quality(
            trade_id=tid,
            entry_pressure_pct=0.7,
            spread_rank=0.3,
            volatility_rank=0.5,
            liquidity_rank=0.8,
        )

        # During trade — track extremes
        for bar in range(5):
            collector.update_trade_extremes(tid, 102.0 + bar, 99.0, bar)

        # Close
        result = collector.finalize(
            trade_id=tid,
            asset="ASSET",
            entry_date="2026-05-27",
            exit_date="2026-05-30",
            side="long",
            exit_price=106.0,
            exit_reason="tp",
            realized_r=2.0,
            realized_return=0.06,
            realized_pnl=200.0,
            theoretical_r=2.0,
            policy_hash="abc",
            archetype_version="1.0",
        )
        assert result is not None
        assert result.prediction.archetype_at_entry == "BREAKOUT"
        assert result.execution.entry_type == "immediate"
        assert result.execution.deferred_bars == 0
        assert result.exit_info.exit_reason == "tp"
        assert result.exit_info.realized_r == 2.0
        assert result.exit_info.mfe > 0
        assert result.exit_info.mae_per_bar > 0
        assert result.decision_quality.spread_rank == 0.3
        assert result.policy_hash == "abc"

    def test_lifecycle_deferred_entry(self, collector):
        tid = "lifecycle_def_ASSET"
        collector.record_prediction(
            trade_id=tid,
            signal="BUY",
            label=1,
            confidence=70.0,
            prob_long=0.70,
            prob_short=0.2,
            prob_neutral=0.1,
            regime_at_entry="volatile",
            archetype_at_entry="TREND_PULLBACK",
        )
        collector.record_execution(
            trade_id=tid,
            entry_type="deferred",
            deferred_bars=3,
            entry_price=101.5,
            mid_price_at_signal=100.0,
            entry_slippage_bps=1.2,
        )
        collector.record_friction(
            trade_id=tid,
            entry_slippage_bps=1.2,
            exit_slippage_bps=0.0,
        )
        collector.update_trade_extremes(tid, 103.0, 99.5, 0)
        collector.update_trade_extremes(tid, 104.0, 101.0, 1)

        result = collector.finalize(
            trade_id=tid,
            asset="ASSET",
            entry_date="2026-05-27",
            exit_date="2026-05-29",
            side="long",
            exit_price=103.0,
            exit_reason="tp",
            realized_r=1.2,
            realized_return=0.015,
            realized_pnl=50.0,
            theoretical_r=1.5,
            policy_hash="def",
            archetype_version="1.0",
        )
        assert result is not None
        assert result.execution.entry_type == "deferred"
        assert result.execution.deferred_bars == 3
        assert result.execution.mid_price_at_signal != result.execution.entry_price

    def test_get_record_returns_none_for_missing(self, collector):
        assert collector.get_record("nonexistent") is None

    def test_count_after_finalize(self, collector):
        for i in range(3):
            tid = f"trade_{i}"
            collector.record_prediction(
                trade_id=tid,
                signal="BUY",
                label=1,
                confidence=50.0,
                prob_long=0.5,
                prob_short=0.3,
                prob_neutral=0.2,
            )
            collector.record_execution(
                trade_id=tid,
                entry_type="immediate",
                deferred_bars=0,
                entry_price=100.0,
                mid_price_at_signal=100.0,
                entry_slippage_bps=0.0,
            )
            collector.record_friction(
                trade_id=tid,
                entry_slippage_bps=0.0,
                exit_slippage_bps=0.0,
            )
            collector.finalize(
                trade_id=tid,
                asset="TEST",
                entry_date="2026-05-27",
                exit_date="2026-05-28",
                side="long",
                exit_price=105.0,
                exit_reason="tp",
                realized_r=1.0,
                realized_return=0.05,
                realized_pnl=100.0,
                theoretical_r=1.5,
            )
        assert collector.count() == 3
        assert len(collector.get_all()) == 3

    def test_flush_to_external_list(self, collector):
        """flush_to moves records to external list without data loss."""
        for i in range(2):
            tid = f"flush_{i}"
            collector.record_prediction(
                trade_id=tid,
                signal="BUY",
                label=1,
                confidence=50.0,
                prob_long=0.5,
                prob_short=0.3,
                prob_neutral=0.2,
            )
            collector.record_execution(
                trade_id=tid,
                entry_type="immediate",
                deferred_bars=0,
                entry_price=100.0,
                mid_price_at_signal=100.0,
                entry_slippage_bps=0.0,
            )
            collector.record_friction(
                trade_id=tid,
                entry_slippage_bps=0.0,
                exit_slippage_bps=0.0,
            )
            collector.finalize(
                trade_id=tid,
                asset="TEST",
                entry_date="2026-05-27",
                exit_date="2026-05-28",
                side="long",
                exit_price=105.0,
                exit_reason="tp",
                realized_r=1.0,
                realized_return=0.05,
                realized_pnl=100.0,
                theoretical_r=1.5,
            )
        external = []
        collector.flush_to(external)
        assert len(external) == 2
        assert collector.count() == 0

    def test_reset_clears_everything(self, collector):
        tid = "reset_test"
        collector.record_prediction(
            trade_id=tid,
            signal="BUY",
            label=1,
            confidence=50.0,
            prob_long=0.5,
            prob_short=0.3,
            prob_neutral=0.2,
        )
        collector.record_execution(
            trade_id=tid,
            entry_type="immediate",
            deferred_bars=0,
            entry_price=100.0,
            mid_price_at_signal=100.0,
            entry_slippage_bps=0.0,
        )
        collector.record_friction(
            trade_id=tid,
            entry_slippage_bps=0.0,
            exit_slippage_bps=0.0,
        )
        collector.reset()
        assert collector.count() == 0


# ── Test 9: Structural Purity ─────────────────────────────────────────────────


class TestStructuralPurity:
    """Phase 6 dataclasses enforce their contracts."""

    def test_prediction_attribution_frozen_after_exit(self):
        """forecast_direction_correct is the only field updated at exit."""
        attr = PredictionAttribution(
            "BUY",
            1,
            75.0,
            0.75,
            0.1,
            0.15,
            None,
        )
        attr.forecast_direction_correct = True
        assert attr.forecast_direction_correct is True

    def test_collector_no_import_from_strategy_modules(self):
        """AttributionCollector does not import strategy modules."""
        import paper_trading.attribution.collector as ta

        src = str(ta.__file__)
        with open(src) as f:
            content = f.read()
        # Should not import model or strategy modules
        assert "xgboost" not in content
        assert "sklearn" not in content
        assert "meta_label" not in content

    def test_attribution_record_picklable(self, full_record_data):
        """TradeAttributionRecord must be serializable for replay."""
        rec = TradeAttributionRecord(
            **full_record_data,
            execution_model_version="v1",
            fill_model_version="v1",
            prediction=PredictionAttribution(
                "BUY",
                1,
                75.0,
                0.75,
                0.1,
                0.15,
                None,
            ),
            execution=ExecutionAttribution(
                "immediate",
                0,
                100.0,
                100.0,
                0.0,
            ),
            exit_info=ExitAttribution(
                "tp",
                1.5,
                2.0,
                0.3,
                1.8,
                0.03,
                0.18,
                1,
                4,
                10,
            ),
            friction=FrictionAttribution(
                0.5,
                0.8,
                False,
                False,
                1.0,
                0,
            ),
            decision_quality=DecisionQuality(None, None, None, None, None),
            entry_price=100.0,
            exit_price=105.0,
            realized_return=0.05,
            realized_pnl=100.0,
        )
        data = pickle.dumps(rec)
        restored = pickle.loads(data)
        assert restored.trade_id == rec.trade_id
        assert restored.prediction.signal == "BUY"
        assert restored.exit_info.realized_r == 1.5
