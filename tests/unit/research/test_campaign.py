"""Tests for Phase 1I-F Controlled Alpha Campaign.

Tests cover:
- CampaignRunner execution
- CampaignManifest creation
- CampaignResult comparison
- Reproducibility testing
- Trial group assignment
- Ledger integration
- Edge cases: missing hypotheses, failed executions
"""

import pytest

from eigencapital.research.campaigns.runner import (
    CampaignRunner,
    CampaignManifest,
    CampaignResult,
)
from eigencapital.research.execution.engine import ExecutionEngine, ExecutionConfig
from eigencapital.research.execution.record import ExecutionRecord, ExecutionStatus
from eigencapital.research.execution.ledger import ExecutionLedger
from eigencapital.research.hypotheses.hypothesis import Hypothesis
from eigencapital.research.experiments.registry import ExperimentRegistry
from eigencapital.research.costs.model import MODERATE_COST
from eigencapital.features.pipeline import FeaturePipeline
from eigencapital.features.feature_set import FeatureSet, FeatureEntry, FeatureStatus


# ───────────────────────────────────────────────
#  Helpers
# ───────────────────────────────────────────────

def _make_hypothesis(hyp_id: str, family: str = "trend") -> Hypothesis:
    return Hypothesis(
        hypothesis_id=hyp_id,
        claim=f"Test claim for {hyp_id}",
        economic_rationale="Test rationale",
        falsification_criteria="Sharpe < 0.5",
        status="REGISTERED",
    )


def _mock_features(bars, config):
    entry = FeatureEntry("roc_20", "v1", FeatureStatus.COMPUTED, value=0.05)
    return FeatureSet(
        instrument_id="ES",
        decision_timestamp="2025-06-30T10:00:00Z",
        timestamp_utc="2025-06-30T10:00:00Z",
        entries={"roc_20": entry},
    ).with_provenance()


def _mock_backtest(featureset, config):
    return {"sharpe": 1.2, "total_return": 0.15, "max_drawdown": 0.08}


def _mock_validate(result, config):
    return {"verdict": "CANDIDATE", "sharpe": result.get("sharpe", 0)}


# ═══════════════════════════════════════════════
#  CAMPAIGN MANIFEST
# ═══════════════════════════════════════════════

class TestCampaignManifest:
    def test_basic_creation(self):
        manifest = CampaignManifest(
            campaign_id="CAMP-001",
            hypotheses=["HYP-TREND-001", "HYP-MOM-001"],
        )
        assert manifest.campaign_id == "CAMP-001"
        assert len(manifest.hypotheses) == 2

    def test_serialization(self):
        manifest = CampaignManifest(
            campaign_id="CAMP-001",
            hypotheses=["HYP-TREND-001"],
            description="Test campaign",
        )
        d = manifest.to_dict()
        assert d["campaign_id"] == "CAMP-001"
        assert d["hypotheses"] == ["HYP-TREND-001"]


# ═══════════════════════════════════════════════
#  CAMPAIGN RUNNER
# ═══════════════════════════════════════════════

