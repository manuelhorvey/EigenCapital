"""Phase 1Q Tests — Independent Alpha Research Campaign.

Tests:
- Research campaign governance (no hypothesis mutation)
- Hypothesis registration and trial tracking
- Alpha admission scorecard evaluation
- Incremental alpha testing
- Research map generation
- Adversarial scenarios
"""

import pytest

from eigencapital.research.alpha.campaign import (
    ResearchCampaign,
    ResearchCampaignRunner,
    HypothesisIdentity,
    HypothesisTrial,
    HypothesisVerdict,
    HypothesisStatus,
    CampaignPhase,
)
from eigencapital.research.alpha.scorecard import (
    ScorecardEvaluator,
)
from eigencapital.research.alpha.incremental import (
    IncrementalAlphaTester,
    PortfolioBaseline,
)
from eigencapital.research.alpha.research_map import (
    ResearchMapGenerator,
)


# ============================================================
# Hypothesis Identity Tests
# ============================================================


class TestHypothesisIdentity:
    """Test hypothesis identity immutability."""

    def _make_hypothesis(self, **overrides):
        defaults = {
            "hypothesis_id": "HYP-TREND-001",
            "family": "trend",
            "title": "Time-Series Momentum",
            "claim": "12-1m momentum persists net of costs",
            "economic_rationale": "Information diffuses gradually",
            "expected_mechanism": "Positive serial correlation",
            "universe": "Liquid equities",
            "required_data": ("daily_ohlcv",),
            "candidate_features": ("ts_ret_12m_1m",),
            "candidate_parameters": {"lookback": [126, 189, 252]},
            "falsification_criteria": "Reject if Sharpe < 0.3",
            "expected_failure_modes": "Regime flip",
            "transaction_cost_sensitivity": "Moderate",
            "capacity_considerations": "High capacity",
            "source": "ml4t-extraction.md",
        }
        defaults.update(overrides)
        return HypothesisIdentity(**defaults)

    def test_fingerprint_deterministic(self):
        """Same hypothesis produces same fingerprint."""
        h = self._make_hypothesis()
        fp1 = h.compute_fingerprint()
        fp2 = h.compute_fingerprint()
        assert fp1 == fp2

    def test_different_hypotheses_different_fingerprints(self):
        """Different hypotheses produce different fingerprints."""
        h1 = self._make_hypothesis(hypothesis_id="HYP-A")
        h2 = self._make_hypothesis(hypothesis_id="HYP-B")
        assert h1.compute_fingerprint() != h2.compute_fingerprint()

    def test_fingerprint_ignores_status(self):
        """Fingerprint does not include status — identity is immutable."""
        h1 = self._make_hypothesis(status=HypothesisStatus.UNVALIDATED.value)
        h2 = self._make_hypothesis(status=HypothesisStatus.REGISTERED.value)
        assert h1.compute_fingerprint() == h2.compute_fingerprint()


# ============================================================
# Research Campaign Runner Tests
# ============================================================


