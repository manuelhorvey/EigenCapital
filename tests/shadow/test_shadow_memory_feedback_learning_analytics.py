"""Tests for shadow/memory.py, shadow/feedback.py, shadow/learning.py, shadow/analytics.py."""

from __future__ import annotations

import json
from unittest.mock import mock_open

import numpy as np
import pytest

from paper_trading.shadow.memory import (
    _histogram_bins,
    build_baseline,
    load_baseline,
    save_baseline,
)

from paper_trading.shadow.feedback import (
    _build_event,
    _compute_alignment,
    _compute_derived_metrics,
    _expected_action_for_risk,
    record_shadow_feedback,
)

from paper_trading.shadow.learning import (
    _build_regime_behavior_map,
    _compute_learning_profile,
    _compute_shadow_insights,
    _empty_report,
    _mine_latent_patterns,
    compile_shadow_learning,
    load_compiled,
)

from paper_trading.shadow.analytics import (
    build_asset_learning_profile,
    compare_assets,
    compare_learning_profiles,
    detect_systemic_patterns,
)


@pytest.fixture
def sample_memory_events():
    return [
        {
            "model_divergence": {
                "current": {"proba_short": 0.3, "proba_neutral": 0.4, "proba_long": 0.3},
            },
            "signal_divergence": {"match": True},
            "pnl_decomposition": {"original_pnl": 100.0, "computed_pnl": 95.0},
            "regime_context": {"volatility_regime": "low"},
            "sltp_drift": {"sl_delta_pct": 0.02, "tp_delta_pct": 0.01},
        },
        {
            "model_divergence": {
                "current": {"proba_short": 0.2, "proba_neutral": 0.5, "proba_long": 0.3},
            },
            "signal_divergence": {"match": False},
            "pnl_decomposition": {"original_pnl": 200.0, "computed_pnl": 210.0},
            "regime_context": {"volatility_regime": "high"},
            "sltp_drift": {"sl_delta_pct": -0.01, "tp_delta_pct": 0.03},
        },
    ]


@pytest.fixture
def sample_feedback_events():
    return [
        {
            "inputs": {
                "signal": {"type": "LONG", "confidence": 80.0},
                "drift": {
                    "model": 0.10,
                    "signal": 0.20,
                    "pnl": 0.05,
                    "feature": 0.10,
                    "regime": 0.15,
                },
                "risk": {"risk_level": "LOW", "risk_score": 0.20, "risk_flags": []},
                "shadow_action": {"action_type": "NONE", "exposure_adjustment": 1.0},
            },
            "derived": {
                "agreement_score": 0.8800,
                "instability_index": 0.1175,
                "risk_alignment": 1.0,
            },
        },
        {
            "inputs": {
                "signal": {"type": "LONG", "confidence": 75.0},
                "drift": {
                    "model": 0.15,
                    "signal": 0.25,
                    "pnl": 0.08,
                    "feature": 0.12,
                    "regime": 0.18,
                },
                "risk": {"risk_level": "LOW", "risk_score": 0.25, "risk_flags": []},
                "shadow_action": {"action_type": "NONE", "exposure_adjustment": 1.0},
            },
            "derived": {
                "agreement_score": 0.8100,
                "instability_index": 0.1590,
                "risk_alignment": 1.0,
            },
        },
        {
            "inputs": {
                "signal": {"type": "LONG", "confidence": 70.0},
                "drift": {
                    "model": 0.20,
                    "signal": 0.30,
                    "pnl": 0.10,
                    "feature": 0.15,
                    "regime": 0.20,
                },
                "risk": {"risk_level": "MEDIUM", "risk_score": 0.40, "risk_flags": ["MODEL_DRIFT"]},
                "shadow_action": {"action_type": "REDUCE_EXPOSURE", "exposure_adjustment": 0.6},
            },
            "derived": {
                "agreement_score": 0.7100,
                "instability_index": 0.2035,
                "risk_alignment": 1.0,
            },
        },
    ]


@pytest.fixture
def mock_portfolio(monkeypatch):
    monkeypatch.setattr(
        "paper_trading.shadow.analytics.PAPER_PORTFOLIO",
        ["EURUSD", "GBPUSD"],
    )
    return ["EURUSD", "GBPUSD"]


@pytest.fixture
def mock_feedback_events(monkeypatch):
    events = [
        {
            "inputs": {
                "signal": {"type": "LONG", "confidence": 85.0},
                "drift": {
                    "model": 0.05,
                    "signal": 0.10,
                    "pnl": 0.02,
                    "feature": 0.03,
                    "regime": 0.08,
                },
                "risk": {"risk_level": "LOW", "risk_score": 0.10, "risk_flags": []},
                "shadow_action": {"action_type": "NONE", "exposure_adjustment": 1.0},
            },
            "derived": {
                "agreement_score": 0.9200,
                "instability_index": 0.0590,
                "risk_alignment": 1.0,
            },
        },
        {
            "inputs": {
                "signal": {"type": "SHORT", "confidence": 60.0},
                "drift": {
                    "model": 0.30,
                    "signal": 0.40,
                    "pnl": 0.15,
                    "feature": 0.20,
                    "regime": 0.35,
                },
                "risk": {"risk_level": "HIGH", "risk_score": 0.70, "risk_flags": ["MODEL_DRIFT"]},
                "shadow_action": {"action_type": "PAUSE_TRADING", "exposure_adjustment": 0.3},
            },
            "derived": {
                "agreement_score": 0.4200,
                "instability_index": 0.3030,
                "risk_alignment": 1.0,
            },
        },
    ]
    monkeypatch.setattr("paper_trading.shadow.analytics.read_feedback", lambda a, months=3: events)
    monkeypatch.setattr("paper_trading.shadow.learning.read_feedback", lambda a, months=6: events)
    return events


