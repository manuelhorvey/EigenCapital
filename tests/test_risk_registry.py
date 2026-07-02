"""Tests for ``paper_trading/governance/risk_registry.py`` — RiskRegistry."""

from unittest.mock import patch

import pytest

from paper_trading.governance.risk_registry import (
    SL_HIT_RATE_WINDOW,
    RiskRegistry,
)


@pytest.fixture
def registry():
    return RiskRegistry()


# ═══════════════════════════════════════════════════════════════════
# SL hit rate tracking
# ═══════════════════════════════════════════════════════════════════


class TestSlHitRate:
    def test_returns_none_with_fewer_than_5_trades(self, registry):
        for _ in range(4):
            registry.record_trade_outcome("EURUSD", "SL")
        assert registry.get_sl_hit_rate("EURUSD") is None

    def test_returns_rate_after_5_trades(self, registry):
        for _ in range(5):
            registry.record_trade_outcome("EURUSD", "TP")
        assert registry.get_sl_hit_rate("EURUSD") == 0.0

    def test_50_percent_sl_hits(self, registry):
        for _ in range(5):
            registry.record_trade_outcome("EURUSD", "SL")
        for _ in range(5):
            registry.record_trade_outcome("EURUSD", "TP")
        assert registry.get_sl_hit_rate("EURUSD") == 0.5

    def test_tracks_multiple_assets_independently(self, registry):
        for _ in range(5):
            registry.record_trade_outcome("EURUSD", "SL")
        for _ in range(5):
            registry.record_trade_outcome("GBPUSD", "TP")
        assert registry.get_sl_hit_rate("EURUSD") == 1.0
        assert registry.get_sl_hit_rate("GBPUSD") == 0.0

    def test_get_sl_hit_rate_all(self, registry):
        for _ in range(5):
            registry.record_trade_outcome("EURUSD", "SL")
        all_rates = registry.get_sl_hit_rate_all()
        assert "EURUSD" in all_rates
        assert all_rates["EURUSD"] == 1.0

    def test_sliding_window(self, registry):
        # Fill window with TPs, then add one more — oldest drops off
        for _ in range(SL_HIT_RATE_WINDOW):
            registry.record_trade_outcome("EURUSD", "TP")
        registry.record_trade_outcome("EURUSD", "SL")
        rate = registry.get_sl_hit_rate("EURUSD")
        assert rate == 1.0 / SL_HIT_RATE_WINDOW


# ═══════════════════════════════════════════════════════════════════
# SELL tripwire
# ═══════════════════════════════════════════════════════════════════


class TestSellTripwire:
    def test_does_not_record_non_short(self, registry):
        registry.record_sell_side_outcome("EURUSD", "TP", "long")
        assert registry.get_sell_win_rate("EURUSD") is None

    def test_does_not_record_non_tp_sl(self, registry):
        registry.record_sell_side_outcome("EURUSD", "FLIP", "short")
        assert registry.get_sell_win_rate("EURUSD") is None

    def test_records_short_tp_as_win(self, registry):
        for _ in range(5):
            registry.record_sell_side_outcome("EURUSD", "TP", "short")
        assert registry.get_sell_win_rate("EURUSD") == 1.0

    def test_records_short_sl_as_loss(self, registry):
        for _ in range(5):
            registry.record_sell_side_outcome("EURUSD", "SL", "short")
        assert registry.get_sell_win_rate("EURUSD") == 0.0

    def test_tripwire_tripped_below_threshold(self, registry):
        for _ in range(20):
            registry.record_sell_side_outcome("EURUSD", "SL", "short")
        state = registry.get_sell_tripwire_state("EURUSD", sell_only=True)
        assert state["tripped"] is True

    def test_tripwire_not_tripped_above_threshold(self, registry):
        for _ in range(20):
            registry.record_sell_side_outcome("EURUSD", "TP", "short")
        state = registry.get_sell_tripwire_state("EURUSD", sell_only=True)
        assert state["tripped"] is False

    def test_tripwire_requires_sell_only_flag(self, registry):
        for _ in range(20):
            registry.record_sell_side_outcome("EURUSD", "SL", "short")
        # sell_only=False — tripwire tracks but doesn't trip
        state = registry.get_sell_tripwire_state("EURUSD", sell_only=False)
        assert state["tripped"] is False
        assert state["win_rate"] is not None


