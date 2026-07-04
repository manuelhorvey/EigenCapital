"""Tests for shadow/actions.py — pure functions, no mocking needed."""

from __future__ import annotations

import pytest

from paper_trading.shadow.actions import (
    _compute_action,
    _compute_guardrails,
    _fallback,
    compute_shadow_actions,
)


class TestComputeAction:
    def test_high_risk_pauses_trading(self):
        action_type, exposure = _compute_action("HIGH", 0.7)
        assert action_type == "PAUSE_TRADING"
        assert exposure == pytest.approx(0.3, rel=1e-9)

    def test_medium_risk_reduces_exposure(self):
        action_type, exposure = _compute_action("MEDIUM", 0.4)
        assert action_type == "REDUCE_EXPOSURE"
        assert exposure == 0.6

    def test_low_risk_increases_monitoring(self):
        action_type, exposure = _compute_action("LOW", 0.15)
        assert action_type == "INCREASE_MONITORING"
        assert exposure == 1.0

    def test_zero_risk_none_action(self):
        action_type, exposure = _compute_action("LOW", 0.0)
        assert action_type == "NONE"
        assert exposure == 1.0


class TestComputeGuardrails:
    def test_high_risk_blocks_entry(self):
        g = _compute_guardrails("HIGH", 0.7)
        assert g["entry_block"] is True
        assert g["max_position_size"] == 0.3
        assert g["min_hold_time"] == 2

    def test_medium_risk_no_entry_block(self):
        g = _compute_guardrails("MEDIUM", 0.4)
        assert g["entry_block"] is False
        assert g["max_position_size"] == 0.6
        assert g["min_hold_time"] == 1

    def test_low_risk_no_restrictions(self):
        g = _compute_guardrails("LOW", 0.0)
        assert g["entry_block"] is False
        assert g["max_position_size"] == 1.0
        assert g["min_hold_time"] == 0


class TestFallback:
    def test_fallback_structure(self):
        result = _fallback("TEST_REASON")
        assert result["action_type"] == "NONE"
        assert result["exposure_adjustment"] == 1.0
        assert "TEST_REASON" in result["reason_codes"]


class TestComputeShadowActions:
    def test_no_drift_returns_none(self):
        drift = {
            "drift_scores": {
                "model_drift": 0.0, "signal_drift": 0.0, "pnl_drift": 0.0,
                "feature_stability": 0.0, "regime_consistency": 0.0,
            }
        }
        risk = {"risk_level": "LOW", "risk_score": 0.0, "risk_flags": []}
        result = compute_shadow_actions("EURUSD", {}, drift, risk)
        assert result["action_type"] == "NONE"
        assert result["reason_codes"] == []

    def test_high_model_drift_triggers_flag(self):
        drift = {
            "drift_scores": {
                "model_drift": 0.5, "signal_drift": 0.0, "pnl_drift": 0.0,
                "feature_stability": 0.0, "regime_consistency": 0.0,
            }
        }
        risk = {"risk_level": "LOW", "risk_score": 0.0, "risk_flags": []}
        result = compute_shadow_actions("EURUSD", {}, drift, risk)
        assert "HIGH_MODEL_DRIFT" in result["reason_codes"]

    def test_multiple_drifts_accumulate(self):
        drift = {
            "drift_scores": {
                "model_drift": 0.5, "signal_drift": 0.4, "pnl_drift": 0.6,
                "feature_stability": 0.3, "regime_consistency": 0.35,
            }
        }
        risk = {"risk_level": "MEDIUM", "risk_score": 0.4, "risk_flags": []}
        result = compute_shadow_actions("EURUSD", {}, drift, risk)
        assert len(result["reason_codes"]) >= 3
        assert result["action_type"] == "REDUCE_EXPOSURE"

    def test_high_risk_pauses(self):
        drift = {
            "drift_scores": {
                "model_drift": 0.8, "signal_drift": 0.7, "pnl_drift": 0.9,
                "feature_stability": 0.6, "regime_consistency": 0.5,
            }
        }
        risk = {"risk_level": "HIGH", "risk_score": 0.7, "risk_flags": ["MODEL_DRIFT"]}
        result = compute_shadow_actions("EURUSD", {}, drift, risk)
        assert result["action_type"] == "PAUSE_TRADING"

    def test_fallback_on_missing_data(self):
        result = compute_shadow_actions("EURUSD", {}, None, None)
        assert result["action_type"] == "NONE"
        assert "SHADOW_FAILURE" in result["reason_codes"]

    def test_drift_summary_included(self):
        drift = {
            "drift_scores": {
                "model_drift": 0.1, "signal_drift": 0.2, "pnl_drift": 0.3,
                "feature_stability": 0.4, "regime_consistency": 0.5,
            }
        }
        risk = {"risk_level": "LOW", "risk_score": 0.0, "risk_flags": []}
        result = compute_shadow_actions("EURUSD", {}, drift, risk)
        summary = result["drift_summary"]
        assert summary["model"] == 0.1
        assert summary["regime"] == 0.5