# ── memory.py ──────────────────────────────────────────────────────────────────


class TestHistogramBins:
    def test__histogram_bins_empty(self):
        assert _histogram_bins([]) == []

    def test__histogram_bins_normal(self):
        result = _histogram_bins([0.2, 0.4, 0.6, 0.8, 0.95], bins=5, low=0.0, high=1.0)
        assert len(result) == 5
        assert sum(b["count"] for b in result) == 5
        for b in result:
            assert "bin_start" in b
            assert "bin_end" in b
            assert "count" in b

    def test__histogram_bins_single_value(self):
        result = _histogram_bins([0.5], bins=5, low=0.0, high=1.0)
        assert len(result) == 5
        filled = [b for b in result if b["count"] > 0]
        assert len(filled) == 1


class TestBuildBaseline:
    def test_build_baseline_empty_events(self):
        baseline = build_baseline("EURUSD", events=[])
        assert baseline["asset"] == "EURUSD"
        assert baseline["event_count"] == 0
        assert "model_proba_distribution" not in baseline
        assert "signal_distribution" not in baseline

    def test_build_baseline_with_events(self, sample_memory_events):
        baseline = build_baseline("EURUSD", events=sample_memory_events)
        assert baseline["asset"] == "EURUSD"
        assert baseline["event_count"] == 2
        assert baseline["model_proba_distribution"]["count"] == 2
        assert baseline["signal_distribution"]["total"] == 2
        assert baseline["signal_distribution"]["matches"] == 1
        assert baseline["signal_distribution"]["mismatch_rate"] == pytest.approx(0.5)
        assert baseline["regime_distribution"] == {"low": 1, "high": 1}
        assert baseline["pnl_mismatch_stats"]["count"] == 2
        assert baseline["sltp_drift_stats"]["sl_adjustment_count"] == 2
        assert baseline["sltp_drift_stats"]["tp_adjustment_count"] == 2

    def test_build_baseline_partial_events(self):
        events = [
            {"model_divergence": {"current": {"proba_short": 0.5, "proba_neutral": 0.3, "proba_long": 0.2}}},
            {"signal_divergence": {"match": True}},
        ]
        baseline = build_baseline("EURUSD", events=events)
        assert baseline["event_count"] == 2
        assert baseline["model_proba_distribution"]["count"] == 1
        assert baseline["signal_distribution"]["total"] == 1
        assert baseline["signal_distribution"]["matches"] == 1
        assert "pnl_mismatch_stats" not in baseline
        assert "sltp_drift_stats" not in baseline

    def test_build_baseline_calls_read_events(self, monkeypatch, sample_memory_events):
        monkeypatch.setattr("paper_trading.shadow.memory.read_events", lambda a, days=90: sample_memory_events)
        baseline = build_baseline("EURUSD")
        assert baseline["event_count"] == 2

    def test_build_baseline_no_model_divergence(self):
        events = [
            {"signal_divergence": {"match": True}, "pnl_decomposition": {"original_pnl": 100.0, "computed_pnl": 99.0}}
        ]
        baseline = build_baseline("EURUSD", events=events)
        assert baseline["model_proba_distribution"]["count"] == 0

    def test_build_baseline_no_sltp(self):
        events = [{"model_divergence": {"current": {"proba_short": 0.1, "proba_neutral": 0.8, "proba_long": 0.1}}}]
        baseline = build_baseline("EURUSD", events=events)
        assert "sltp_drift_stats" not in baseline


class TestSaveLoadBaseline:
    def test_save_baseline(self, monkeypatch):
        m = mock_open()
        monkeypatch.setattr("builtins.open", m)
        monkeypatch.setattr("os.makedirs", lambda p, exist_ok: None)
        monkeypatch.setattr("os.replace", lambda s, d: None)
        baseline = {"asset": "EURUSD", "event_count": 5}
        save_baseline("EURUSD", baseline)
        m.assert_called_once()

    def test_load_baseline_exists(self, monkeypatch):
        data = json.dumps({"asset": "EURUSD", "event_count": 5})
        m = mock_open(read_data=data)
        monkeypatch.setattr("builtins.open", m)
        monkeypatch.setattr("os.path.exists", lambda p: True)
        result = load_baseline("EURUSD")
        assert result == {"asset": "EURUSD", "event_count": 5}

    def test_load_baseline_missing(self, monkeypatch):
        monkeypatch.setattr("os.path.exists", lambda p: False)
        result = load_baseline("EURUSD")
        assert result is None


# ── feedback.py ────────────────────────────────────────────────────────────────


