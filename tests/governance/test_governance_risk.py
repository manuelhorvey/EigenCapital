"""Tests for governance/risk.py — module-level risk scoring, SL hit rate, flags."""

from __future__ import annotations

import pytest

from paper_trading.governance import risk as risk_module
from paper_trading.governance import risk_registry


@pytest.fixture(autouse=True)
def reset_risk_state():
    risk_module.reset()
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
            "signal": {"mismatch_rate": 0.05, "flip_rate": 0.02},
            "pnl": {"mae": 0.08},
            "feature": {"stability": 0.88},
            "regime": {"consistency": 0.97},
        },
    }


# ── SL hit rate ─────────────────────────────────────────────────────────


class TestSlHitRate:
    def test_record_and_retrieve(self):
        for _ in range(10):
            risk_module.record_trade_outcome("EURUSD", "sl")
        for _ in range(10):
            risk_module.record_trade_outcome("EURUSD", "tp")

        rate = risk_module.get_sl_hit_rate("EURUSD")
        assert rate == 0.5

    def test_insufficient_data_returns_none(self):
        risk_module.record_trade_outcome("EURUSD", "sl")
        assert risk_module.get_sl_hit_rate("EURUSD") is None

    def test_get_sl_hit_rate_all(self):
        for _ in range(5):
            risk_module.record_trade_outcome("EURUSD", "sl")
        for _ in range(5):
            risk_module.record_trade_outcome("GBPUSD", "tp")

        rates = risk_module.get_sl_hit_rate_all()
        assert "EURUSD" in rates
        assert rates["EURUSD"] == 1.0
        assert "GBPUSD" in rates
        assert rates["GBPUSD"] == 0.0

    def test_sl_hit_rate_window_limit(self):
        # Fill past the deque maxlen (SL_HIT_RATE_WINDOW=20)
        # First 10 sl, then 20 tp — last 20 entries are all tp
        for i in range(30):
            risk_module.record_trade_outcome("EURUSD", "sl" if i < 10 else "tp")
        rate = risk_module.get_sl_hit_rate("EURUSD")
        assert rate is not None
        # Last 20: 0 sl + 20 tp = 0.0
        assert rate == 0.0


# ── Reset ───────────────────────────────────────────────────────────────


class TestReset:
    def test_reset_clears_sl_hit_rates(self):
        for _ in range(10):
            risk_module.record_trade_outcome("EURUSD", "sl")
        risk_module.reset()
        assert risk_module.get_sl_hit_rate("EURUSD") is None
        assert risk_module.get_sl_hit_rate_all() == {}

    def test_reset_clears_cache(self):
        risk_module._default_registry._cache["test"] = "value"
        risk_module.reset()
        assert risk_module._default_registry._cache == {}


# ── Evaluate ────────────────────────────────────────────────────────────


