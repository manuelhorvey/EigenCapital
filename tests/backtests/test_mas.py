import math

from backtests.mas import (
    _clip01,
    _entropy,
    _safe,
    compute_mas,
    hard_gates,
    score_forward,
    score_model,
    score_portfolio,
    score_shadow,
    score_signal,
    score_stress,
)


class TestSafe:
    def test_returns_value_when_not_none(self):
        assert _safe(5.0) == 5.0
        assert _safe(0) == 0
        assert _safe("a") == "a"

    def test_returns_default_when_none(self):
        assert _safe(None) == 0.0
        assert _safe(None, 1.0) == 1.0


class TestClip01:
    def test_clips_below_zero(self):
        assert _clip01(-0.5) == 0.0
        assert _clip01(-0.0) == 0.0

    def test_clips_above_one(self):
        assert _clip01(1.5) == 1.0
        assert _clip01(1.0) == 1.0

    def test_preserves_in_range(self):
        assert _clip01(0.5) == 0.5
        assert _clip01(0.0) == 0.0


class TestEntropy:
    def test_zero_when_total_zero(self):
        assert _entropy({}) == 0.0

    def test_zero_when_single_class(self):
        h = _entropy({"short": 10, "neutral": 0, "long": 0})
        assert abs(h) < 1e-10

    def test_maximum_when_uniform(self):
        h = _entropy({"short": 1, "neutral": 1, "long": 1})
        expected = -3 * (1 / 3) * math.log(1 / 3 + 1e-12)
        assert abs(h - expected) < 1e-10

    def test_missing_keys_treated_as_zero(self):
        h = _entropy({"short": 1})
        assert abs(h) < 1e-10


