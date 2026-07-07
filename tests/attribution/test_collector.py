"""Tests for paper_trading/attribution/collector.py."""

from __future__ import annotations

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


class TestPredictionAttribution:
    def test_to_dict(self):
        pred = PredictionAttribution(
            signal="BUY", label=1, confidence=0.8,
            prob_long=0.8, prob_short=0.15, prob_neutral=0.05, meta_proba=None,
        )
        d = pred.to_dict()
        assert d["signal"] == "BUY"
        assert d["confidence"] == 0.8
        assert d["forecast_direction_correct"] is None


class TestExecutionAttribution:
    def test_timing_efficiency(self):
        exec_attr = ExecutionAttribution(
            entry_type="immediate", deferred_bars=0,
            entry_price=1.0500, mid_price_at_signal=1.0000,
            entry_slippage_bps=5.0,
        )
        eff = exec_attr.entry_timing_efficiency
        assert eff == pytest.approx(1.05)


class TestExitAttribution:
    def test_to_dict(self):
        exit_info = ExitAttribution(
            exit_reason="TP", realized_r=2.0, theoretical_r=2.0,
            mae=0.5, mfe=3.0, mae_per_bar=0.1, mfe_per_bar=0.6,
            time_to_max_adverse=2, time_to_max_favorable=5, bars_held=10,
        )
        d = exit_info.to_dict()
        assert d["exit_reason"] == "TP"
        assert d["realized_r"] == 2.0


class TestFrictionAttribution:
    def test_to_dict(self):
        friction = FrictionAttribution(
            entry_slippage_bps=1.0, exit_slippage_bps=2.0,
            gap_fill=False, partial_fill=False, fill_qty_ratio=1.0, latency_bars=0,
        )
        d = friction.to_dict()
        assert d["entry_slippage_bps"] == 1.0


class TestTradeAttributionRecord:
    def test_to_dict_flattens_all_fields(self):
        pred = PredictionAttribution(
            signal="BUY", label=1, confidence=0.8,
            prob_long=0.8, prob_short=0.15, prob_neutral=0.05, meta_proba=None,
        )
        exec_attr = ExecutionAttribution(
            entry_type="immediate", deferred_bars=0,
            entry_price=1.0500, mid_price_at_signal=1.0000,
            entry_slippage_bps=5.0,
        )
        exit_info = ExitAttribution(
            exit_reason="TP", realized_r=2.0, theoretical_r=2.0,
            mae=0.5, mfe=3.0, mae_per_bar=0.1, mfe_per_bar=0.6,
            time_to_max_adverse=2, time_to_max_favorable=5, bars_held=10,
        )
        friction = FrictionAttribution(
            entry_slippage_bps=1.0, exit_slippage_bps=2.0,
            gap_fill=False, partial_fill=False, fill_qty_ratio=1.0, latency_bars=0,
        )
        dq = DecisionQuality(0.5, 0.3, 0.7, 0.9, 0.1)
        record = TradeAttributionRecord(
            trade_id="abc123", asset="EURUSD",
            entry_date="2026-07-01", exit_date="2026-07-07",
            side="long", policy_hash="hash1", archetype_version="v1",
            execution_model_version="v1", fill_model_version="v1",
            prediction=pred, execution=exec_attr, exit_info=exit_info,
            friction=friction, decision_quality=dq,
            entry_price=1.0500, exit_price=1.0700,
            realized_return=0.02, realized_pnl=200.0,
        )
        d = record.to_dict()
        assert d["trade_id"] == "abc123"
        assert d["pred_signal"] == "BUY"
        assert d["exec_entry_price"] == 1.0500
        assert d["exit_exit_reason"] == "TP"
        assert d["friction_entry_slippage_bps"] == 1.0
        assert d["dq_entry_pressure_pct"] == 0.5
        assert all(k.startswith(("pred_", "exec_", "exit_", "friction_", "dq_")) or k in (
            "trade_id", "asset", "entry_date", "exit_date", "side",
            "policy_hash", "archetype_version", "execution_model_version",
            "fill_model_version", "entry_price", "exit_price",
            "realized_return", "realized_pnl", "created_at", "experiment_id",
        ) for k in d.keys())


class TestComputeMaeMfe:
    def test_long_trade(self):
        mae, mfe, time_mae, time_mfe = compute_mae_mfe(
            entry_price=100.0, side="long",
            high_prices=[101.0, 102.0, 103.0],
            low_prices=[99.0, 98.0, 99.5],
        )
        assert mfe == 3.0  # max high - entry
        assert mae == 2.0  # max entry - low
        assert time_mfe == 2  # index of 103.0
        assert time_mae == 1  # index of 98.0

    def test_short_trade(self):
        mae, mfe, time_mae, time_mfe = compute_mae_mfe(
            entry_price=100.0, side="short",
            high_prices=[102.0, 101.0, 103.0],
            low_prices=[99.0, 98.0, 97.0],
        )
        assert mfe == 3.0  # max entry - low = 100 - 97 = 3
        assert mae == 3.0  # max high - entry = 103 - 100 = 3

    def test_empty_lists_returns_zero(self):
        mae, mfe, time_mae, time_mfe = compute_mae_mfe(100.0, "long", [], [])
        assert mae == 0.0
        assert mfe == 0.0


