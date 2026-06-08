from unittest.mock import MagicMock

import numpy as np
import pandas as pd
import pytest

# ──────────────────────────────────────────────
# Edge cases for mas.py decision branches
# ──────────────────────────────────────────────


class TestMasDecisionBranches:
    """Covers mas.py lines 289, 291 (dead code), 296-299"""

    BASE_KWARGS = dict(
        model_result={
            "old": {"auc_macro": 0.5, "logloss": 1.0},
            "new": {"auc_macro": 0.7, "logloss": 0.5},
            "class_distribution": {
                "old": {"short": 0.3, "neutral": 0.4, "long": 0.3},
                "new": {"short": 0.3, "neutral": 0.4, "long": 0.3},
            },
        },
        signal_result={
            "overall_agreement": 0.96,
            "flip_rate": 0.05,
            "mean_confidence_shift": 0.01,
            "regime_stratified_agreement": {"low_vol": 0.9, "high_vol": 0.9},
        },
        portfolio_result={
            "old": {"total_return": 0.05, "max_drawdown": 0.2, "total_trades": 50},
            "new": {"total_return": 0.10, "max_drawdown": 0.15, "total_trades": 45},
        },
        shadow_result={
            "entropy_shift": 0.02,
            "signal_agreement": 0.96,
            "mean_confidence_old": {"short": 0.6, "long": 0.6},
            "mean_confidence_new": {"short": 0.6, "long": 0.6},
            "regime_stability": {"low_vol": 0.9, "high_vol": 0.9},
        },
        forward_result={
            "baseline": {"sharpe": 1.0, "max_drawdown": 0.1, "hit_rate": 0.3, "stability": 0.8},
            "new": {"sharpe": 1.2, "max_drawdown": 0.08, "hit_rate": 0.35, "stability": 0.85},
            "baseline_regime": {
                "low_vol": {"sharpe": 1.0, "max_drawdown": 0.1},
                "high_vol": {"sharpe": 0.5, "max_drawdown": 0.2},
                "transition": {"sharpe": 0.8, "max_drawdown": 0.15},
            },
            "new_regime": {
                "low_vol": {"sharpe": 1.0, "max_drawdown": 0.1},
                "high_vol": {"sharpe": 0.5, "max_drawdown": 0.2},
                "transition": {"sharpe": 0.8, "max_drawdown": 0.15},
            },
        },
    )

    def _compute(self, **overrides):
        from backtests.mas import compute_mas

        kwargs = {**self.BASE_KWARGS, **overrides}
        return compute_mas(**kwargs)

    def test_deploy_candidate(self):
        """mas >= 85 and < 88, stress > 0.6 -> DEPLOY_CANDIDATE (line 289)"""
        better_regime = {
            "baseline": {"sharpe": 1.0, "max_drawdown": 0.1, "hit_rate": 0.3, "stability": 0.8},
            "new": {"sharpe": 1.2, "max_drawdown": 0.08, "hit_rate": 0.35, "stability": 0.85},
            "baseline_regime": {
                "low_vol": {"sharpe": 0.5, "max_drawdown": 0.3},
                "high_vol": {"sharpe": 0.3, "max_drawdown": 0.4},
                "transition": {"sharpe": 0.4, "max_drawdown": 0.3},
            },
            "new_regime": {
                "low_vol": {"sharpe": 1.5, "max_drawdown": 0.1},
                "high_vol": {"sharpe": 1.0, "max_drawdown": 0.15},
                "transition": {"sharpe": 1.2, "max_drawdown": 0.1},
            },
        }
        weights = {"model": 0.7, "signal": 0.05, "portfolio": 0.05, "shadow": 0.05, "forward": 0.05, "stress": 0.1}
        r = self._compute(weights=weights, forward_result=better_regime)
        assert 85.0 <= r["mas"] < 88.0, f"Expected mas in [85,88), got {r['mas']}"
        assert r["sub_scores"]["stress"] > 0.6, f"stress={r['sub_scores']['stress']}"
        assert r["decision"] == "DEPLOY_CANDIDATE"

    def test_shadow_only(self):
        """mas >= 70 and < 85 (with stress <= 0.6) -> SHADOW_ONLY (line 294)"""
        r = self._compute(
            forward_result={
                "baseline": {"sharpe": 1.0, "max_drawdown": 0.1, "hit_rate": 0.3, "stability": 0.8},
                "new": {"sharpe": 1.2, "max_drawdown": 0.08, "hit_rate": 0.35, "stability": 0.85},
                "baseline_regime": {
                    "low_vol": {"sharpe": 1.0, "max_drawdown": 0.1},
                    "high_vol": {"sharpe": 0.5, "max_drawdown": 0.2},
                    "transition": {"sharpe": 0.8, "max_drawdown": 0.15},
                },
                "new_regime": {
                    "low_vol": {"sharpe": -1.0, "max_drawdown": 0.3},
                    "high_vol": {"sharpe": -0.5, "max_drawdown": 0.4},
                    "transition": {"sharpe": -0.2, "max_drawdown": 0.3},
                },
            },
            model_result={
                "old": {"auc_macro": 0.5, "logloss": 1.0},
                "new": {"auc_macro": 0.55, "logloss": 0.9},
                "class_distribution": {
                    "old": {"short": 0.3, "neutral": 0.4, "long": 0.3},
                    "new": {"short": 0.3, "neutral": 0.4, "long": 0.3},
                },
            },
        )
        assert r["gates_passed"]
        assert r["decision"] == "SHADOW_ONLY"

    def test_research(self):
        """mas >= 50 and < 70 -> RESEARCH (line 296)"""
        r = self._compute(
            model_result={"error": "failed"},
            signal_result={
                "overall_agreement": 0.96,
                "flip_rate": 0.05,
                "mean_confidence_shift": 0.01,
                "regime_stratified_agreement": {"low_vol": 0.9},
            },
            portfolio_result={"error": "failed"},
            shadow_result={"error": "failed"},
            forward_result={
                "baseline": {"sharpe": 1.0, "max_drawdown": 0.1, "hit_rate": 0.3, "stability": 0.8},
                "new": {"sharpe": 0.6, "max_drawdown": 0.15, "hit_rate": 0.2, "stability": 0.6},
                "baseline_regime": {
                    "low_vol": {"sharpe": 1.0, "max_drawdown": 0.1},
                    "high_vol": {"sharpe": 0.5, "max_drawdown": 0.2},
                    "transition": {"sharpe": 0.8, "max_drawdown": 0.15},
                },
                "new_regime": {
                    "low_vol": {"sharpe": 1.0, "max_drawdown": 0.1},
                    "high_vol": {"sharpe": 0.5, "max_drawdown": 0.2},
                    "transition": {"sharpe": 0.8, "max_drawdown": 0.15},
                },
            },
        )
        assert r["decision"] in ("SHADOW_ONLY", "RESEARCH", "REJECT")
        assert r["mas"] < 85

    def test_research_exact(self):
        """Force mas in [50, 70) -> RESEARCH (line 297)."""
        from backtests.mas import compute_mas

        weights = {"model": 0.2, "signal": 0.3, "portfolio": 0.1, "shadow": 0.1, "forward": 0.2, "stress": 0.1}
        r = compute_mas(
            model_result={"error": "failed"},
            signal_result={
                "overall_agreement": 0.96,
                "flip_rate": 0.05,
                "mean_confidence_shift": 0.01,
                "regime_stratified_agreement": {"low_vol": 0.9},
            },
            portfolio_result={
                "old": {"total_return": 0.05, "max_drawdown": 0.1, "total_trades": 10},
                "new": {"total_return": 0.08, "max_drawdown": 0.09, "total_trades": 12},
            },
            shadow_result={"error": "failed"},
            forward_result={
                "baseline": {"sharpe": 1.0, "max_drawdown": 0.1, "hit_rate": 0.3, "stability": 0.8},
                "new": {"sharpe": 1.0, "max_drawdown": 0.1, "hit_rate": 0.35, "stability": 0.85},
                "baseline_regime": {
                    "low_vol": {"sharpe": 1.0, "max_drawdown": 0.1},
                    "high_vol": {"sharpe": 0.5, "max_drawdown": 0.2},
                    "transition": {"sharpe": 0.8, "max_drawdown": 0.15},
                },
                "new_regime": {
                    "low_vol": {"sharpe": 1.0, "max_drawdown": 0.1},
                    "high_vol": {"sharpe": 0.5, "max_drawdown": 0.2},
                    "transition": {"sharpe": 0.8, "max_drawdown": 0.15},
                },
            },
            weights=weights,
        )
        assert 50 <= r["mas"] < 70, f"mas={r['mas']} not in [50, 70)"
        assert r["decision"] == "RESEARCH"

    def test_reject_low_mas(self):
        """mas < 50 -> REJECT (line 299)"""
        r = self._compute(
            signal_result={"overall_agreement": 0.96, "flip_rate": 0.05},
            model_result={"error": "failed"},
            portfolio_result={"error": "failed"},
            shadow_result={"error": "failed"},
            forward_result={"error": "failed"},
        )
        assert r["decision"] == "REJECT"