class TestComputeDerivedMetrics:
    def test__compute_derived_metrics_normal(self):
        signal_data = {"signal": "LONG", "confidence": 0.8}
        drift = {
            "drift_scores": {
                "model_drift": 0.1,
                "signal_drift": 0.2,
                "pnl_drift": 0.05,
                "feature_stability": 0.1,
                "regime_consistency": 0.15,
            },
        }
        risk = {"risk_level": "LOW", "risk_score": 0.2}
        action = {"action_type": "NONE", "exposure_adjustment": 1.0}
        result = _compute_derived_metrics(signal_data, drift, risk, action)
        assert result["agreement_score"] == pytest.approx(0.8800, rel=1e-4)
        assert result["instability_index"] == pytest.approx(0.1175, rel=1e-4)
        assert result["risk_alignment"] == pytest.approx(1.0)

    def test__compute_derived_metrics_zero_drift(self):
        signal_data = {"signal": "FLAT", "confidence": 1.0}
        drift = {
            "drift_scores": {
                "model_drift": 0.0,
                "signal_drift": 0.0,
                "pnl_drift": 0.0,
                "feature_stability": 0.0,
                "regime_consistency": 0.0,
            },
        }
        risk = {"risk_level": "LOW", "risk_score": 0.0}
        action = {"action_type": "NONE", "exposure_adjustment": 1.0}
        result = _compute_derived_metrics(signal_data, drift, risk, action)
        assert result["agreement_score"] == pytest.approx(1.0)
        assert result["instability_index"] == pytest.approx(0.0)
        assert result["risk_alignment"] == pytest.approx(1.0)

    def test__compute_derived_metrics_high_drift(self):
        signal_data = {"signal": "SHORT", "confidence": 0.3}
        drift = {
            "drift_scores": {
                "model_drift": 0.8,
                "signal_drift": 0.7,
                "pnl_drift": 0.9,
                "feature_stability": 0.6,
                "regime_consistency": 0.5,
            },
        }
        risk = {"risk_level": "HIGH", "risk_score": 0.8}
        action = {"action_type": "NONE", "exposure_adjustment": 1.0}
        result = _compute_derived_metrics(signal_data, drift, risk, action)
        expected_avg = (0.8 + 0.7 + 0.9 + 0.6 + 0.5) / 5
        expected_agreement = max(0.0, 1.0 - (expected_avg * 0.5 + (1.0 - 0.3) * 0.3 + 0.0 * 0.2))
        expected_instability = 0.8 * 0.25 + 0.7 * 0.25 + 0.9 * 0.25 + 0.6 * 0.15 + 0.5 * 0.10
        assert result["agreement_score"] == pytest.approx(expected_agreement, rel=1e-4)
        assert result["instability_index"] == pytest.approx(expected_instability, rel=1e-4)
        expected_action = "PAUSE_TRADING"
        expected_alignment = max(0.0, 1.0 - abs(0 - 3) * 0.5)
        assert result["risk_alignment"] == pytest.approx(expected_alignment, rel=1e-4)

    def test__compute_derived_metrics_empty_drift(self):
        signal_data = {"signal": "LONG", "confidence": 0.5}
        drift = {}
        risk = {"risk_level": "LOW", "risk_score": 0.0}
        action = {"action_type": "NONE", "exposure_adjustment": 1.0}
        result = _compute_derived_metrics(signal_data, drift, risk, action)
        assert result["agreement_score"] == pytest.approx(0.85, rel=1e-4)
        assert result["instability_index"] == pytest.approx(0.0)
        assert result["risk_alignment"] == pytest.approx(1.0)


class TestExpectedActionForRisk:
    def test__expected_action_for_risk_low(self):
        assert _expected_action_for_risk({"risk_level": "LOW", "risk_score": 0.1}) == "NONE"

    def test__expected_action_for_risk_medium(self):
        assert _expected_action_for_risk({"risk_level": "MEDIUM", "risk_score": 0.4}) == "REDUCE_EXPOSURE"

    def test__expected_action_for_risk_high(self):
        assert _expected_action_for_risk({"risk_level": "HIGH", "risk_score": 0.7}) == "PAUSE_TRADING"

    def test__expected_action_for_risk_none(self):
        assert _expected_action_for_risk(None) == "NONE"

    def test__expected_action_for_risk_unknown_level(self):
        assert _expected_action_for_risk({"risk_level": "CRITICAL", "risk_score": 0.9}) == "NONE"


class TestComputeAlignment:
    def test__compute_alignment_exact_match(self):
        assert _compute_alignment("NONE", "NONE") == 1.0
        assert _compute_alignment("REDUCE_EXPOSURE", "REDUCE_EXPOSURE") == 1.0

    def test__compute_alignment_one_step_apart(self):
        assert _compute_alignment("NONE", "INCREASE_MONITORING") == pytest.approx(0.5)

    def test__compute_alignment_two_steps_apart(self):
        assert _compute_alignment("NONE", "REDUCE_EXPOSURE") == pytest.approx(0.0)

    def test__compute_alignment_three_steps_apart(self):
        assert _compute_alignment("NONE", "PAUSE_TRADING") == pytest.approx(0.0)

    def test__compute_alignment_unknown_actions(self):
        assert _compute_alignment("UNKNOWN", "NONE") == pytest.approx(1.0)