class TestHardGates:
    def test_all_gates_pass(self):
        passed, failures = hard_gates(
            signal_result={"overall_agreement": 0.96, "flip_rate": 0.05},
            portfolio_result={},
            model_result={},
            shadow_result={
                "class_distribution_shift": {
                    "old": {"short": 0.3, "neutral": 0.4, "long": 0.3},
                    "new": {"short": 0.3, "neutral": 0.4, "long": 0.3},
                }
            },
            forward_result={
                "baseline": {"sharpe": 1.0, "max_drawdown": 0.1},
                "new": {"sharpe": 1.0, "max_drawdown": 0.1},
            },
            drift_score=0.3,
        )
        assert passed
        assert failures == []

    def test_gate_a_signal_agreement_fails(self):
        passed, failures = hard_gates(
            signal_result={"overall_agreement": 0.90, "flip_rate": 0.0},
            portfolio_result={},
            model_result={},
            shadow_result={
                "class_distribution_shift": {
                    "old": {"short": 0.3, "neutral": 0.4, "long": 0.3},
                    "new": {"short": 0.3, "neutral": 0.4, "long": 0.3},
                }
            },
            forward_result={
                "baseline": {"sharpe": 1.0, "max_drawdown": 0.1},
                "new": {"sharpe": 1.0, "max_drawdown": 0.1},
            },
        )
        assert not passed
        assert any("Gate A" in f for f in failures)

    def test_gate_b_sharpe_decay_too_large(self):
        passed, failures = hard_gates(
            signal_result={"overall_agreement": 0.96, "flip_rate": 0.0},
            portfolio_result={},
            model_result={},
            shadow_result={
                "class_distribution_shift": {
                    "old": {"short": 0.3, "neutral": 0.4, "long": 0.3},
                    "new": {"short": 0.3, "neutral": 0.4, "long": 0.3},
                }
            },
            forward_result={
                "baseline": {"sharpe": 1.0, "max_drawdown": 0.1},
                "new": {"sharpe": 0.5, "max_drawdown": 0.1},
            },
        )
        assert not passed
        assert any("Gate B" in f for f in failures)

    def test_gate_b_drawdown_too_large(self):
        passed, failures = hard_gates(
            signal_result={"overall_agreement": 0.96, "flip_rate": 0.0},
            portfolio_result={},
            model_result={},
            shadow_result={
                "class_distribution_shift": {
                    "old": {"short": 0.3, "neutral": 0.4, "long": 0.3},
                    "new": {"short": 0.3, "neutral": 0.4, "long": 0.3},
                }
            },
            forward_result={
                "baseline": {"sharpe": 1.0, "max_drawdown": 0.1},
                "new": {"sharpe": 1.0, "max_drawdown": 0.25},
            },
        )
        assert not passed
        assert any("Gate B" in f and "drawdown" in f for f in failures)

    def test_gate_c_drift_score_fails(self):
        passed, failures = hard_gates(
            signal_result={"overall_agreement": 0.96, "flip_rate": 0.0},
            portfolio_result={},
            model_result={},
            shadow_result={
                "class_distribution_shift": {
                    "old": {"short": 0.3, "neutral": 0.4, "long": 0.3},
                    "new": {"short": 0.3, "neutral": 0.4, "long": 0.3},
                }
            },
            forward_result={
                "baseline": {"sharpe": 1.0, "max_drawdown": 0.1},
                "new": {"sharpe": 1.0, "max_drawdown": 0.1},
            },
            drift_score=0.8,
        )
        assert not passed
        assert any("Gate C" in f for f in failures)

    def test_gate_d_entropy_ratio_outside_range(self):
        # old: very concentrated (low entropy), new: near-uniform (high entropy) => ratio >> 1.2
        passed, failures = hard_gates(
            signal_result={"overall_agreement": 0.96, "flip_rate": 0.0},
            portfolio_result={},
            model_result={},
            shadow_result={
                "class_distribution_shift": {
                    "old": {"short": 0.9, "neutral": 0.05, "long": 0.05},
                    "new": {"short": 0.33, "neutral": 0.34, "long": 0.33},
                }
            },
            forward_result={
                "baseline": {"sharpe": 1.0, "max_drawdown": 0.1},
                "new": {"sharpe": 1.0, "max_drawdown": 0.1},
            },
        )
        assert not passed
        assert any("Gate D" in f for f in failures)

    def test_baseline_sharpe_zero_does_not_fail(self):
        passed, failures = hard_gates(
            signal_result={"overall_agreement": 0.96, "flip_rate": 0.0},
            portfolio_result={},
            model_result={},
            shadow_result={
                "class_distribution_shift": {
                    "old": {"short": 0.3, "neutral": 0.4, "long": 0.3},
                    "new": {"short": 0.3, "neutral": 0.4, "long": 0.3},
                }
            },
            forward_result={
                "baseline": {"sharpe": 0.0, "max_drawdown": 0.0},
                "new": {"sharpe": 0.0, "max_drawdown": 0.0},
            },
        )
        assert passed

    def test_baseline_drawdown_zero_does_not_fail(self):
        passed, failures = hard_gates(
            signal_result={"overall_agreement": 0.96, "flip_rate": 0.0},
            portfolio_result={},
            model_result={},
            shadow_result={
                "class_distribution_shift": {
                    "old": {"short": 0.3, "neutral": 0.4, "long": 0.3},
                    "new": {"short": 0.3, "neutral": 0.4, "long": 0.3},
                }
            },
            forward_result={
                "baseline": {"sharpe": 1.0, "max_drawdown": 0.0},
                "new": {"sharpe": 1.0, "max_drawdown": 0.0},
            },
        )
        assert passed

    def test_drift_score_none_does_not_fail(self):
        passed, failures = hard_gates(
            signal_result={"overall_agreement": 0.96, "flip_rate": 0.0},
            portfolio_result={},
            model_result={},
            shadow_result={
                "class_distribution_shift": {
                    "old": {"short": 0.3, "neutral": 0.4, "long": 0.3},
                    "new": {"short": 0.3, "neutral": 0.4, "long": 0.3},
                }
            },
            forward_result={
                "baseline": {"sharpe": 1.0, "max_drawdown": 0.1},
                "new": {"sharpe": 1.0, "max_drawdown": 0.1},
            },
            drift_score=None,
        )
        assert passed

    def test_empty_class_distribution(self):
        passed, failures = hard_gates(
            signal_result={"overall_agreement": 0.96, "flip_rate": 0.0},
            portfolio_result={},
            model_result={},
            shadow_result={"class_distribution_shift": {"old": {}, "new": {}}},
            forward_result={
                "baseline": {"sharpe": 1.0, "max_drawdown": 0.1},
                "new": {"sharpe": 1.0, "max_drawdown": 0.1},
            },
        )
        assert passed