class TestResearchCampaignRunner:
    """Test research campaign governance and lifecycle."""

    def _make_campaign(self):
        return ResearchCampaign(
            campaign_id="1Q-campaign",
            production_fingerprint="fp-abc",
        )

    def _make_hypothesis(self, **overrides):
        defaults = {
            "hypothesis_id": "HYP-TREND-001",
            "family": "trend",
            "title": "Time-Series Momentum",
            "claim": "12-1m momentum persists",
            "economic_rationale": "Gradual diffusion",
            "expected_mechanism": "Serial correlation",
            "universe": "Liquid equities",
            "required_data": ("daily_ohlcv",),
            "candidate_features": ("ret_12_1",),
            "candidate_parameters": {"lookback": [126, 252]},
            "falsification_criteria": "Sharpe < 0.3",
            "expected_failure_modes": "Regime flip",
            "transaction_cost_sensitivity": "Moderate",
            "capacity_considerations": "High",
            "source": "ml4t",
        }
        defaults.update(overrides)
        return HypothesisIdentity(**defaults)

    def test_create_campaign(self):
        """Campaign creation works."""
        runner = ResearchCampaignRunner()
        campaign = self._make_campaign()
        created = runner.create_campaign(campaign)
        assert created.campaign_id == "1Q-campaign"

    def test_valid_phase_transition(self):
        """Valid phase transition works."""
        runner = ResearchCampaignRunner()
        runner.create_campaign(self._make_campaign())
        assert runner.transition_phase(
            "1Q-campaign", CampaignPhase.CALIBRATION.value, "t1"
        )
        campaign = runner.get_campaign("1Q-campaign")
        assert campaign.current_phase == CampaignPhase.CALIBRATION.value

    def test_invalid_phase_transition_blocked(self):
        """Invalid phase transition is blocked."""
        runner = ResearchCampaignRunner()
        runner.create_campaign(self._make_campaign())
        assert not runner.transition_phase(
            "1Q-campaign", CampaignPhase.COMPLETED.value, "t1"
        )

    def test_register_hypothesis(self):
        """Hypothesis registration works."""
        runner = ResearchCampaignRunner()
        h = self._make_hypothesis()
        registered = runner.register_hypothesis(h)
        assert registered.status == HypothesisStatus.REGISTERED.value
        assert registered.hypothesis_id == "HYP-TREND-001"

    def test_hypothesis_immutable_after_registration(self):
        """Registered hypothesis cannot be modified through the runner."""
        runner = ResearchCampaignRunner()
        runner.register_hypothesis(self._make_hypothesis())
        assert runner.cannot_modify_hypothesis("HYP-TREND-001")

    def test_record_trial(self):
        """Trial recording works."""
        runner = ResearchCampaignRunner()
        runner.register_hypothesis(self._make_hypothesis())
        trial = HypothesisTrial(
            trial_id="trial-1",
            hypothesis_id="HYP-TREND-001",
            trial_group_id="group-1",
            trial_index=0,
            parameter_config={"lookback": 252},
            dataset_version="v1",
            universe="liquid",
            feature_versions={},
            strategy_config_hash="sc-h",
            cost_model_hash="cm-h",
            provenance_hash="prov-h",
            result_status="REJECTED",
        )
        runner.record_trial(trial)
        trials = runner.get_trials("HYP-TREND-001")
        assert len(trials) == 1

    def test_record_verdict(self):
        """Verdict recording works."""
        runner = ResearchCampaignRunner()
        runner.register_hypothesis(self._make_hypothesis())
        verdict = HypothesisVerdict(
            hypothesis_id="HYP-TREND-001",
            family="trend",
            status=HypothesisStatus.REJECTED.value,
            total_trials=9,
            best_sharpe=0.2,
        )
        runner.record_verdict(verdict)
        v = runner.get_verdict("HYP-TREND-001")
        assert v is not None
        assert v.status == HypothesisStatus.REJECTED.value

    def test_verdict_updates_hypothesis_status(self):
        """Verdict updates hypothesis status."""
        runner = ResearchCampaignRunner()
        runner.register_hypothesis(self._make_hypothesis())
        verdict = HypothesisVerdict(
            hypothesis_id="HYP-TREND-001",
            family="trend",
            status=HypothesisStatus.SUPPORTED.value,
            total_trials=9,
        )
        runner.record_verdict(verdict)
        h = runner.get_hypothesis("HYP-TREND-001")
        assert h.status == HypothesisStatus.SUPPORTED.value

    def test_rejected_count(self):
        """Rejected count is tracked."""
        runner = ResearchCampaignRunner()
        runner.register_hypothesis(self._make_hypothesis(hypothesis_id="HYP-A"))
        runner.register_hypothesis(self._make_hypothesis(hypothesis_id="HYP-B"))
        runner.record_verdict(
            HypothesisVerdict(
                hypothesis_id="HYP-A",
                family="trend",
                status=HypothesisStatus.REJECTED.value,
                total_trials=1,
            )
        )
        runner.record_verdict(
            HypothesisVerdict(
                hypothesis_id="HYP-B",
                family="trend",
                status=HypothesisStatus.SUPPORTED.value,
                total_trials=1,
            )
        )
        assert runner.get_rejected_count() == 1
        assert runner.get_supported_count() == 1

    def test_full_campaign_lifecycle(self):
        """Full campaign lifecycle PLANNED → CALIBRATION → ... → COMPLETED."""
        runner = ResearchCampaignRunner()
        runner.create_campaign(self._make_campaign())
        phases = [
            CampaignPhase.CALIBRATION.value,
            CampaignPhase.SIMPLE_FACTORS.value,
            CampaignPhase.TREND_MOMENTUM.value,
            CampaignPhase.MEAN_REVERSION.value,
            CampaignPhase.STAT_ARB.value,
            CampaignPhase.VOLATILITY.value,
            CampaignPhase.ALT_DATA.value,
            CampaignPhase.ML_GATE.value,
            CampaignPhase.COMPLETED.value,
        ]
        for i, phase in enumerate(phases):
            assert runner.transition_phase("1Q-campaign", phase, f"t{i}")
        campaign = runner.get_campaign("1Q-campaign")
        assert campaign.current_phase == CampaignPhase.COMPLETED.value
        assert len(campaign.phase_history) == 9