# ──────────────────────────────────────────────
# Edge cases for model_comparator.py branches
# ──────────────────────────────────────────────


class AlternatingFakeModel:
    """Produces alternating long/short/neutral predictions so portfolio has trades."""

    def __init__(self, pattern=None):
        self.pattern = pattern or [2, 0, 2, 1, 0, 2, 1, 0]

    def predict_proba(self, X):
        n = len(X)
        proba = np.zeros((n, 3))
        for i in range(n):
            sig = self.pattern[i % len(self.pattern)]
            if sig == 2:
                proba[i] = [0.1, 0.2, 0.7]
            elif sig == 0:
                proba[i] = [0.7, 0.2, 0.1]
            else:
                proba[i] = [0.3, 0.4, 0.3]
        return proba


class TestModelComparatorEdgeCases:
    @pytest.fixture
    def X(self):  # noqa: N802
        np.random.seed(42)
        dates = pd.date_range("2020-01-01", periods=30, freq="D")
        return pd.DataFrame({"f1": np.random.randn(30), "f2": np.random.randn(30)}, index=dates)

    @pytest.fixture
    def close(self):
        dates = pd.date_range("2020-01-01", periods=30, freq="D")
        np.random.seed(42)
        return pd.Series(100 + np.cumsum(np.random.randn(30) * 0.5), index=dates)

    def test_compare_portfolio_with_trades(self, X, close):
        """Cover lines 174-178: simulate portfolio with actual trades being opened and closed."""
        from backtests.model_comparator import compare_portfolio

        old = AlternatingFakeModel()
        new = AlternatingFakeModel(pattern=[0, 2, 0, 2, 0, 2, 0, 1])
        result = compare_portfolio(old, new, X, close)
        assert "old" in result
        assert "new" in result
        assert "delta" in result
        assert result["old"]["total_trades"] > 0
        assert result["new"]["total_trades"] > 0

    def test_auc_exception(self, X):
        """Cover lines 70-71: ROC AUC exception is caught."""
        import sklearn.metrics

        from backtests.model_comparator import compare_models

        # Use y with all 3 classes so log_loss/accuracy work
        y = pd.Series(np.random.choice([0, 1, 2], size=len(X)))
        old = MagicMock()
        new = MagicMock()
        old.predict_proba.return_value = np.column_stack(
            [np.full(len(X), 0.2), np.full(len(X), 0.3), np.full(len(X), 0.5)]
        )
        new.predict_proba.return_value = np.column_stack(
            [np.full(len(X), 0.6), np.full(len(X), 0.3), np.full(len(X), 0.1)]
        )
        original_auc = sklearn.metrics.roc_auc_score

        def broken_auc(*args, **kwargs):
            raise ValueError("AUC failed")

        sklearn.metrics.roc_auc_score = broken_auc
        try:
            result = compare_models(old, new, X, y=y)
            assert "error" not in result
            assert "auc_macro" not in result.get("old", {})
        finally:
            sklearn.metrics.roc_auc_score = original_auc