class TestScoreModel:
    def test_returns_zero_on_error(self):
        assert score_model({"error": "something broke"}) == 0.0

    def test_perfect_model_scores_high(self):
        result = score_model(
            {
                "old": {"auc_macro": 0.5, "logloss": 1.0},
                "new": {"auc_macro": 0.9, "logloss": 0.1},
                "class_distribution": {
                    "old": {"short": 0.3, "neutral": 0.4, "long": 0.3},
                    "new": {"short": 0.3, "neutral": 0.4, "long": 0.3},
                },
            }
        )
        assert 0.0 <= result <= 1.0
        assert result > 0.6

    def test_worse_model_scores_low(self):
        result = score_model(
            {
                "old": {"auc_macro": 0.9, "logloss": 0.1},
                "new": {"auc_macro": 0.5, "logloss": 1.0},
                "class_distribution": {
                    "old": {"short": 0.3, "neutral": 0.4, "long": 0.3},
                    "new": {"short": 0.6, "neutral": 0.3, "long": 0.1},
                },
            }
        )
        assert 0.0 <= result <= 1.0
        assert result < 0.5

    def test_missing_keys_default_gracefully(self):
        result = score_model(
            {
                "old": {},
                "new": {},
                "class_distribution": {"old": {}, "new": {}},
            }
        )
        assert 0.0 <= result <= 1.0


class TestScoreSignal:
    def test_returns_zero_on_error(self):
        assert score_signal({"error": "failed"}) == 0.0

    def test_perfect_signal_scores_high(self):
        result = score_signal(
            {
                "overall_agreement": 1.0,
                "flip_rate": 0.0,
                "mean_confidence_shift": 0.0,
                "regime_stratified_agreement": {"low_vol": 1.0, "high_vol": 1.0, "transition": 1.0},
            }
        )
        assert result > 0.8

    def test_poor_signal_scores_low(self):
        result = score_signal(
            {
                "overall_agreement": 0.5,
                "flip_rate": 0.5,
                "mean_confidence_shift": 0.2,
                "regime_stratified_agreement": {"low_vol": 0.5, "high_vol": 0.5},
            }
        )
        assert result < 0.6

    def test_empty_regime_agreement_does_not_crash(self):
        result = score_signal(
            {
                "overall_agreement": 0.9,
                "flip_rate": 0.1,
                "mean_confidence_shift": 0.01,
                "regime_stratified_agreement": {},
            }
        )
        assert 0.0 <= result <= 1.0


class TestScorePortfolio:
    def test_returns_zero_on_error(self):
        assert score_portfolio({"error": "failed"}) == 0.0

    def test_improving_portfolio_scores_high(self):
        result = score_portfolio(
            {
                "old": {"total_return": 0.05, "max_drawdown": 0.2, "total_trades": 50},
                "new": {"total_return": 0.15, "max_drawdown": 0.1, "total_trades": 40},
            }
        )
        assert result > 0.5

    def test_degrading_portfolio_scores_low(self):
        result = score_portfolio(
            {
                "old": {"total_return": 0.15, "max_drawdown": 0.1, "total_trades": 40},
                "new": {"total_return": 0.05, "max_drawdown": 0.2, "total_trades": 50},
            }
        )
        assert result < 0.7

    def test_missing_keys_default(self):
        result = score_portfolio(
            {
                "old": {},
                "new": {},
            }
        )
        assert 0.0 <= result <= 1.0


