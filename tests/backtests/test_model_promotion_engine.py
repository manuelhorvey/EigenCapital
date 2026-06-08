import os

from backtests.model_promotion_engine import (
    _check_consistency,
    _check_performance,
    _check_safety,
    _check_stability,
    evaluate_promotion,
)


class TestCheckPerformance:
    def test_forward_test_error(self):
        result = _check_performance({"error": "failed"})
        assert not result["met"]
        assert "Performance:" in result["failures"][0]

    def test_all_conditions_met(self):
        result = _check_performance(
            {
                "baseline": {"sharpe": 1.0, "max_drawdown": 0.1, "hit_rate": 0.35},
                "new": {"sharpe": 1.2, "max_drawdown": 0.08, "hit_rate": 0.45},
            }
        )
        assert result["met"]
        assert result["forward_sharpe"] == 1.2

    def test_sharpe_fails(self):
        result = _check_performance(
            {
                "baseline": {"sharpe": 1.0, "max_drawdown": 0.1, "hit_rate": 0.35},
                "new": {"sharpe": 0.5, "max_drawdown": 0.08, "hit_rate": 0.45},
            }
        )
        assert not result["met"]
        assert any("Sharpe" in f for f in result["failures"])

    def test_drawdown_fails(self):
        result = _check_performance(
            {
                "baseline": {"sharpe": 1.0, "max_drawdown": 0.1, "hit_rate": 0.35},
                "new": {"sharpe": 1.0, "max_drawdown": 0.2, "hit_rate": 0.35},
            }
        )
        assert not result["met"]
        assert any("drawdown" in f for f in result["failures"])

    def test_hit_rate_fails(self):
        result = _check_performance(
            {
                "baseline": {"sharpe": 1.0, "max_drawdown": 0.1, "hit_rate": 0.35},
                "new": {"sharpe": 1.0, "max_drawdown": 0.08, "hit_rate": 0.15},
            }
        )
        assert not result["met"]
        assert any("hit rate" in f.lower() for f in result["failures"])

    def test_baseline_drawdown_zero(self):
        result = _check_performance(
            {
                "baseline": {"sharpe": 1.0, "max_drawdown": 0.0, "hit_rate": 0.35},
                "new": {"sharpe": 1.0, "max_drawdown": 0.05, "hit_rate": 0.35},
            }
        )
        assert result["met"]


class TestCheckStability:
    def test_all_conditions_met(self):
        result = _check_stability(
            {"sub_scores": {"stress": 0.75}},
            {},
            drift_score=0.3,
        )
        assert result["met"]

    def test_stress_too_low(self):
        result = _check_stability(
            {"sub_scores": {"stress": 0.4}},
            {},
            drift_score=0.3,
        )
        assert not result["met"]
        assert any("M_stress" in f for f in result["failures"])

    def test_drift_too_high(self):
        result = _check_stability(
            {"sub_scores": {"stress": 0.75}},
            {},
            drift_score=0.8,
        )
        assert not result["met"]
        assert any("drift" in f for f in result["failures"])

    def test_missing_stress_defaults_to_zero(self):
        result = _check_stability(
            {"sub_scores": {}},
            {},
        )
        assert not result["met"]

    def test_drift_none_ignored(self):
        result = _check_stability(
            {"sub_scores": {"stress": 0.75}},
            {},
            drift_score=None,
        )
        assert result["met"]


class TestCheckConsistency:
    def test_short_trajectory(self):
        result = _check_consistency(
            [{"mas": 75.0}],
            {"mas": 75.0},
        )
        assert result["met"]
        assert result["mas_slope"] is None

    def test_stable_trajectory(self):
        traj = [{"mas": 75.0}, {"mas": 76.0}, {"mas": 77.0}]
        result = _check_consistency(traj, {"mas": 77.0})
        assert result["met"]

    def test_degrading_slope(self):
        traj = [{"mas": 80.0}, {"mas": 75.0}, {"mas": 70.0}]
        result = _check_consistency(traj, {"mas": 70.0})
        assert not result["met"]
        assert any("slope" in f for f in result["failures"])

    def test_high_variance(self):
        traj = [{"mas": 70.0}, {"mas": 85.0}, {"mas": 72.0}, {"mas": 88.0}, {"mas": 71.0}]
        result = _check_consistency(traj, {"mas": 71.0})
        assert any("MAS std" in f or "variance" in f for f in result["failures"])

    def test_mas_below_70(self):
        traj = [{"mas": 75.0}, {"mas": 74.0}, {"mas": 73.0}]
        result = _check_consistency(traj, {"mas": 65.0})
        assert not result["met"]
        assert any("MAS" in f and "70" in f for f in result["failures"])