# ============================================================
# Alpha Admission Scorecard Tests
# ============================================================


class TestAlphaAdmissionScorecard:
    """Test alpha admission scorecard evaluation."""

    def test_strong_candidate_admitted(self):
        """Strong candidate with good metrics is admitted."""
        evaluator = ScorecardEvaluator()
        metrics = {
            "net_sharpe": 0.8,
            "t_stat": 3.0,
            "pbo": 0.05,
            "has_economic_rationale": True,
            "has_expected_mechanism": True,
            "walk_forward_passed": True,
            "parameter_stability": True,
            "regime_stability": True,
            "universe_perturbation_passed": True,
            "cost_survived": True,
            "turnover": 0.3,
            "spread_survived": True,
            "capacity_adequate": True,
            "adv_participation": 0.01,
            "incremental_value": True,
            "incremental_sharpe_delta": 0.15,
            "incremental_dd_delta": -0.02,
            "correlation_with_existing": 0.4,
            "downside_correlation": 0.3,
            "crisis_behavior_ok": True,
            "concentration": 0.15,
            "breadth_ok": True,
        }
        scorecard = evaluator.evaluate("HYP-TREND-001", "trend", metrics)
        assert scorecard.admitted is True
        assert scorecard.verdict in ("PRODUCTION_CANDIDATE", "PORTFOLIO_USEFUL")

    def test_weak_candidate_rejected(self):
        """Weak candidate with poor metrics is rejected."""
        evaluator = ScorecardEvaluator()
        metrics = {
            "net_sharpe": 0.1,
            "t_stat": 0.5,
            "pbo": 0.8,
            "has_economic_rationale": False,
            "has_expected_mechanism": False,
            "walk_forward_passed": False,
            "parameter_stability": False,
            "regime_stability": False,
            "universe_perturbation_passed": False,
            "cost_survived": False,
            "turnover": 2.0,
            "spread_survived": False,
            "capacity_adequate": False,
            "adv_participation": 0.1,
            "incremental_value": False,
            "incremental_sharpe_delta": -0.1,
            "incremental_dd_delta": 0.1,
            "correlation_with_existing": 0.95,
            "downside_correlation": 0.9,
            "crisis_behavior_ok": False,
            "concentration": 0.8,
            "breadth_ok": False,
        }
        scorecard = evaluator.evaluate("HYP-MR-001", "mean_reversion", metrics)
        assert scorecard.admitted is False
        assert scorecard.verdict == "REJECTED"

    def test_scorecard_fingerprint_deterministic(self):
        """Scorecard fingerprint is deterministic."""
        evaluator = ScorecardEvaluator()
        metrics = {
            "net_sharpe": 0.5,
            "t_stat": 2.0,
            "cost_survived": True,
            "walk_forward_passed": True,
            "parameter_stability": True,
            "has_economic_rationale": True,
            "incremental_value": True,
            "incremental_sharpe_delta": 0.05,
            "correlation_with_existing": 0.3,
        }
        sc = evaluator.evaluate("HYP-X", "trend", metrics)
        fp1 = sc.compute_fingerprint()
        fp2 = sc.compute_fingerprint()
        assert fp1 == fp2

    def test_all_nine_dimensions_evaluated(self):
        """All 9 scorecard dimensions are evaluated."""
        evaluator = ScorecardEvaluator()
        metrics = {
            "net_sharpe": 0.5,
            "t_stat": 2.0,
            "pbo": 0.1,
            "has_economic_rationale": True,
            "has_expected_mechanism": True,
            "walk_forward_passed": True,
            "parameter_stability": True,
            "regime_stability": True,
            "universe_perturbation_passed": True,
            "cost_survived": True,
            "turnover": 0.3,
            "spread_survived": True,
            "capacity_adequate": True,
            "adv_participation": 0.01,
            "incremental_value": True,
            "incremental_sharpe_delta": 0.05,
            "incremental_dd_delta": -0.01,
            "correlation_with_existing": 0.4,
            "downside_correlation": 0.3,
            "crisis_behavior_ok": True,
            "concentration": 0.15,
            "breadth_ok": True,
        }
        sc = evaluator.evaluate("HYP-X", "trend", metrics)
        assert len(sc.dimension_scores) == 9

    def test_scorecards_tracked(self):
        """Scorecards are tracked in evaluator history."""
        evaluator = ScorecardEvaluator()
        metrics = {
            "net_sharpe": 0.5,
            "t_stat": 2.0,
            "cost_survived": True,
            "walk_forward_passed": True,
            "parameter_stability": True,
            "has_economic_rationale": True,
            "incremental_value": True,
            "incremental_sharpe_delta": 0.05,
            "correlation_with_existing": 0.3,
        }
        evaluator.evaluate("HYP-A", "trend", metrics)
        evaluator.evaluate("HYP-B", "momentum", metrics)
        assert len(evaluator.get_scorecards()) == 2
        assert evaluator.get_latest() is not None