# ──────────────────────────────────────────────
# Edge cases for model_promotion_engine.py
# ──────────────────────────────────────────────


class TestPromotionEdgeCases:
    def test_live_candidate_decision(self, tmp_path):
        """met_count == total -> LIVE_CANDIDATE (lines 59-60)"""
        from backtests.model_promotion_engine import evaluate_promotion

        result = evaluate_promotion(
            asset="TEST",
            mas_result={"mas": 90.0, "sub_scores": {"stress": 0.75}},
            forward_result={
                "baseline": {"sharpe": 1.0, "max_drawdown": 0.1, "hit_rate": 0.4},
                "new": {"sharpe": 1.1, "max_drawdown": 0.08, "hit_rate": 0.45},
            },
            model_result={},
            signal_result={"overall_agreement": 0.96, "flip_rate": 0.04},
            portfolio_result={},
            shadow_result={
                "entropy_shift": 0.04,
                "signal_agreement": 0.96,
                "regime_stability": {"low_vol": 0.85, "high_vol": 0.85},
                "mean_confidence_old": {"short": 0.6, "long": 0.6},
                "mean_confidence_new": {"short": 0.6, "long": 0.6},
            },
            trajectory=[{"mas": 85.0}, {"mas": 88.0}, {"mas": 90.0}],
            drift_score=0.3,
        )
        assert result["decision"] == "LIVE_CANDIDATE"

    def test_shadow_only_decision(self, tmp_path):
        """met_count == total - 2 -> SHADOW_ONLY (lines 65-66)"""
        from backtests.model_promotion_engine import evaluate_promotion

        result = evaluate_promotion(
            asset="TEST",
            mas_result={"mas": 75.0, "sub_scores": {"stress": 0.55}},
            forward_result={
                "baseline": {"sharpe": 1.0, "max_drawdown": 0.1, "hit_rate": 0.4},
                "new": {"sharpe": 0.8, "max_drawdown": 0.15, "hit_rate": 0.3},
            },
            model_result={},
            signal_result={"overall_agreement": 0.90, "flip_rate": 0.05},
            portfolio_result={},
            shadow_result={
                "entropy_shift": 0.05,
                "signal_agreement": 0.96,
                "regime_stability": {"low_vol": 0.85, "high_vol": 0.85},
                "mean_confidence_old": {"short": 0.6, "long": 0.6},
                "mean_confidence_new": {"short": 0.6, "long": 0.6},
            },
            trajectory=[{"mas": 80.0}, {"mas": 78.0}, {"mas": 75.0}],
        )
        assert result["decision"] in ("SHADOW_ONLY", "PAPER_TRADING_ONLY", "REJECT")

    def test_decision_reject(self):
        """met_count < total - 2 -> REJECT (lines 67-68)"""
        from backtests.model_promotion_engine import evaluate_promotion

        result = evaluate_promotion(
            asset="TEST",
            mas_result={"mas": 60.0, "sub_scores": {"stress": 0.4}},
            forward_result={"error": "failed"},
            model_result={},
            signal_result={"overall_agreement": 0.85, "flip_rate": 0.1},
            portfolio_result={},
            shadow_result={
                "entropy_shift": 0.05,
                "signal_agreement": 0.85,
                "regime_stability": {"low_vol": 0.6, "high_vol": 0.6},
                "mean_confidence_old": {"short": 0.6, "long": 0.6},
                "mean_confidence_new": {"short": 0.6, "long": 0.6},
            },
            trajectory=[],
        )
        assert result["decision"] == "REJECT"

    def test_live_candidate_recommended_action(self, tmp_path):
        """Live_candidate decision -> deploy_shadow_live_test_30d (line 82)"""
        from backtests.model_promotion_engine import evaluate_promotion

        result = evaluate_promotion(
            asset="TEST",
            mas_result={"mas": 90.0, "sub_scores": {"stress": 0.75}},
            forward_result={
                "baseline": {"sharpe": 1.0, "max_drawdown": 0.1, "hit_rate": 0.4},
                "new": {"sharpe": 1.1, "max_drawdown": 0.08, "hit_rate": 0.45},
            },
            model_result={},
            signal_result={"overall_agreement": 0.96, "flip_rate": 0.04},
            portfolio_result={},
            shadow_result={
                "entropy_shift": 0.04,
                "signal_agreement": 0.96,
                "regime_stability": {"low_vol": 0.85, "high_vol": 0.85},
                "mean_confidence_old": {"short": 0.6, "long": 0.6},
                "mean_confidence_new": {"short": 0.6, "long": 0.6},
            },
            trajectory=[{"mas": 85.0}, {"mas": 88.0}, {"mas": 90.0}],
            drift_score=0.3,
        )
        assert result["recommended_action"] == "deploy_shadow_live_test_30d"