class TestAttributionCollector:
    def test_initial_state(self):
        collector = AttributionCollector()
        assert collector.count() == 0
        assert collector.get_all() == []

    def test_record_prediction(self):
        collector = AttributionCollector()
        collector.record_prediction(
            trade_id="t1", signal="BUY", label=1, confidence=0.8,
            prob_long=0.8, prob_short=0.15, prob_neutral=0.05,
        )
        # Not finalized yet
        assert collector.count() == 0

    def test_full_lifecycle(self):
        collector = AttributionCollector()
        collector.record_prediction(
            trade_id="t1", signal="BUY", label=1, confidence=0.8,
            prob_long=0.8, prob_short=0.15, prob_neutral=0.05,
        )
        collector.record_execution(
            trade_id="t1", entry_type="immediate", deferred_bars=0,
            entry_price=1.0500, mid_price_at_signal=1.0000,
            entry_slippage_bps=5.0,
        )
        collector.record_friction(
            trade_id="t1", entry_slippage_bps=1.0, exit_slippage_bps=2.0,
        )
        collector.record_decision_quality(
            trade_id="t1", entry_pressure_pct=0.5,
        )
        collector.update_trade_extremes("t1", high=1.0600, low=1.0400, bar_index=1)
        collector.update_trade_extremes("t1", high=1.0700, low=1.0450, bar_index=2)

        record = collector.finalize(
            trade_id="t1", asset="EURUSD",
            entry_date="2026-07-01", exit_date="2026-07-07",
            side="long", exit_price=1.0700, exit_reason="TP",
            realized_r=2.0, realized_return=0.02, realized_pnl=200.0,
            theoretical_r=2.0,
        )
        assert record is not None
        assert record.trade_id == "t1"
        assert record.prediction.signal == "BUY"
        assert record.execution.entry_price == 1.0500
        assert record.exit_info.exit_reason == "TP"
        assert record.exit_info.realized_r == 2.0
        assert collector.count() == 1

    def test_finalize_without_prediction_returns_none(self):
        collector = AttributionCollector()
        record = collector.finalize(
            trade_id="t1", asset="EURUSD",
            entry_date="", exit_date="",
            side="long", exit_price=0.0, exit_reason="SL",
            realized_r=-1.0, realized_return=-0.01, realized_pnl=-100.0,
            theoretical_r=2.0,
        )
        assert record is None

    def test_get_record(self):
        collector = AttributionCollector()
        assert collector.get_record("nonexistent") is None

    def test_flush_to(self):
        collector = AttributionCollector()
        collector.record_prediction(
            trade_id="t1", signal="BUY", label=1, confidence=0.8,
            prob_long=0.8, prob_short=0.15, prob_neutral=0.05,
        )
        collector.record_execution(
            trade_id="t1", entry_type="immediate", deferred_bars=0,
            entry_price=1.0500, mid_price_at_signal=1.0000,
            entry_slippage_bps=5.0,
        )
        collector.record_friction(
            trade_id="t1", entry_slippage_bps=1.0, exit_slippage_bps=2.0,
        )
        collector.record_decision_quality(trade_id="t1")
        collector.finalize(
            trade_id="t1", asset="EURUSD",
            entry_date="", exit_date="",
            side="long", exit_price=0.0, exit_reason="TP",
            realized_r=1.0, realized_return=0.01, realized_pnl=100.0,
            theoretical_r=2.0,
        )

        external = []
        collector.flush_to(external)
        assert len(external) == 1
        assert collector.count() == 0

    def test_reset(self):
        collector = AttributionCollector()
        collector.record_prediction(
            trade_id="t1", signal="BUY", label=1, confidence=0.8,
            prob_long=0.8, prob_short=0.15, prob_neutral=0.05,
        )
        collector.record_execution(
            trade_id="t1", entry_type="immediate", deferred_bars=0,
            entry_price=1.0500, mid_price_at_signal=1.0000,
            entry_slippage_bps=5.0,
        )
        collector.record_friction(
            trade_id="t1", entry_slippage_bps=1.0, exit_slippage_bps=2.0,
        )
        collector.record_decision_quality(trade_id="t1")
        collector.reset()
        assert collector.count() == 0


class TestHashPolicyState:
    def test_returns_12_char_hash(self):
        h = hash_policy_state("abc", "v1")
        assert len(h) == 12

    def test_deterministic(self):
        assert hash_policy_state("abc", "v1") == hash_policy_state("abc", "v1")