# ============================================================
# Incremental Alpha Testing Tests
# ============================================================


class TestIncrementalAlphaTesting:
    """Test incremental alpha testing framework."""

    def _make_baseline(self):
        return PortfolioBaseline(
            portfolio_id="current",
            sharpe=0.65,
            sortino=1.2,
            max_drawdown=-0.15,
            cagr=0.08,
            volatility=0.12,
            turnover=0.3,
            tail_risk=0.05,
            constituents=("HYP-TREND-001", "HYP-MOM-001"),
        )

    def test_good_candidate_recommended_add(self):
        """Good diversifying candidate is recommended ADD."""
        tester = IncrementalAlphaTester()
        tester.set_baseline(self._make_baseline())
        result = tester.evaluate(
            hypothesis_id="HYP-VOL-001",
            candidate_sharpe=0.5,
            candidate_drawdown=-0.10,
            candidate_turnover=0.2,
            correlation_with_existing=0.3,
            portfolio_with_candidate={
                "sharpe": 0.72,
                "sortino": 1.35,
                "max_drawdown": -0.13,
                "turnover": 0.35,
                "tail_risk": 0.04,
            },
        )
        assert result.recommendation == "ADD"
        assert result.incremental_value is True
        assert result.diversification_value is True

    def test_correlated_candidate_rejected(self):
        """Highly correlated candidate with no improvement is rejected."""
        tester = IncrementalAlphaTester()
        tester.set_baseline(self._make_baseline())
        result = tester.evaluate(
            hypothesis_id="HYP-MOM-002",
            candidate_sharpe=0.7,
            candidate_drawdown=-0.12,
            candidate_turnover=0.4,
            correlation_with_existing=0.95,
            portfolio_with_candidate={
                "sharpe": 0.66,
                "sortino": 1.22,
                "max_drawdown": -0.14,
                "turnover": 0.38,
                "tail_risk": 0.05,
            },
        )
        assert result.recommendation == "REJECT"

    def test_diversifying_but_mild_improvement_conditional(self):
        """Diversifying candidate with mild improvement is CONDITIONAL."""
        tester = IncrementalAlphaTester()
        tester.set_baseline(self._make_baseline())
        result = tester.evaluate(
            hypothesis_id="HYP-SA-001",
            candidate_sharpe=0.4,
            candidate_drawdown=-0.08,
            candidate_turnover=0.5,
            correlation_with_existing=0.2,
            portfolio_with_candidate={
                "sharpe": 0.66,
                "sortino": 1.21,
                "max_drawdown": -0.14,
                "turnover": 0.36,
                "tail_risk": 0.048,
            },
        )
        # Mild improvement, low correlation
        assert result.recommendation in ("ADD", "CONDITIONAL")

    def test_result_fingerprint_deterministic(self):
        """IncrementalTestResult fingerprint is deterministic."""
        tester = IncrementalAlphaTester()
        tester.set_baseline(self._make_baseline())
        result = tester.evaluate(
            hypothesis_id="HYP-X",
            candidate_sharpe=0.5,
            candidate_drawdown=-0.10,
            candidate_turnover=0.3,
            correlation_with_existing=0.4,
            portfolio_with_candidate={
                "sharpe": 0.7,
                "sortino": 1.3,
                "max_drawdown": -0.12,
                "turnover": 0.35,
                "tail_risk": 0.04,
            },
        )
        fp1 = result.compute_fingerprint()
        fp2 = result.compute_fingerprint()
        assert fp1 == fp2

    def test_get_additions_and_rejections(self):
        """Additions and rejections are correctly filtered."""
        tester = IncrementalAlphaTester()
        tester.set_baseline(self._make_baseline())
        tester.evaluate(
            "HYP-A",
            0.5,
            -0.10,
            0.2,
            0.3,
            {
                "sharpe": 0.72,
                "sortino": 1.35,
                "max_drawdown": -0.13,
                "turnover": 0.35,
                "tail_risk": 0.04,
            },
        )
        tester.evaluate(
            "HYP-B",
            0.7,
            -0.12,
            0.4,
            0.95,
            {
                "sharpe": 0.64,
                "sortino": 1.18,
                "max_drawdown": -0.16,
                "turnover": 0.4,
                "tail_risk": 0.055,
            },
        )
        additions = tester.get_additions()
        rejections = tester.get_rejections()
        assert len(additions) + len(rejections) == 2