class TestBuildEvent:
    def test__build_event_structure(self):
        signal_data = {"signal": "LONG", "confidence": 0.8}
        drift = {
            "drift_scores": {
                "model_drift": 0.1,
                "signal_drift": 0.2,
                "pnl_drift": 0.05,
                "feature_stability": 0.1,
                "regime_consistency": 0.15,
            }
        }
        risk = {"risk_level": "LOW", "risk_score": 0.2}
        action = {"action_type": "NONE", "exposure_adjustment": 1.0}
        derived = {"agreement_score": 0.88, "instability_index": 0.1175, "risk_alignment": 1.0}
        event = _build_event("EURUSD", signal_data, drift, risk, action, derived)
        assert event["asset"] == "EURUSD"
        assert "timestamp" in event
        assert event["inputs"]["signal"]["type"] == "LONG"
        assert event["inputs"]["signal"]["confidence"] == 0.8
        assert event["inputs"]["drift"]["model"] == 0.1
        assert event["inputs"]["drift"]["feature"] == 0.1
        assert event["inputs"]["risk"]["risk_level"] == "LOW"
        assert event["inputs"]["shadow_action"]["action_type"] == "NONE"
        assert event["derived"] == derived

    def test__build_event_with_none_inputs(self):
        event = _build_event("EURUSD", None, None, None, None, {"a": 1})
        assert event["inputs"]["signal"]["type"] == "FLAT"
        assert event["inputs"]["signal"]["confidence"] == 0.0
        assert event["inputs"]["risk"]["risk_level"] == "LOW"
        assert event["inputs"]["shadow_action"]["action_type"] == "NONE"


class TestRecordShadowFeedback:
    def test_record_shadow_feedback_valid(self, monkeypatch):
        stored = []
        monkeypatch.setattr("paper_trading.shadow.feedback._store_event", lambda a, e: stored.append(e))
        signal_data = {"signal": "LONG", "confidence": 0.8}
        drift = {
            "drift_scores": {
                "model_drift": 0.1,
                "signal_drift": 0.2,
                "pnl_drift": 0.05,
                "feature_stability": 0.1,
                "regime_consistency": 0.15,
            }
        }
        risk = {"risk_level": "LOW", "risk_score": 0.2}
        action = {"action_type": "NONE", "exposure_adjustment": 1.0}
        record_shadow_feedback("EURUSD", signal_data, drift, risk, action)
        assert len(stored) == 1
        assert stored[0]["asset"] == "EURUSD"
        assert stored[0]["derived"]["agreement_score"] == pytest.approx(0.88, rel=1e-4)

    def test_record_shadow_feedback_invalid_asset(self, monkeypatch):
        stored = []
        monkeypatch.setattr("paper_trading.shadow.feedback._store_event", lambda a, e: stored.append(e))
        record_shadow_feedback("", {"signal": "LONG", "confidence": 0.8}, {}, {}, {})
        assert len(stored) == 0

    def test_record_shadow_feedback_none_signal_data(self, monkeypatch):
        stored = []
        monkeypatch.setattr("paper_trading.shadow.feedback._store_event", lambda a, e: stored.append(e))
        record_shadow_feedback("EURUSD", None, {}, {}, {})
        assert len(stored) == 0

    def test_record_shadow_feedback_none_drift(self, monkeypatch):
        stored = []
        monkeypatch.setattr("paper_trading.shadow.feedback._store_event", lambda a, e: stored.append(e))
        record_shadow_feedback("EURUSD", {"signal": "LONG", "confidence": 0.8}, None, {}, {})
        assert len(stored) == 0

    def test_record_shadow_feedback_none_risk(self, monkeypatch):
        stored = []
        monkeypatch.setattr("paper_trading.shadow.feedback._store_event", lambda a, e: stored.append(e))
        record_shadow_feedback("EURUSD", {"signal": "LONG", "confidence": 0.8}, {}, None, {})
        assert len(stored) == 0

    def test_record_shadow_feedback_none_action(self, monkeypatch):
        stored = []
        monkeypatch.setattr("paper_trading.shadow.feedback._store_event", lambda a, e: stored.append(e))
        record_shadow_feedback("EURUSD", {"signal": "LONG", "confidence": 0.8}, {}, {}, None)
        assert len(stored) == 0


# ── learning.py ────────────────────────────────────────────────────────────────


