"""Tests for governance/health.py — composite health scoring.

Relies on monkeypatching to avoid file I/O and shadow memory calls.
"""

from __future__ import annotations

import pytest

from paper_trading.governance import health


@pytest.fixture(autouse=True)
def reset_health_state():
    health._cache.clear()
    yield


@pytest.fixture
def shadow_intelligence():
    return {
        "drift_scores": {
            "model_drift": 0.1,
            "signal_drift": 0.05,
            "pnl_drift": 0.08,
            "feature_stability": 0.12,
            "regime_consistency": 0.03,
        },
        "details": {
            "model": {"average_kl": 0.1},
            "signal": {"mismatch_rate": 0.05},
            "pnl": {},
            "feature": {},
            "regime": {},
        },
    }


class TestValidityScore:
    def test_green_returns_one(self):
        assert health._get_validity_score("GREEN") == 1.0

    def test_yellow_returns_point_75(self):
        assert health._get_validity_score("YELLOW") == 0.75

    def test_red_returns_zero(self):
        assert health._get_validity_score("RED") == 0.0

    def test_unknown_returns_point_75(self):
        assert health._get_validity_score("UNKNOWN") == 0.75


class TestDriftHealth:
    def test_no_drift_returns_one(self):
        assert health._compute_drift_health({"model_drift": 0.0, "signal_drift": 0.0}) == 1.0

    def test_full_drift_returns_zero(self):
        assert health._compute_drift_health({
            "model_drift": 1.0, "signal_drift": 1.0, "feature_stability": 1.0, "regime_consistency": 1.0,
        }) == 0.0

    def test_partial_drift(self):
        score = health._compute_drift_health({"model_drift": 0.2, "signal_drift": 0.2, "feature_stability": 0.2, "regime_consistency": 0.2})
        assert score == 0.8


class TestPnlHealth:
    def test_no_pnl_drift_returns_one(self):
        assert health._compute_pnl_health({"pnl_drift": 0.0}) == 1.0

    def test_full_pnl_drift_returns_zero(self):
        assert health._compute_pnl_health({"pnl_drift": 1.0}) == 0.0

    def test_partial_pnl_drift(self):
        assert health._compute_pnl_health({"pnl_drift": 0.3}) == 0.7


class TestShadowAgreement:
    def test_perfect_agreement(self, shadow_intelligence):
        si = shadow_intelligence
        si["details"]["signal"]["mismatch_rate"] = 0.0
        si["details"]["model"]["average_kl"] = 0.0
        score = health._compute_shadow_agreement(si["drift_scores"], si)
        assert score == 1.0

    def test_mismatch_reduces_score(self, shadow_intelligence):
        si = shadow_intelligence
        si["details"]["signal"]["mismatch_rate"] = 0.5
        si["details"]["model"]["average_kl"] = 0.0
        score = health._compute_shadow_agreement(si["drift_scores"], si)
        assert score == 0.5