# ═══════════════════════════════════════════════════════════════════
# Risk evaluation
# ═══════════════════════════════════════════════════════════════════


class TestEvaluate:
    def test_returns_fallback_on_exception(self, registry):
        with patch(
            "paper_trading.governance.risk_registry.get_shadow_intelligence",
            side_effect=ValueError("test error"),
        ):
            result = registry.evaluate("EURUSD")
        assert result["risk_level"] == "LOW"
        assert result["risk_score"] == 0.0

    def test_returns_low_with_no_drift(self, registry):
        with patch(
            "paper_trading.governance.risk_registry.get_shadow_intelligence",
            return_value={"drift_scores": {}, "details": {}},
        ):
            result = registry.evaluate("EURUSD")
        assert result["risk_level"] == "LOW"
        assert result["recommended_action"] == "NORMAL"

    def test_drift_increases_risk(self, registry):
        with patch(
            "paper_trading.governance.risk_registry.get_shadow_intelligence",
            return_value={
                "drift_scores": {
                    "model_drift": 0.5,
                    "signal_drift": 0.5,
                    "pnl_drift": 0.5,
                    "feature_stability": 0.5,
                    "regime_consistency": 0.5,
                },
                "details": {},
            },
        ):
            result = registry.evaluate("EURUSD")
        assert result["risk_level"] in ("MEDIUM", "HIGH")

    def test_excessive_sl_hits_pauses(self, registry):
        for _ in range(20):
            registry.record_trade_outcome("EURUSD", "SL")
        with patch(
            "paper_trading.governance.risk_registry.get_shadow_intelligence",
            return_value={"drift_scores": {}, "details": {}},
        ):
            result = registry.evaluate("EURUSD")
        assert result["recommended_action"] == "PAUSE"
        assert "EXCESSIVE_SL_HITS" in result["risk_flags"]

    def test_sell_tripwire_pauses(self, registry):
        for _ in range(20):
            registry.record_sell_side_outcome("EURUSD", "SL", "short")
        with patch(
            "paper_trading.governance.risk_registry.get_shadow_intelligence",
            return_value={"drift_scores": {}, "details": {}},
        ):
            result = registry.evaluate("EURUSD")
        assert result["recommended_action"] == "PAUSE"
        assert "SELL_TRIPWIRE" in result["risk_flags"]

    def test_high_risk_pauses(self, registry):
        with patch(
            "paper_trading.governance.risk_registry.get_shadow_intelligence",
            return_value={
                "drift_scores": {
                    k: 0.9
                    for k in ("model_drift", "signal_drift", "pnl_drift", "feature_stability", "regime_consistency")
                },
                "details": {},
            },
        ):
            result = registry.evaluate("EURUSD")
        assert result["recommended_action"] == "PAUSE"

    def test_get_latest_returns_cached(self, registry):
        with patch(
            "paper_trading.governance.risk_registry.get_shadow_intelligence",
            return_value={"drift_scores": {}, "details": {}},
        ):
            result = registry.evaluate("EURUSD")
            assert registry.get_latest("EURUSD") is result

    def test_get_latest_all(self, registry):
        assert registry.get_latest() == {}


# ═══════════════════════════════════════════════════════════════════
# Lifecycle
# ═══════════════════════════════════════════════════════════════════


class TestReset:
    def test_clears_all_state(self, registry):
        for _ in range(5):
            registry.record_trade_outcome("EURUSD", "SL")
        registry.record_sell_side_outcome("EURUSD", "TP", "short")
        registry.reset()
        assert registry.get_sl_hit_rate("EURUSD") is None
        assert registry.get_sell_win_rate("EURUSD") is None