class TestCampaignRunner:
    def test_run_single_hypothesis(self):
        registry = ExperimentRegistry()
        pipeline = FeaturePipeline()
        engine = ExecutionEngine(registry, pipeline)
        ledger = ExecutionLedger()
        runner = CampaignRunner(engine, ledger)

        manifest = CampaignManifest(
            campaign_id="CAMP-001",
            hypotheses=["HYP-TREND-001"],
        )
        hypotheses = {"HYP-TREND-001": _make_hypothesis("HYP-TREND-001")}

        result = runner.run(
            manifest=manifest,
            hypotheses=hypotheses,
            compute_features_fn=_mock_features,
            run_backtest_fn=_mock_backtest,
            validate_fn=_mock_validate,
            cost_model=MODERATE_COST,
        )

        assert result.campaign_id == "CAMP-001"
        assert len(result.executions) == 1
        assert result.verdicts["HYP-TREND-001"] == "CANDIDATE"

    def test_run_multiple_hypotheses(self):
        registry = ExperimentRegistry()
        pipeline = FeaturePipeline()
        engine = ExecutionEngine(registry, pipeline)
        ledger = ExecutionLedger()
        runner = CampaignRunner(engine, ledger)

        manifest = CampaignManifest(
            campaign_id="CAMP-001",
            hypotheses=["HYP-TREND-001", "HYP-MOM-001", "HYP-MR-001"],
        )
        hypotheses = {
            "HYP-TREND-001": _make_hypothesis("HYP-TREND-001"),
            "HYP-MOM-001": _make_hypothesis("HYP-MOM-001"),
            "HYP-MR-001": _make_hypothesis("HYP-MR-001"),
        }

        result = runner.run(
            manifest=manifest,
            hypotheses=hypotheses,
            compute_features_fn=_mock_features,
            run_backtest_fn=_mock_backtest,
            validate_fn=_mock_validate,
            cost_model=MODERATE_COST,
        )

        assert len(result.executions) == 3
        assert len(result.verdicts) == 3

    def test_results_added_to_ledger(self):
        registry = ExperimentRegistry()
        pipeline = FeaturePipeline()
        engine = ExecutionEngine(registry, pipeline)
        ledger = ExecutionLedger()
        runner = CampaignRunner(engine, ledger)

        manifest = CampaignManifest(
            campaign_id="CAMP-001",
            hypotheses=["HYP-TREND-001"],
        )
        hypotheses = {"HYP-TREND-001": _make_hypothesis("HYP-TREND-001")}

        runner.run(
            manifest=manifest,
            hypotheses=hypotheses,
            compute_features_fn=_mock_features,
            run_backtest_fn=_mock_backtest,
            cost_model=MODERATE_COST,
        )

        assert len(ledger) == 1

    def test_comparison_built(self):
        registry = ExperimentRegistry()
        pipeline = FeaturePipeline()
        engine = ExecutionEngine(registry, pipeline)
        ledger = ExecutionLedger()
        runner = CampaignRunner(engine, ledger)

        manifest = CampaignManifest(
            campaign_id="CAMP-001",
            hypotheses=["HYP-TREND-001", "HYP-MOM-001"],
        )
        hypotheses = {
            "HYP-TREND-001": _make_hypothesis("HYP-TREND-001"),
            "HYP-MOM-001": _make_hypothesis("HYP-MOM-001"),
        }

        result = runner.run(
            manifest=manifest,
            hypotheses=hypotheses,
            compute_features_fn=_mock_features,
            run_backtest_fn=_mock_backtest,
            validate_fn=_mock_validate,
            cost_model=MODERATE_COST,
        )

        assert result.comparison["total_executions"] == 2
        assert "CANDIDATE" in result.comparison["by_verdict"]

    def test_reproducibility_tested(self):
        registry = ExperimentRegistry()
        pipeline = FeaturePipeline()
        engine = ExecutionEngine(registry, pipeline)
        ledger = ExecutionLedger()
        runner = CampaignRunner(engine, ledger)

        manifest = CampaignManifest(
            campaign_id="CAMP-001",
            hypotheses=["HYP-TREND-001"],
        )
        hypotheses = {"HYP-TREND-001": _make_hypothesis("HYP-TREND-001")}

        result = runner.run(
            manifest=manifest,
            hypotheses=hypotheses,
            compute_features_fn=_mock_features,
            run_backtest_fn=_mock_backtest,
            validate_fn=_mock_validate,
            cost_model=MODERATE_COST,
        )

        assert result.reproducibility["status"] == "passed"
        assert result.reproducibility["result_match"] is True

    def test_missing_hypothesis_skipped(self):
        registry = ExperimentRegistry()
        pipeline = FeaturePipeline()
        engine = ExecutionEngine(registry, pipeline)
        ledger = ExecutionLedger()
        runner = CampaignRunner(engine, ledger)

        manifest = CampaignManifest(
            campaign_id="CAMP-001",
            hypotheses=["HYP-NONEXISTENT"],
        )
        hypotheses = {}  # Empty — hypothesis not found

        result = runner.run(
            manifest=manifest,
            hypotheses=hypotheses,
            compute_features_fn=_mock_features,
            run_backtest_fn=_mock_backtest,
            cost_model=MODERATE_COST,
        )

        assert len(result.executions) == 0

    def test_campaign_result_serialization(self):
        registry = ExperimentRegistry()
        pipeline = FeaturePipeline()
        engine = ExecutionEngine(registry, pipeline)
        ledger = ExecutionLedger()
        runner = CampaignRunner(engine, ledger)

        manifest = CampaignManifest(
            campaign_id="CAMP-001",
            hypotheses=["HYP-TREND-001"],
        )
        hypotheses = {"HYP-TREND-001": _make_hypothesis("HYP-TREND-001")}

        result = runner.run(
            manifest=manifest,
            hypotheses=hypotheses,
            compute_features_fn=_mock_features,
            run_backtest_fn=_mock_backtest,
            cost_model=MODERATE_COST,
        )

        d = result.to_dict()
        assert d["campaign_id"] == "CAMP-001"
        assert len(d["executions"]) == 1