class TestCompute:
    def test_healthy_asset(self, monkeypatch, shadow_intelligence):
        monkeypatch.setattr(health, "_load_state_assets", lambda: {
            "EURUSD": {"validity_state": "GREEN"},
        })
        monkeypatch.setattr(health, "get_shadow_intelligence", lambda asset, **kw: shadow_intelligence)
        monkeypatch.setattr(health, "_load_cmss", lambda asset: None)

        result = health.compute("EURUSD")
        assert result["health_label"] == "HEALTHY"
        assert result["health_score"] > 0.80
        assert result["health_color"] == "green"
        assert result["stress_robustness_source"] == "estimated"

    def test_critical_asset(self, monkeypatch):
        monkeypatch.setattr(health, "_load_state_assets", lambda: {
            "EURUSD": {"validity_state": "RED"},
        })
        monkeypatch.setattr(health, "get_shadow_intelligence", lambda asset, **kw: {
            "drift_scores": {
                "model_drift": 0.8,
                "signal_drift": 0.7,
                "pnl_drift": 0.9,
                "feature_stability": 0.8,
                "regime_consistency": 0.7,
            },
            "details": {
                "model": {"average_kl": 0.8},
                "signal": {"mismatch_rate": 0.7},
            },
        })
        monkeypatch.setattr(health, "_load_cmss", lambda asset: None)

        result = health.compute("EURUSD")
        assert result["health_label"] == "CRITICAL"
        assert result["health_color"] == "red"
        assert result["health_score"] < 0.5

    def test_with_cmss_from_adversarial(self, monkeypatch, shadow_intelligence):
        monkeypatch.setattr(health, "_load_state_assets", lambda: {
            "EURUSD": {"validity_state": "GREEN"},
        })
        monkeypatch.setattr(health, "get_shadow_intelligence", lambda asset, **kw: shadow_intelligence)
        monkeypatch.setattr(health, "_load_cmss", lambda asset: 0.95)

        result = health.compute("EURUSD")
        assert result["stress_robustness_source"] == "adversarial_manifold"
        assert result["components"]["stress_robustness"] == 0.95

    def test_fallback_on_exception(self, monkeypatch):
        def failing(asset):
            raise RuntimeError("Something broke")

        monkeypatch.setattr(health, "_load_state_assets", failing)
        result = health.compute("EURUSD")
        assert result["health_label"] == "UNKNOWN"
        assert result["health_score"] == 0.5

    def test_limiting_factors_identified(self, monkeypatch):
        degraded_intel = {
            "drift_scores": {
                "model_drift": 0.6,
                "signal_drift": 0.5,
                "pnl_drift": 0.4,
                "feature_stability": 0.6,
                "regime_consistency": 0.5,
            },
            "details": {
                "model": {"average_kl": 0.6},
                "signal": {"mismatch_rate": 0.5},
            },
        }
        monkeypatch.setattr(health, "_load_state_assets", lambda: {
            "EURUSD": {"validity_state": "YELLOW"},
        })
        monkeypatch.setattr(health, "get_shadow_intelligence", lambda asset, **kw: degraded_intel)
        monkeypatch.setattr(health, "_load_cmss", lambda asset: None)

        result = health.compute("EURUSD")
        limiting = result["limiting_factors"]
        assert len(limiting) > 0
        for lf in limiting:
            assert lf["score"] < 0.75


class TestComputeAll:
    def test_compute_all_multiple_assets(self, monkeypatch):
        state_assets = {
            "EURUSD": {"validity_state": "GREEN"},
            "GBPUSD": {"validity_state": "YELLOW"},
        }
        monkeypatch.setattr(health, "_load_state_assets", lambda: state_assets)

        def mock_intel(asset, **kw):
            return {
                "drift_scores": {
                    "model_drift": 0.1,
                    "signal_drift": 0.05,
                    "pnl_drift": 0.08,
                    "feature_stability": 0.12,
                    "regime_consistency": 0.03,
                },
                "details": {"model": {"average_kl": 0.1}, "signal": {"mismatch_rate": 0.05}},
            }

        monkeypatch.setattr(health, "get_shadow_intelligence", mock_intel)
        monkeypatch.setattr(health, "_load_cmss", lambda asset: None)

        result = health.compute_all()
        assert "EURUSD" in result["assets"]
        assert "GBPUSD" in result["assets"]
        assert result["system_health"]["n_assets"] == 2

    def test_compute_all_empty_state(self, monkeypatch):
        monkeypatch.setattr(health, "_load_state_assets", lambda: {})
        result = health.compute_all()
        assert result["assets"] == {}
        assert result["system_health"]["n_assets"] == 0


class TestGetLatest:
    def test_get_latest(self):
        health._cache = {"EURUSD": {"health_label": "HEALTHY"}}
        assert health.get_latest("EURUSD") == {"health_label": "HEALTHY"}
        assert health.get_latest("NONEXISTENT") is None
        assert len(health.get_latest()) == 1