class TestComputeLearningProfile:
    def test__compute_learning_profile_empty(self):
        profile = _compute_learning_profile([])
        for k in (
            "behavioral_stability",
            "drift_resilience",
            "signal_consistency",
            "risk_sensitivity",
            "action_coherence",
        ):
            assert profile[k] == 0.0

    def test__compute_learning_profile_normal(self, sample_feedback_events):
        profile = _compute_learning_profile(sample_feedback_events)
        assert "behavioral_stability" in profile
        assert "drift_resilience" in profile
        assert "signal_consistency" in profile
        assert "risk_sensitivity" in profile
        assert "action_coherence" in profile
        instabilities = [e["derived"]["instability_index"] for e in sample_feedback_events]
        expected_stability = max(0.0, 1.0 - np.mean(instabilities))
        assert profile["behavioral_stability"] == pytest.approx(float(expected_stability), rel=1e-4)

    def test__compute_learning_profile_default_risk_sensitivity(self):
        events = [
            {
                "inputs": {
                    "signal": {"type": "LONG", "confidence": 80.0},
                    "drift": {"model": 0.0, "signal": 0.0, "pnl": 0.0, "feature": 0.0, "regime": 0.0},
                    "risk": {"risk_level": "LOW", "risk_score": 0.0, "risk_flags": []},
                    "shadow_action": {"action_type": "NONE", "exposure_adjustment": 1.0},
                },
                "derived": {"agreement_score": 1.0, "instability_index": 0.0, "risk_alignment": 1.0},
            }
        ]
        profile = _compute_learning_profile(events)
        assert profile["risk_sensitivity"] == pytest.approx(0.5)


class TestMineLatentPatterns:
    def test__mine_latent_patterns_few_events(self):
        assert _mine_latent_patterns([{}, {}, {}, {}]) == []

    def test__mine_latent_patterns_sufficient_events_no_patterns(self):
        events = [
            {
                "inputs": {
                    "signal": {"type": "LONG", "confidence": 90.0},
                    "drift": {"model": 0.05, "signal": 0.05, "pnl": 0.05, "feature": 0.05, "regime": 0.05},
                    "risk": {"risk_level": "LOW", "risk_score": 0.1, "risk_flags": []},
                    "shadow_action": {"action_type": "NONE", "exposure_adjustment": 1.0},
                },
                "derived": {"agreement_score": 0.95, "instability_index": 0.05, "risk_alignment": 1.0},
            }
            for _ in range(6)
        ]
        patterns = _mine_latent_patterns(events)
        assert isinstance(patterns, list)
        assert len(patterns) == 0

    def test__mine_latent_patterns_high_risk_detected(self):
        events = []
        for i in range(10):
            rl = "HIGH" if i < 4 else "LOW"
            events.append(
                {
                    "inputs": {
                        "signal": {"type": "LONG", "confidence": 80.0},
                        "drift": {"model": 0.1, "signal": 0.1, "pnl": 0.1, "feature": 0.1, "regime": 0.1},
                        "risk": {"risk_level": rl, "risk_score": 0.5, "risk_flags": []},
                        "shadow_action": {"action_type": "REDUCE_EXPOSURE", "exposure_adjustment": 0.6},
                    },
                    "derived": {"agreement_score": 0.8, "instability_index": 0.1, "risk_alignment": 1.0},
                }
            )
        patterns = _mine_latent_patterns(events)
        assert "PROLONGED_HIGH_RISK_REGIME_DETECTED" in patterns

    def test__mine_latent_patterns_underreaction(self):
        events = []
        for i in range(10):
            rl = "MEDIUM"
            at = "NONE"
            events.append(
                {
                    "inputs": {
                        "signal": {"type": "LONG", "confidence": 80.0},
                        "drift": {"model": 0.1, "signal": 0.1, "pnl": 0.1, "feature": 0.1, "regime": 0.1},
                        "risk": {"risk_level": rl, "risk_score": 0.4, "risk_flags": []},
                        "shadow_action": {"action_type": at, "exposure_adjustment": 1.0},
                    },
                    "derived": {"agreement_score": 0.8, "instability_index": 0.1, "risk_alignment": 0.5},
                }
            )
        patterns = _mine_latent_patterns(events)
        assert "RISK_UNDERREACTION_IN_MEDIUM_RISK_PERIODS" in patterns

    def test__mine_latent_patterns_overreaction(self):
        events = []
        for i in range(10):
            rl = "HIGH"
            at = "NONE"
            events.append(
                {
                    "inputs": {
                        "signal": {"type": "LONG", "confidence": 80.0},
                        "drift": {"model": 0.1, "signal": 0.1, "pnl": 0.1, "feature": 0.1, "regime": 0.1},
                        "risk": {"risk_level": rl, "risk_score": 0.7, "risk_flags": []},
                        "shadow_action": {"action_type": at, "exposure_adjustment": 1.0},
                    },
                    "derived": {"agreement_score": 0.5, "instability_index": 0.1, "risk_alignment": 0.0},
                }
            )
        patterns = _mine_latent_patterns(events)
        assert "RISK_OVEREACTION_IN_HIGH_VIX_REGIMES" in patterns

    def test__mine_latent_patterns_correlation(self):
        events = []
        for i in range(10):
            d = 0.05 + i * 0.05
            c = max(10.0, 90.0 - i * 8.0)
            events.append(
                {
                    "inputs": {
                        "signal": {"type": "LONG", "confidence": c},
                        "drift": {"model": d, "signal": d, "pnl": d, "feature": d, "regime": d},
                        "risk": {"risk_level": "LOW", "risk_score": 0.1, "risk_flags": []},
                        "shadow_action": {"action_type": "NONE", "exposure_adjustment": 1.0},
                    },
                    "derived": {"agreement_score": 0.8, "instability_index": d, "risk_alignment": 1.0},
                }
            )
        patterns = _mine_latent_patterns(events)
        found = any("HIGH_DRIFT_PERIODS_CORRELATE_WITH" in p for p in patterns)
        assert found

    def test__mine_latent_patterns_feature_decay(self):
        events = []
        for i in range(10):
            # Spike instability at index 3 and 7
            if i in (3, 7):
                instability = 0.8
            else:
                instability = 0.1
            events.append(
                {
                    "inputs": {
                        "signal": {"type": "LONG", "confidence": 80.0},
                        "drift": {"model": 0.1, "signal": 0.1, "pnl": 0.1, "feature": 0.1, "regime": 0.1},
                        "risk": {"risk_level": "LOW", "risk_score": 0.1, "risk_flags": []},
                        "shadow_action": {"action_type": "NONE", "exposure_adjustment": 1.0},
                    },
                    "derived": {"agreement_score": 0.8, "instability_index": instability, "risk_alignment": 1.0},
                }
            )
        patterns = _mine_latent_patterns(events)
        assert "FEATURE_DECAY_AFTER_VOLATILITY_SPIKES" in patterns