# ============================================================
# Research Map Generator Tests
# ============================================================


class TestResearchMapGenerator:
    """Test research map generation."""

    def _make_verdict(self, **overrides):
        defaults = {
            "hypothesis_id": "HYP-TREND-001",
            "family": "trend",
            "status": HypothesisStatus.REJECTED.value,
            "total_trials": 9,
            "best_sharpe": 0.2,
            "net_sharpe": 0.15,
            "turnover": 0.5,
            "max_drawdown": -0.25,
            "falsification_passed": False,
            "cost_survived": False,
            "incremental_value": False,
        }
        defaults.update(overrides)
        return HypothesisVerdict(**defaults)

    def test_generate_map(self):
        """Research map generation works."""
        generator = ResearchMapGenerator()
        verdicts = [
            self._make_verdict(
                hypothesis_id="HYP-TREND-001",
                family="trend",
                status=HypothesisStatus.REJECTED.value,
            ),
            self._make_verdict(
                hypothesis_id="HYP-MOM-001",
                family="momentum",
                status=HypothesisStatus.SUPPORTED.value,
                net_sharpe=0.6,
            ),
            self._make_verdict(
                hypothesis_id="HYP-MR-001",
                family="mean_reversion",
                status=HypothesisStatus.REJECTED.value,
            ),
        ]
        research_map = generator.generate(
            "1Q-campaign", verdicts, [], [], timestamp="2026-06-01"
        )
        assert research_map.total_hypotheses == 3
        assert research_map.total_rejected == 2
        assert research_map.total_supported == 1

    def test_survival_rate(self):
        """Survival rate is correctly computed."""
        generator = ResearchMapGenerator()
        verdicts = [
            self._make_verdict(
                hypothesis_id="HYP-A", status=HypothesisStatus.REJECTED.value
            ),
            self._make_verdict(
                hypothesis_id="HYP-B", status=HypothesisStatus.SUPPORTED.value
            ),
            self._make_verdict(
                hypothesis_id="HYP-C", status=HypothesisStatus.REJECTED.value
            ),
        ]
        research_map = generator.generate("camp", verdicts, [], [])
        assert research_map.overall_survival_rate == pytest.approx(1 / 3, abs=0.01)

    def test_family_summaries(self):
        """Family summaries are generated for all expected families."""
        generator = ResearchMapGenerator()
        verdicts = [
            self._make_verdict(
                hypothesis_id="HYP-T1",
                family="trend",
                status=HypothesisStatus.SUPPORTED.value,
                net_sharpe=0.7,
            ),
            self._make_verdict(
                hypothesis_id="HYP-T2",
                family="trend",
                status=HypothesisStatus.REJECTED.value,
            ),
            self._make_verdict(
                hypothesis_id="HYP-M1",
                family="momentum",
                status=HypothesisStatus.PORTFOLIO_USEFUL.value,
                net_sharpe=0.5,
            ),
        ]
        research_map = generator.generate("camp", verdicts, [], [])
        # All 10 expected families should be represented
        families = {fs.family for fs in research_map.family_summaries}
        assert "trend" in families
        assert "momentum" in families
        # Trend family: 1 supported, 1 rejected
        trend = next(fs for fs in research_map.family_summaries if fs.family == "trend")
        assert trend.executed == 2
        assert trend.rejected == 1
        assert trend.supported == 1

    def test_to_markdown(self):
        """Markdown report generation works."""
        generator = ResearchMapGenerator()
        verdicts = [
            self._make_verdict(
                hypothesis_id="HYP-A", status=HypothesisStatus.REJECTED.value
            ),
            self._make_verdict(
                hypothesis_id="HYP-B",
                family="momentum",
                status=HypothesisStatus.SUPPORTED.value,
                net_sharpe=0.6,
            ),
        ]
        research_map = generator.generate("camp", verdicts, [], [])
        md = research_map.to_markdown()
        assert "# Alpha Research Map" in md
        assert "HYP-A" in md
        assert "HYP-B" in md

    def test_map_fingerprint_deterministic(self):
        """Research map fingerprint is deterministic."""
        generator = ResearchMapGenerator()
        verdicts = [
            self._make_verdict(
                hypothesis_id="HYP-A", status=HypothesisStatus.REJECTED.value
            )
        ]
        rm1 = generator.generate("camp", verdicts, [], [])
        rm2 = generator.generate("camp", verdicts, [], [])
        assert rm1.compute_fingerprint() == rm2.compute_fingerprint()


