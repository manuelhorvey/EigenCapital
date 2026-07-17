"""Tests for shared/metrics/attribution.py."""

from __future__ import annotations

import pytest

from shared.metrics.attribution import (
    compute_aggregate_domain_scores,
    compute_domain_scores,
    compute_waterfall,
)


class TestComputeDomainScores:
    def test_correct_long_prediction(self):
        scores = compute_domain_scores(
            {
                "pred_confidence": 0.80,
                "pred_forecast_direction_correct": True,
                "exec_entry_timing_efficiency": 1.0,
                "friction_entry_slippage_bps": 0,
                "exit_realized_r": 2.0,
                "exit_theoretical_r": 2.0,
            }
        )
        assert scores["prediction_score"] == pytest.approx(0.5 + 0.8 * 0.5)
        assert scores["execution_score"] == 1.0
        assert scores["exit_score"] == 1.0
        assert scores["friction_score"] == 1.0

    def test_incorrect_prediction(self):
        scores = compute_domain_scores(
            {
                "pred_confidence": 0.80,
                "pred_forecast_direction_correct": False,
                "exec_entry_timing_efficiency": 1.0,
                "friction_entry_slippage_bps": 0,
                "exit_realized_r": -1.0,
                "exit_theoretical_r": 2.0,
            }
        )
        assert scores["prediction_score"] == pytest.approx(0.20)

    def test_slippage_reduces_execution_score(self):
        scores = compute_domain_scores(
            {
                "pred_confidence": 0.50,
                "pred_forecast_direction_correct": None,
                "exec_entry_timing_efficiency": 1.0,
                "friction_entry_slippage_bps": 50,
                "exit_realized_r": 1.0,
                "exit_theoretical_r": 1.0,
            }
        )
        assert scores["execution_score"] < 1.0

    def test_friction_from_gap_fill(self):
        scores = compute_domain_scores(
            {
                "pred_confidence": 0.50,
                "pred_forecast_direction_correct": None,
                "exec_entry_timing_efficiency": 1.0,
                "friction_entry_slippage_bps": 0,
                "friction_gap_fill": True,
                "friction_partial_fill": False,
                "friction_fill_qty_ratio": 1.0,
                "friction_latency_bars": 0,
                "exit_realized_r": 1.0,
                "exit_theoretical_r": 1.0,
            }
        )
        assert scores["friction_score"] == pytest.approx(0.70)

    def test_fallback_from_side_and_prices(self):
        scores = compute_domain_scores(
            {
                "side": "long",
                "entry_price": 100.0,
                "exit_price": 105.0,
                "exec_mid_price_at_signal": 100.0,
            }
        )
        assert scores["prediction_score"] >= 0.5  # correct direction


class TestComputeWaterfall:
    def test_empty_records(self):
        result = compute_waterfall([])
        assert result["n"] == 0
        assert result["net_pnl"] == 0.0

    def test_single_trade(self):
        result = compute_waterfall(
            [
                {
                    "pred_confidence": 0.80,
                    "side": "long",
                    "entry_price": 100.0,
                    "exit_price": 105.0,
                    "realized_pnl": 500.0,
                    "exec_mid_price_at_signal": 100.0,
                }
            ]
        )
        assert result["n"] == 1
        assert result["net_pnl"] == pytest.approx(500.0)
        assert isinstance(result["prediction_pnl"], float)


class TestComputeAggregateDomainScores:
    def test_empty_records(self):
        result = compute_aggregate_domain_scores([])
        assert result["overall"] == {}

    def test_single_record(self):
        result = compute_aggregate_domain_scores(
            [
                {
                    "pred_confidence": 0.80,
                    "pred_forecast_direction_correct": True,
                    "exec_entry_timing_efficiency": 1.0,
                    "friction_entry_slippage_bps": 0,
                    "exit_realized_r": 2.0,
                    "exit_theoretical_r": 2.0,
                    "pred_archetype_at_entry": "BREAKOUT",
                    "pred_regime_at_entry": "GREEN",
                }
            ]
        )
        assert "prediction_score" in result["overall"]
        assert "execution_score" in result["overall"]
        assert "BREAKOUT" in result["by_archetype"]
        assert "GREEN" in result["by_regime"]