class TestBuildRegimeBehaviorMap:
    def test__build_regime_behavior_map_empty(self):
        result = _build_regime_behavior_map([])
        assert result["low_vol"]["stability"] == 0.5
        assert result["low_vol"]["risk_action_rate"] == 0.0
        assert result["high_vol"]["stability"] == 0.5
        assert result["high_vol"]["risk_action_rate"] == 0.0

    def test__build_regime_behavior_map_all_low_vol(self):
        events = [
            {
                "inputs": {
                    "drift": {"model": 0.0, "signal": 0.0, "pnl": 0.0, "feature": 0.0, "regime": 0.1},
                    "risk": {"risk_level": "LOW", "risk_score": 0.1, "risk_flags": []},
                    "shadow_action": {"action_type": "NONE", "exposure_adjustment": 1.0},
                },
                "derived": {"instability_index": 0.1, "risk_alignment": 1.0},
            }
            for _ in range(3)
        ]
        result = _build_regime_behavior_map(events)
        assert result["low_vol"]["stability"] == pytest.approx(0.9)
        assert result["low_vol"]["risk_action_rate"] == 0.0
        assert result["high_vol"]["stability"] == 0.5

    def test__build_regime_behavior_map_all_high_vol(self):
        events = [
            {
                "inputs": {
                    "drift": {"model": 0.0, "signal": 0.0, "pnl": 0.0, "feature": 0.0, "regime": 0.5},
                    "risk": {"risk_level": "HIGH", "risk_score": 0.7, "risk_flags": []},
                    "shadow_action": {"action_type": "PAUSE_TRADING", "exposure_adjustment": 0.3},
                },
                "derived": {"instability_index": 0.2, "risk_alignment": 1.0},
            }
            for _ in range(3)
        ]
        result = _build_regime_behavior_map(events)
        assert result["high_vol"]["stability"] == pytest.approx(0.8)
        assert result["high_vol"]["risk_action_rate"] == pytest.approx(1.0)
        assert result["low_vol"]["stability"] == 0.5

    def test__build_regime_behavior_map_mixed(self):
        events = [
            {
                "inputs": {
                    "drift": {"model": 0.0, "signal": 0.0, "pnl": 0.0, "feature": 0.0, "regime": 0.1},
                    "risk": {"risk_level": "LOW", "risk_score": 0.1, "risk_flags": []},
                    "shadow_action": {"action_type": "NONE", "exposure_adjustment": 1.0},
                },
                "derived": {"instability_index": 0.1, "risk_alignment": 1.0},
            },
            {
                "inputs": {
                    "drift": {"model": 0.0, "signal": 0.0, "pnl": 0.0, "feature": 0.0, "regime": 0.5},
                    "risk": {"risk_level": "HIGH", "risk_score": 0.7, "risk_flags": []},
                    "shadow_action": {"action_type": "PAUSE_TRADING", "exposure_adjustment": 0.3},
                },
                "derived": {"instability_index": 0.3, "risk_alignment": 1.0},
            },
        ]
        result = _build_regime_behavior_map(events)
        assert result["low_vol"]["stability"] == pytest.approx(0.9)
        assert result["low_vol"]["risk_action_rate"] == pytest.approx(0.0)
        assert result["high_vol"]["stability"] == pytest.approx(0.7)
        assert result["high_vol"]["risk_action_rate"] == pytest.approx(1.0)


class TestComputeShadowInsights:
    def test__compute_shadow_insights_empty(self):
        result = _compute_shadow_insights([])
        assert result["top_instability_drivers"] == []
        assert result["dominant_failure_mode"] == "unknown"
        assert result["execution_fragility_score"] == 0.0

    def test__compute_shadow_insights_with_events(self, sample_feedback_events):
        result = _compute_shadow_insights(sample_feedback_events)
        assert isinstance(result["top_instability_drivers"], list)
        assert isinstance(result["dominant_failure_mode"], str)
        assert result["execution_fragility_score"] >= 0.0

    def test__compute_shadow_insights_risk_flags(self):
        events = [
            {
                "inputs": {
                    "drift": {"model": 0.5, "signal": 0.3, "pnl": 0.2, "feature": 0.1, "regime": 0.4},
                    "risk": {"risk_level": "HIGH", "risk_score": 0.8, "risk_flags": ["MODEL_DRIFT", "LIQUIDITY"]},
                    "shadow_action": {"action_type": "PAUSE_TRADING", "exposure_adjustment": 0.3},
                },
                "derived": {"instability_index": 0.3, "risk_alignment": 1.0},
            }
            for _ in range(3)
        ]
        result = _compute_shadow_insights(events)
        assert "model" in result["top_instability_drivers"]
        assert "model_drift" in result["dominant_failure_mode"] or result["dominant_failure_mode"] != "unknown"
        assert result["execution_fragility_score"] > 0.0