class TestScoreShadow:
    def test_returns_zero_on_error(self):
        assert score_shadow({"error": "failed"}) == 0.0

    def test_stable_shadow_scores_high(self):
        result = score_shadow(
            {
                "entropy_shift": 0.01,
                "signal_agreement": 0.98,
                "mean_confidence_old": {"short": 0.6, "long": 0.6},
                "mean_confidence_new": {"short": 0.6, "long": 0.6},
                "regime_stability": {"low_vol": 0.9, "high_vol": 0.9, "transition": 0.9},
            }
        )
        assert result > 0.7

    def test_unstable_shadow_scores_low(self):
        result = score_shadow(
            {
                "entropy_shift": 0.5,
                "signal_agreement": 0.5,
                "mean_confidence_old": {"short": 0.2, "long": 0.2},
                "mean_confidence_new": {"short": 0.8, "long": 0.8},
                "regime_stability": {"low_vol": 0.3, "high_vol": 0.3, "transition": 0.3},
            }
        )
        assert result < 0.5

    def test_empty_regime_stability_defaults_to_one(self):
        result = score_shadow(
            {
                "entropy_shift": 0.0,
                "signal_agreement": 1.0,
                "mean_confidence_old": {"short": 0.6, "long": 0.6},
                "mean_confidence_new": {"short": 0.6, "long": 0.6},
                "regime_stability": {},
            }
        )
        assert result > 0.5


class TestScoreForward:
    def test_returns_zero_on_error(self):
        assert score_forward({"error": "failed"}) == 0.0

    def test_improving_forward_scores_high(self):
        result = score_forward(
            {
                "baseline": {"sharpe": 0.5, "hit_rate": 0.3, "stability": 0.8},
                "new": {"sharpe": 1.5, "hit_rate": 0.5, "stability": 0.9},
            }
        )
        assert result > 0.5

    def test_degrading_forward_scores_low(self):
        result = score_forward(
            {
                "baseline": {"sharpe": 1.5, "hit_rate": 0.5, "stability": 0.9},
                "new": {"sharpe": 0.5, "hit_rate": 0.3, "stability": 0.8},
            }
        )
        assert result < 0.6

    def test_baseline_hit_rate_zero_handled(self):
        result = score_forward(
            {
                "baseline": {"sharpe": 1.0, "hit_rate": 0.0, "stability": 1.0},
                "new": {"sharpe": 1.0, "hit_rate": 0.5, "stability": 1.0},
            }
        )
        assert 0.0 <= result <= 1.0

    def test_missing_keys_default(self):
        result = score_forward(
            {
                "baseline": {},
                "new": {},
            }
        )
        assert 0.0 <= result <= 1.0