class TestCheckSafety:
    def test_all_conditions_met(self):
        result = _check_safety(
            signal_result={"overall_agreement": 0.96},
            forward_result={"new": {"hit_rate": 0.30}},
            shadow_result={
                "entropy_shift": 0.05,
                "regime_stability": {"low_vol": 0.8, "high_vol": 0.8, "transition": 0.8},
            },
            mas_result={},
        )
        assert result["met"]

    def test_signal_agreement_fails(self):
        result = _check_safety(
            signal_result={"overall_agreement": 0.90},
            forward_result={"new": {"hit_rate": 0.30}},
            shadow_result={
                "entropy_shift": 0.05,
                "regime_stability": {"low_vol": 0.8, "high_vol": 0.8},
            },
            mas_result={},
        )
        assert not result["met"]
        assert any("agreement" in f for f in result["failures"])

    def test_entropy_shift_fails(self):
        result = _check_safety(
            signal_result={"overall_agreement": 0.96},
            forward_result={"new": {"hit_rate": 0.30}},
            shadow_result={
                "entropy_shift": 0.2,
                "regime_stability": {"low_vol": 0.8, "high_vol": 0.8},
            },
            mas_result={},
        )
        assert not result["met"]
        assert any("entropy" in f for f in result["failures"])

    def test_regime_stability_fails(self):
        result = _check_safety(
            signal_result={"overall_agreement": 0.96},
            forward_result={"new": {"hit_rate": 0.30}},
            shadow_result={
                "entropy_shift": 0.05,
                "regime_stability": {"low_vol": 0.6, "high_vol": 0.6},
            },
            mas_result={},
        )
        assert not result["met"]
        assert any("regime stability" in f for f in result["failures"])

    def test_empty_regime_stability(self):
        result = _check_safety(
            signal_result={"overall_agreement": 0.96},
            forward_result={"new": {"hit_rate": 0.30}},
            shadow_result={
                "entropy_shift": 0.05,
                "regime_stability": {},
            },
            mas_result={},
        )
        assert not result["met"]

    def test_hit_rate_fails(self):
        result = _check_safety(
            signal_result={"overall_agreement": 0.96},
            forward_result={"new": {"hit_rate": 0.10}},
            shadow_result={
                "entropy_shift": 0.05,
                "regime_stability": {"low_vol": 0.8, "high_vol": 0.8},
            },
            mas_result={},
        )
        assert not result["met"]
        assert any("hit rate" in f for f in result["failures"])


class TestEvaluatePromotion:
    def test_live_candidate(self, tmp_path):
        result = evaluate_promotion(
            asset="TEST",
            mas_result={"mas": 90.0, "sub_scores": {"stress": 0.75}},
            forward_result={
                "baseline": {"sharpe": 1.0, "max_drawdown": 0.1, "hit_rate": 0.35},
                "new": {"sharpe": 1.2, "max_drawdown": 0.08, "hit_rate": 0.40},
            },
            model_result={},
            signal_result={"overall_agreement": 0.96, "flip_rate": 0.05},
            portfolio_result={},
            shadow_result={
                "entropy_shift": 0.05,
                "signal_agreement": 0.96,
                "regime_stability": {"low_vol": 0.8, "high_vol": 0.8},
                "mean_confidence_old": {"short": 0.6, "long": 0.6},
                "mean_confidence_new": {"short": 0.6, "long": 0.6},
            },
            trajectory=[{"mas": 80.0}, {"mas": 85.0}, {"mas": 90.0}],
            drift_score=0.3,
        )
        assert result["decision"] in ("LIVE_CANDIDATE", "PAPER_TRADING_ONLY")
        assert result["confidence"] > 0

    def test_mas_low_forces_reject(self):
        result = evaluate_promotion(
            asset="TEST",
            mas_result={"mas": 60.0, "sub_scores": {"stress": 0.75}},
            forward_result={
                "baseline": {"sharpe": 1.0, "max_drawdown": 0.1, "hit_rate": 0.35},
                "new": {"sharpe": 1.2, "max_drawdown": 0.08, "hit_rate": 0.40},
            },
            model_result={},
            signal_result={"overall_agreement": 0.96},
            portfolio_result={},
            shadow_result={
                "entropy_shift": 0.05,
                "signal_agreement": 0.96,
                "regime_stability": {"low_vol": 0.8, "high_vol": 0.8},
                "mean_confidence_old": {"short": 0.6, "long": 0.6},
                "mean_confidence_new": {"short": 0.6, "long": 0.6},
            },
            trajectory=[{"mas": 65.0}, {"mas": 62.0}, {"mas": 60.0}],
        )
        assert result["decision"] == "REJECT"

    def test_failure_modes_blocks_action(self):
        result = evaluate_promotion(
            asset="TEST",
            mas_result={"mas": 70.0, "sub_scores": {"stress": 0.4}},
            forward_result={"error": "failed"},
            model_result={},
            signal_result={"overall_agreement": 0.90},
            portfolio_result={},
            shadow_result={
                "entropy_shift": 0.05,
                "signal_agreement": 0.90,
                "regime_stability": {"low_vol": 0.8, "high_vol": 0.8},
                "mean_confidence_old": {"short": 0.6, "long": 0.6},
                "mean_confidence_new": {"short": 0.6, "long": 0.6},
            },
            trajectory=[],
        )
        assert "recommended_action" in result
        assert result["recommended_action"].startswith("blocked_by_")

    def test_writes_to_file(self, tmp_path):
        import backtests.model_promotion_engine as mpe

        orig_base = os.path.dirname(os.path.dirname(os.path.abspath(mpe.__file__)))
        evaluate_promotion(
            asset="test_promotion_asset",
            mas_result={"mas": 88.0, "sub_scores": {"stress": 0.75}},
            forward_result={
                "baseline": {"sharpe": 1.0, "max_drawdown": 0.1, "hit_rate": 0.35},
                "new": {"sharpe": 1.2, "max_drawdown": 0.08, "hit_rate": 0.40},
            },
            model_result={},
            signal_result={"overall_agreement": 0.96},
            portfolio_result={},
            shadow_result={
                "entropy_shift": 0.05,
                "signal_agreement": 0.96,
                "regime_stability": {"low_vol": 0.8, "high_vol": 0.8},
                "mean_confidence_old": {"short": 0.6, "long": 0.6},
                "mean_confidence_new": {"short": 0.6, "long": 0.6},
            },
            trajectory=[{"mas": 80.0}, {"mas": 85.0}, {"mas": 88.0}],
        )
        # check that file was written to sandbox directory
        fpath = os.path.join(orig_base, "data", "sandbox", "test_promotion_asset_promotion.json")
        try:
            assert os.path.exists(fpath)
        finally:
            if os.path.exists(fpath):
                os.remove(fpath)