class TestEmptyReport:
    def test__empty_report_structure(self):
        report = _empty_report("EURUSD")
        assert report["asset"] == "EURUSD"
        assert report["event_count"] == 0
        assert report["learning_profile"]["behavioral_stability"] == 0.0
        assert report["latent_patterns"] == []
        assert report["regime_behavior_map"]["low_vol"]["stability"] == 0.5
        assert report["shadow_insights"]["execution_fragility_score"] == 0.0
        assert "timestamp" in report


class TestCompileShadowLearning:
    def test_compile_shadow_learning_empty(self, monkeypatch):
        monkeypatch.setattr("paper_trading.shadow.learning._save_compiled", lambda a, r: None)
        result = compile_shadow_learning("EURUSD", feedback_logs=[])
        assert result["event_count"] == 0
        assert result["learning_profile"]["behavioral_stability"] == 0.0

    def test_compile_shadow_learning_with_events(self, monkeypatch, sample_feedback_events):
        monkeypatch.setattr("paper_trading.shadow.learning._save_compiled", lambda a, r: None)
        result = compile_shadow_learning("EURUSD", feedback_logs=sample_feedback_events)
        assert result["asset"] == "EURUSD"
        assert result["event_count"] == 3
        assert "learning_profile" in result
        assert "latent_patterns" in result
        assert "regime_behavior_map" in result
        assert "shadow_insights" in result

    def test_compile_shadow_learning_calls_read_feedback(self, monkeypatch, sample_feedback_events):
        monkeypatch.setattr("paper_trading.shadow.learning.read_feedback", lambda a, months=6: sample_feedback_events)
        monkeypatch.setattr("paper_trading.shadow.learning._save_compiled", lambda a, r: None)
        result = compile_shadow_learning("EURUSD")
        assert result["event_count"] == 3

    def test_compile_shadow_learning_fallback_on_error(self, monkeypatch):
        monkeypatch.setattr(
            "paper_trading.shadow.learning._compute_learning_profile",
            lambda e: (_ for _ in ()).throw(RuntimeError("test")),
        )
        monkeypatch.setattr("paper_trading.shadow.learning._save_compiled", lambda a, r: None)
        result = compile_shadow_learning("EURUSD", feedback_logs=[{"derived": {"instability_index": 0.1}}])
        assert result["event_count"] == 0


class TestLoadCompiled:
    def test_load_compiled_exists(self, monkeypatch):
        data = json.dumps({"asset": "EURUSD", "learning_profile": {"behavioral_stability": 0.8}})
        m = mock_open(read_data=data)
        monkeypatch.setattr("builtins.open", m)
        monkeypatch.setattr("os.path.exists", lambda p: True)
        result = load_compiled("EURUSD")
        assert result["asset"] == "EURUSD"
        assert result["learning_profile"]["behavioral_stability"] == 0.8

    def test_load_compiled_missing(self, monkeypatch):
        monkeypatch.setattr("os.path.exists", lambda p: False)
        result = load_compiled("EURUSD")
        assert result is None


# ── analytics.py ───────────────────────────────────────────────────────────────


class TestBuildAssetLearningProfile:
    def test_build_asset_learning_profile_normal(self, monkeypatch, mock_feedback_events):
        profile = build_asset_learning_profile("EURUSD", months=3)
        assert profile is not None
        assert profile["asset"] == "EURUSD"
        assert profile["event_count"] == 2
        assert profile["avg_agreement"] == pytest.approx((0.92 + 0.42) / 2, rel=1e-4)
        assert profile["avg_instability"] == pytest.approx((0.059 + 0.303) / 2, rel=1e-4)
        assert profile["avg_risk_alignment"] == pytest.approx(1.0)
        assert "shadow_action_utilization" in profile
        assert profile["risk_overreaction_rate"] == 0.0

    def test_build_asset_learning_profile_empty(self, monkeypatch):
        monkeypatch.setattr("paper_trading.shadow.analytics.read_feedback", lambda a, months=3: [])
        profile = build_asset_learning_profile("EURUSD", months=3)
        assert profile is None