class TestEvaluate:
    def test_low_risk_no_sl_hits(self, monkeypatch, shadow_intelligence):
        monkeypatch.setattr(risk_registry, "get_shadow_intelligence", lambda asset, **kw: shadow_intelligence)
        result = risk_module.evaluate("EURUSD")
        assert result["risk_level"] == "LOW"
        assert result["risk_score"] < 0.3
        assert result["exposure_multiplier"] > 0.7
        assert result["risk_flags"] == []

    def test_high_drift_flags_raised(self, monkeypatch):
        high_drift = {
            "drift_scores": {
                "model_drift": 0.8,
                "signal_drift": 0.7,
                "pnl_drift": 0.9,
                "feature_stability": 0.8,
                "regime_consistency": 0.7,
            },
            "details": {},
        }
        monkeypatch.setattr(risk_registry, "get_shadow_intelligence", lambda asset, **kw: high_drift)
        result = risk_module.evaluate("EURUSD")
        assert result["risk_level"] == "HIGH"
        assert "MODEL_DRIFT" in result["risk_flags"]
        assert "SIGNAL_INSTABILITY" in result["risk_flags"]
        assert "PNL_DEGRADATION" in result["risk_flags"]
        assert result["recommended_action"] == "PAUSE"

    def test_sl_hit_rate_critical_halts(self, monkeypatch, shadow_intelligence):
        monkeypatch.setattr(risk_registry, "get_shadow_intelligence", lambda asset, **kw: shadow_intelligence)
        for _ in range(15):
            risk_module.record_trade_outcome("EURUSD", "sl")
        for _ in range(5):
            risk_module.record_trade_outcome("EURUSD", "tp")

        result = risk_module.evaluate("EURUSD")
        assert "EXCESSIVE_SL_HITS" in result["risk_flags"]
        assert result["recommended_action"] == "PAUSE"

    def test_sl_hit_rate_elevated_triggers_monitor(self, monkeypatch, shadow_intelligence):
        monkeypatch.setattr(risk_registry, "get_shadow_intelligence", lambda asset, **kw: shadow_intelligence)
        for _ in range(9):
            risk_module.record_trade_outcome("EURUSD", "sl")
        for _ in range(11):
            risk_module.record_trade_outcome("EURUSD", "tp")

        result = risk_module.evaluate("EURUSD")
        assert "ELEVATED_SL_HITS" in result["risk_flags"]
        assert result["recommended_action"] == "MONITOR"

    def test_medium_risk_recommends_reduce(self, monkeypatch):
        medium_drift = {
            "drift_scores": {
                "model_drift": 0.4,
                "signal_drift": 0.3,
                "pnl_drift": 0.35,
                "feature_stability": 0.25,
                "regime_consistency": 0.2,
            },
            "details": {},
        }
        monkeypatch.setattr(risk_registry, "get_shadow_intelligence", lambda asset, **kw: medium_drift)
        result = risk_module.evaluate("EURUSD")
        assert result["risk_level"] == "MEDIUM"
        assert result["recommended_action"] == "REDUCE_RISK"

    def test_fallback_on_exception(self, monkeypatch):
        def failing_get(asset, **kw):
            raise RuntimeError("Shadow unavailable")

        monkeypatch.setattr(risk_registry, "get_shadow_intelligence", failing_get)
        result = risk_module.evaluate("EURUSD")
        # Audit remediation 2026-07-02: fail-closed — HIGH risk + PAUSE,
        # not LOW risk (was a bug where exception silently cleared risk)
        assert result["risk_level"] == "HIGH"
        assert result["recommended_action"] == "PAUSE"
        assert result["exposure_multiplier"] == 0.0
        assert "RISK_GOVERNOR_FAILURE" in result["risk_flags"]


# ── Get latest ──────────────────────────────────────────────────────────


class TestGetLatest:
    def test_get_latest_single_asset(self):
        risk_module._default_registry._cache["EURUSD"] = {"risk_level": "LOW"}
        assert risk_module.get_latest("EURUSD") == {"risk_level": "LOW"}
        assert risk_module.get_latest("GBPUSD") is None

    def test_get_latest_all(self):
        risk_module._default_registry._cache["EURUSD"] = {"risk_level": "LOW"}
        risk_module._default_registry._cache["GBPUSD"] = {"risk_level": "MEDIUM"}
        all_results = risk_module.get_latest()
        assert len(all_results) == 2
        assert all_results["EURUSD"]["risk_level"] == "LOW"


# ── Explanations ────────────────────────────────────────────────────────


class TestExplanations:
    def test_no_drift_explanation(self):
        explanations = risk_module._generate_explanations(
            {"model_drift": 0.05, "signal_drift": 0.03}, [], sl_rate=None
        )
        assert "No significant drift detected" in explanations[0]

    def test_model_drift_explanation(self):
        explanations = risk_module._generate_explanations({"model_drift": 0.5}, ["MODEL_DRIFT"])
        assert "KL" in explanations[0]
        assert "0.50" in explanations[0]

    def test_sl_hit_explanations(self):
        explanations = risk_module._generate_explanations(
            {"pnl_drift": 0.1}, ["EXCESSIVE_SL_HITS"], sl_rate=0.60
        )
        assert "60.0%" in explanations[0]