class TestScoreStress:
    def test_returns_zero_on_error(self):
        assert score_stress({"error": "failed"}) == 0.0

    def test_stable_stress_scores_mid(self):
        result = score_stress(
            {
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
            }
        )
        assert result == 0.5

    def test_improving_stress_scores_above_mid(self):
        result = score_stress(
            {
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
        )
        assert result > 0.5

    def test_missing_regime_handled(self):
        result = score_stress(
            {
                "baseline_regime": {},
                "new_regime": {},
            }
        )
        assert result == 0.5


class TestComputeMAS:
    def test_gates_fail_returns_reject(self):
        result = compute_mas(
            model_result={},
            signal_result={"overall_agreement": 0.5, "flip_rate": 0.5},
            portfolio_result={},
            shadow_result={"class_distribution_shift": {"old": {}, "new": {}}},
            forward_result={
                "baseline": {"sharpe": 1.0, "max_drawdown": 0.1},
                "new": {"sharpe": 1.0, "max_drawdown": 0.1},
            },
        )
        assert result["decision"] == "REJECT"
        assert result["mas"] == 0.0
        assert not result["gates_passed"]

    def test_gates_pass_computes_mas(self):
        result = compute_mas(
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
                "regime_stratified_agreement": {"low_vol": 0.9, "high_vol": 0.9, "transition": 0.9},
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
                "regime_stability": {"low_vol": 0.9, "high_vol": 0.9, "transition": 0.9},
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
                    "low_vol": {"sharpe": 1.2, "max_drawdown": 0.08},
                    "high_vol": {"sharpe": 0.6, "max_drawdown": 0.18},
                    "transition": {"sharpe": 0.9, "max_drawdown": 0.12},
                },
            },
        )
        assert result["gates_passed"]
        assert result["mas"] > 0
        assert "mas" in result
        assert "delta_mas" in result
        assert "decision" in result
        assert "sub_scores" in result
        assert all(k in result["sub_scores"] for k in ["model", "signal", "portfolio", "shadow", "forward", "stress"])

    def test_with_baseline_mas(self):
        result = compute_mas(
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
            baseline_mas=75.0,
        )
        assert result["delta_mas"] == round(result["mas"] - 75.0, 2)

    def test_decision_accept_when_high(self):
        result = compute_mas(
            model_result={
                "old": {"auc_macro": 0.5, "logloss": 1.0},
                "new": {"auc_macro": 0.999, "logloss": 0.01},
                "class_distribution": {
                    "old": {"short": 0.3, "neutral": 0.4, "long": 0.3},
                    "new": {"short": 0.3, "neutral": 0.4, "long": 0.3},
                },
            },
            signal_result={
                "overall_agreement": 0.99,
                "flip_rate": 0.01,
                "mean_confidence_shift": 0.0,
                "regime_stratified_agreement": {"low_vol": 0.99, "high_vol": 0.99},
            },
            portfolio_result={
                "old": {"total_return": 0.05, "max_drawdown": 0.2, "total_trades": 50},
                "new": {"total_return": 0.30, "max_drawdown": 0.05, "total_trades": 30},
            },
            shadow_result={
                "entropy_shift": 0.01,
                "signal_agreement": 0.99,
                "mean_confidence_old": {"short": 0.7, "long": 0.7},
                "mean_confidence_new": {"short": 0.7, "long": 0.7},
                "regime_stability": {"low_vol": 0.99, "high_vol": 0.99},
            },
            forward_result={
                "baseline": {"sharpe": 1.0, "max_drawdown": 0.1, "hit_rate": 0.3, "stability": 0.8},
                "new": {"sharpe": 2.0, "max_drawdown": 0.05, "hit_rate": 0.4, "stability": 0.95},
                "baseline_regime": {
                    "low_vol": {"sharpe": 1.0, "max_drawdown": 0.1},
                    "high_vol": {"sharpe": 0.5, "max_drawdown": 0.2},
                    "transition": {"sharpe": 0.8, "max_drawdown": 0.15},
                },
                "new_regime": {
                    "low_vol": {"sharpe": 2.0, "max_drawdown": 0.05},
                    "high_vol": {"sharpe": 1.5, "max_drawdown": 0.1},
                    "transition": {"sharpe": 1.5, "max_drawdown": 0.08},
                },
            },
        )
        assert result["decision"] in ("ACCEPT", "DEPLOY_CANDIDATE")
        assert result["mas"] >= 80

    def test_custom_weights(self):
        weights = {"model": 0.5, "signal": 0.1, "portfolio": 0.1, "shadow": 0.1, "forward": 0.1, "stress": 0.1}
        result = compute_mas(
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
                "regime_stratified_agreement": {},
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
                "regime_stability": {},
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
            weights=weights,
        )
        assert result["weights"] == weights