class TestCompareAssets:
    def test_compare_assets_ranking(self, monkeypatch, mock_portfolio):
        profiles = {
            "EURUSD": {
                "asset": "EURUSD",
                "event_count": 2,
                "avg_agreement": 0.85,
                "avg_instability": 0.10,
                "avg_risk_alignment": 0.95,
                "drift_sensitivity": 0.12,
                "risk_overreaction_rate": 0.0,
                "shadow_action_utilization": {"NONE": 1.0},
            },
            "GBPUSD": {
                "asset": "GBPUSD",
                "event_count": 2,
                "avg_agreement": 0.75,
                "avg_instability": 0.25,
                "avg_risk_alignment": 0.80,
                "drift_sensitivity": 0.30,
                "risk_overreaction_rate": 0.1,
                "shadow_action_utilization": {"NONE": 0.8, "REDUCE_EXPOSURE": 0.2},
            },
        }
        original = build_asset_learning_profile

        def mock_profile(a, months=3):
            return profiles.get(a)

        monkeypatch.setattr("paper_trading.shadow.analytics.build_asset_learning_profile", mock_profile)
        result = compare_assets(months=3)
        assert "stability_ranking" in result
        assert "profiles" in result
        assert len(result["stability_ranking"]) == 2
        assert result["stability_ranking"][0]["asset"] == "EURUSD"
        assert result["stability_ranking"][0]["stability_score"] == pytest.approx(0.9)
        assert result["stability_ranking"][1]["asset"] == "GBPUSD"

    def test_compare_assets_empty(self, monkeypatch, mock_portfolio):
        monkeypatch.setattr("paper_trading.shadow.analytics.build_asset_learning_profile", lambda a, months=3: None)
        result = compare_assets(months=3)
        assert result["stability_ranking"] == []
        assert result["profiles"] == []


class TestCompareLearningProfiles:
    def test_compare_learning_profiles_ranking(self, monkeypatch, mock_portfolio):
        compiled = {
            "EURUSD": {
                "asset": "EURUSD",
                "event_count": 5,
                "learning_profile": {
                    "behavioral_stability": 0.85,
                    "drift_resilience": 0.80,
                    "risk_sensitivity": 0.70,
                    "action_coherence": 0.90,
                },
                "shadow_insights": {
                    "execution_fragility_score": 0.15,
                    "dominant_failure_mode": "none_detected",
                },
            },
            "GBPUSD": {
                "asset": "GBPUSD",
                "event_count": 5,
                "learning_profile": {
                    "behavioral_stability": 0.65,
                    "drift_resilience": 0.60,
                    "risk_sensitivity": 0.50,
                    "action_coherence": 0.70,
                },
                "shadow_insights": {
                    "execution_fragility_score": 0.35,
                    "dominant_failure_mode": "model_drift",
                },
            },
        }

        def mock_compile(asset):
            return compiled.get(asset, {"event_count": 0})

        monkeypatch.setattr("paper_trading.shadow.analytics.compile_shadow_learning", mock_compile)
        result = compare_learning_profiles()
        assert "rankings" in result
        assert len(result["rankings"]) == 2
        assert result["rankings"][0]["asset"] == "EURUSD"
        assert result["rankings"][0]["stability"] == 0.85
        assert result["rankings"][1]["asset"] == "GBPUSD"

    def test_compare_learning_profiles_empty(self, monkeypatch, mock_portfolio):
        monkeypatch.setattr("paper_trading.shadow.analytics.compile_shadow_learning", lambda a: {"event_count": 0})
        result = compare_learning_profiles()
        assert result["rankings"] == []


class TestDetectSystemicPatterns:
    def test_detect_systemic_patterns(self, monkeypatch, mock_portfolio):
        compiled = {
            "EURUSD": {
                "latent_patterns": ["PROLONGED_HIGH_RISK_REGIME_DETECTED", "FEATURE_DECAY_AFTER_VOLATILITY_SPIKES"],
                "shadow_insights": {"execution_fragility_score": 0.3},
                "learning_profile": {"behavioral_stability": 0.7},
            },
            "GBPUSD": {
                "latent_patterns": ["PROLONGED_HIGH_RISK_REGIME_DETECTED"],
                "shadow_insights": {"execution_fragility_score": 0.5},
                "learning_profile": {"behavioral_stability": 0.5},
            },
        }

        def mock_compile(asset):
            return compiled.get(
                asset,
                {
                    "latent_patterns": [],
                    "shadow_insights": {"execution_fragility_score": 0.0},
                    "learning_profile": {"behavioral_stability": 0.0},
                },
            )

        monkeypatch.setattr("paper_trading.shadow.analytics.compile_shadow_learning", mock_compile)
        result = detect_systemic_patterns()
        assert "global_patterns" in result
        assert "system_risk_signature" in result
        assert "pattern_frequency" in result
        assert "PROLONGED_HIGH_RISK_REGIME_DETECTED" in result["global_patterns"]
        assert result["system_risk_signature"] == pytest.approx(0.4, rel=1e-4)

    def test_detect_systemic_patterns_empty(self, monkeypatch, mock_portfolio):
        monkeypatch.setattr(
            "paper_trading.shadow.analytics.compile_shadow_learning",
            lambda a: {
                "latent_patterns": [],
                "shadow_insights": {"execution_fragility_score": 0.0},
                "learning_profile": {"behavioral_stability": 0.0},
            },
        )
        result = detect_systemic_patterns()
        assert result["global_patterns"] == []
        assert result["system_risk_signature"] == 1.0
        assert result["pattern_frequency"] == {}