# ============================================================
# Adversarial / Integration Tests
# ============================================================


class TestPhase1QAdversarial:
    """Adversarial tests for Phase 1Q."""

    def test_no_hypothesis_modification_after_registration(self):
        """Registered hypothesis cannot be modified."""
        runner = ResearchCampaignRunner()
        h = HypothesisIdentity(
            hypothesis_id="HYP-X",
            family="trend",
            title="Original",
            claim="Original claim",
            economic_rationale="Rationale",
            expected_mechanism="Mechanism",
            universe="Universe",
            required_data=("d1",),
            candidate_features=("f1",),
            candidate_parameters={"p": [1, 2]},
            falsification_criteria="Criteria",
            expected_failure_modes="Modes",
            transaction_cost_sensitivity="Moderate",
            capacity_considerations="High",
            source="src",
        )
        registered = runner.register_hypothesis(h)
        # Hypothesis is now frozen
        assert runner.cannot_modify_hypothesis("HYP-X")
        assert registered.hypothesis_id == "HYP-X"

    def test_rejected_hypothesis_is_successful_research(self):
        """Rejection is a valid and successful outcome."""
        runner = ResearchCampaignRunner()
        runner.register_hypothesis(
            HypothesisIdentity(
                hypothesis_id="HYP-MR-001",
                family="mean_reversion",
                title="Short-term reversal",
                claim="Reversal persists",
                economic_rationale="Liquidity premium",
                expected_mechanism="Spread",
                universe="Equities",
                required_data=("d1",),
                candidate_features=("f1",),
                candidate_parameters={},
                falsification_criteria="Sharpe < 0.3",
                expected_failure_modes="Costs",
                transaction_cost_sensitivity="High",
                capacity_considerations="Low",
                source="ml4t",
            )
        )
        runner.record_verdict(
            HypothesisVerdict(
                hypothesis_id="HYP-MR-001",
                family="mean_reversion",
                status=HypothesisStatus.REJECTED.value,
                total_trials=12,
                notes="Gross alpha exists but dies after realistic costs",
            )
        )
        v = runner.get_verdict("HYP-MR-001")
        assert v.status == HypothesisStatus.REJECTED.value
        # This is a successful research outcome
        assert runner.get_rejected_count() == 1

    def test_scorecard_safety_overrides_sharpe(self):
        """Good Sharpe does not override safety failures."""
        evaluator = ScorecardEvaluator()
        metrics = {
            "net_sharpe": 1.5,  # Very high Sharpe
            "t_stat": 5.0,
            "pbo": 0.01,
            "has_economic_rationale": True,
            "has_expected_mechanism": True,
            "walk_forward_passed": False,  # But walk-forward failed
            "parameter_stability": False,  # And parameters not stable
            "regime_stability": False,
            "universe_perturbation_passed": False,
            "cost_survived": False,  # And costs kill it
            "turnover": 3.0,
            "spread_survived": False,
            "capacity_adequate": True,
            "adv_participation": 0.01,
            "incremental_value": True,
            "incremental_sharpe_delta": 0.3,
            "incremental_dd_delta": -0.01,
            "correlation_with_existing": 0.2,
            "downside_correlation": 0.1,
            "crisis_behavior_ok": True,
            "concentration": 0.1,
            "breadth_ok": True,
        }
        sc = evaluator.evaluate("HYP-HIGH-SHARPE", "trend", metrics)
        # Despite high Sharpe, robustness and cost failures → FRAGILE (stats pass but robustness/cost fail)
        assert sc.verdict in ("REJECTED", "FRAGILE")
        assert sc.admitted is False

    def test_incremental_high_sharpe_low_diversification_rejected(self):
        """High standalone Sharpe but no diversification → not added."""
        tester = IncrementalAlphaTester()
        tester.set_baseline(
            PortfolioBaseline(
                portfolio_id="current",
                sharpe=0.65,
                sortino=1.2,
                max_drawdown=-0.15,
                cagr=0.08,
                volatility=0.12,
                turnover=0.3,
                tail_risk=0.05,
                constituents=("HYP-A",),
            )
        )
        result = tester.evaluate(
            hypothesis_id="HYP-HIGH-CORR",
            candidate_sharpe=0.9,
            candidate_drawdown=-0.08,
            candidate_turnover=0.2,
            correlation_with_existing=0.95,  # Very high correlation
            portfolio_with_candidate={
                "sharpe": 0.66,  # Tiny improvement
                "sortino": 1.21,
                "max_drawdown": -0.145,
                "turnover": 0.35,
                "tail_risk": 0.048,
            },
        )
        assert result.recommendation == "REJECT"

    def test_campaign_cannot_skip_phases(self):
        """Campaign cannot skip phases."""
        runner = ResearchCampaignRunner()
        runner.create_campaign(
            ResearchCampaign(campaign_id="c1", production_fingerprint="fp")
        )
        # Cannot skip to COMPLETED directly
        assert not runner.transition_phase("c1", CampaignPhase.COMPLETED.value, "t1")

    def test_trial_count_recorded(self):
        """Trial count is tracked per hypothesis."""
        runner = ResearchCampaignRunner()
        runner.register_hypothesis(
            HypothesisIdentity(
                hypothesis_id="HYP-TREND-001",
                family="trend",
                title="Trend",
                claim="Claim",
                economic_rationale="Rationale",
                expected_mechanism="Mech",
                universe="Universe",
                required_data=("d1",),
                candidate_features=("f1",),
                candidate_parameters={"lb": [126, 252]},
                falsification_criteria="Sharpe < 0.3",
                expected_failure_modes="Failures",
                transaction_cost_sensitivity="Moderate",
                capacity_considerations="High",
                source="src",
            )
        )
        for i in range(9):
            runner.record_trial(
                HypothesisTrial(
                    trial_id=f"trial-{i}",
                    hypothesis_id="HYP-TREND-001",
                    trial_group_id="group-1",
                    trial_index=i,
                    parameter_config={"lookback": 126 + i * 14},
                    dataset_version="v1",
                    universe="liquid",
                    feature_versions={},
                    strategy_config_hash="sc",
                    cost_model_hash="cm",
                    provenance_hash="prov",
                    result_status="REJECTED",
                )
            )
        trials = runner.get_trials("HYP-TREND-001")
        assert len(trials) == 9

    def test_research_map_includes_rejected(self):
        """Research map includes rejected hypotheses (successful falsification)."""
        generator = ResearchMapGenerator()
        verdicts = [
            HypothesisVerdict(
                hypothesis_id="HYP-A",
                family="trend",
                status=HypothesisStatus.REJECTED.value,
                total_trials=12,
                notes="Falsified",
            ),
        ]
        rm = generator.generate("camp", verdicts, [], [])
        assert rm.total_rejected == 1
        md = rm.to_markdown()
        assert "HYP-A" in md

    def test_ml_hypothesis_last_in_campaign(self):
        """ML gate is the last phase before completion."""
        runner = ResearchCampaignRunner()
        runner.create_campaign(
            ResearchCampaign(campaign_id="c1", production_fingerprint="fp")
        )
        runner.transition_phase("c1", CampaignPhase.CALIBRATION.value, "t0")
        runner.transition_phase("c1", CampaignPhase.SIMPLE_FACTORS.value, "t1")
        runner.transition_phase("c1", CampaignPhase.TREND_MOMENTUM.value, "t2")
        runner.transition_phase("c1", CampaignPhase.MEAN_REVERSION.value, "t3")
        runner.transition_phase("c1", CampaignPhase.STAT_ARB.value, "t4")
        runner.transition_phase("c1", CampaignPhase.VOLATILITY.value, "t5")
        runner.transition_phase("c1", CampaignPhase.ALT_DATA.value, "t6")
        runner.transition_phase("c1", CampaignPhase.ML_GATE.value, "t7")
        campaign = runner.get_campaign("c1")
        assert campaign.current_phase == CampaignPhase.ML_GATE.value
        # Can only go to COMPLETED or FAILED from ML_GATE
        assert runner.transition_phase("c1", CampaignPhase.COMPLETED.value, "t8")
        campaign = runner.get_campaign("c1")
        assert campaign.current_phase == CampaignPhase.COMPLETED.value

    def test_multiple_families_independent_evaluation(self):
        """Different families are evaluated independently."""
        evaluator = ScorecardEvaluator()
        # Strong trend
        sc1 = evaluator.evaluate(
            "HYP-T1",
            "trend",
            {
                "net_sharpe": 0.8,
                "t_stat": 3.0,
                "pbo": 0.05,
                "has_economic_rationale": True,
                "has_expected_mechanism": True,
                "walk_forward_passed": True,
                "parameter_stability": True,
                "regime_stability": True,
                "universe_perturbation_passed": True,
                "cost_survived": True,
                "turnover": 0.3,
                "spread_survived": True,
                "capacity_adequate": True,
                "adv_participation": 0.01,
                "incremental_value": True,
                "incremental_sharpe_delta": 0.1,
                "incremental_dd_delta": -0.02,
                "correlation_with_existing": 0.3,
                "downside_correlation": 0.2,
                "crisis_behavior_ok": True,
                "concentration": 0.1,
                "breadth_ok": True,
            },
        )
        # Weak mean reversion
        sc2 = evaluator.evaluate(
            "HYP-MR1",
            "mean_reversion",
            {
                "net_sharpe": 0.1,
                "t_stat": 0.5,
                "pbo": 0.8,
                "has_economic_rationale": False,
                "has_expected_mechanism": False,
                "walk_forward_passed": False,
                "parameter_stability": False,
                "regime_stability": False,
                "universe_perturbation_passed": False,
                "cost_survived": False,
                "turnover": 2.0,
                "spread_survived": False,
                "capacity_adequate": False,
                "adv_participation": 0.1,
                "incremental_value": False,
                "incremental_sharpe_delta": -0.1,
                "incremental_dd_delta": 0.1,
                "correlation_with_existing": 0.95,
                "downside_correlation": 0.9,
                "crisis_behavior_ok": False,
                "concentration": 0.8,
                "breadth_ok": False,
            },
        )
        assert sc1.admitted is True
        assert sc2.admitted is False
        assert sc1.family == "trend"
        assert sc2.family == "mean_reversion"
