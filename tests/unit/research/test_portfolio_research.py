"""Adversarial tests for Phase 1J Portfolio Research, Allocation & Evidence.

Tests cover:
- AllocationExperiment creation and serialization
- PortfolioEvidenceGate evaluation
- PortfolioResearchEngine orchestration
- Eligibility gate enforcement
- 1/N vs risk-scaled comparison
- Evidence gate verdict logic
- Edge cases: single candidate, empty streams
"""

import math
import random
import pytest

from eigencapital.research.portfolio.allocation import (
    AllocationExperiment,
    AllocationMethod,
    AllocationStatus,
)
from eigencapital.research.portfolio.evidence import (
    PortfolioEvidenceGate,
    PortfolioVerdict,
    EvidenceCheck,
    EvidenceCheckResult,
)
from eigencapital.research.portfolio.engine import (
    PortfolioResearchEngine,
    PortfolioResearchConfig,
)
from eigencapital.research.combination.candidate import AlphaCandidate, EligibilityStatus
from eigencapital.research.combination.returns import ReturnStream


# ───────────────────────────────────────────────
#  Helpers
# ───────────────────────────────────────────────

def _make_streams(n: int = 3, length: int = 200, seed: int = 42):
    """Create n return streams with controlled correlation."""
    rng = random.Random(seed)
    streams = []
    for i in range(n):
        returns = [rng.gauss(0.0005, 0.01) for _ in range(length)]
        timestamps = [f"2025-01-{15 + j:02d}T10:00:00Z" for j in range(length)]
        streams.append(ReturnStream(
            stream_id=f"RS-{i}",
            candidate_id=f"AC-{i}",
            returns=tuple(returns),
            timestamps=tuple(timestamps),
        ))
    return streams


def _make_candidates(n: int = 3, eligible: bool = True):
    """Create n alpha candidates."""
    status = EligibilityStatus.ELIGIBLE if eligible else EligibilityStatus.EXCLUDED
    verdict = "CANDIDATE" if eligible else "REJECTED"
    return [
        AlphaCandidate(
            candidate_id=f"AC-{i}",
            hypothesis_id=f"HYP-{i}",
            execution_record_id=f"EXEC-{i}",
            evidence_verdict=verdict,
            eligibility_status=status,
            eligibility_reason=f"{'Eligible' if eligible else 'Excluded'}",
        )
        for i in range(n)
    ]


# ═══════════════════════════════════════════════
#  ALLOCATION EXPERIMENT
# ═══════════════════════════════════════════════

class TestAllocationExperiment:
    def test_basic_creation(self):
        exp = AllocationExperiment(
            experiment_id="PAE-001",
            hypothesis_id="HYP-PORTFOLIO-001",
            constituents=("AC-0", "AC-1", "AC-2"),
            allocation_method=AllocationMethod.EQUAL_WEIGHT,
        )
        assert exp.experiment_id == "PAE-001"
        assert exp.status == AllocationStatus.REGISTERED

    def test_missing_experiment_id(self):
        with pytest.raises(ValueError, match="experiment_id"):
            AllocationExperiment(
                experiment_id="",
                hypothesis_id="HYP-001",
                constituents=("AC-0",),
                allocation_method=AllocationMethod.EQUAL_WEIGHT,
            )

    def test_empty_constituents(self):
        with pytest.raises(ValueError, match="constituents"):
            AllocationExperiment(
                experiment_id="PAE-001",
                hypothesis_id="HYP-001",
                constituents=(),
                allocation_method=AllocationMethod.EQUAL_WEIGHT,
            )

    def test_invalid_trial_index(self):
        with pytest.raises(ValueError, match="trial_index"):
            AllocationExperiment(
                experiment_id="PAE-001",
                hypothesis_id="HYP-001",
                constituents=("AC-0",),
                allocation_method=AllocationMethod.EQUAL_WEIGHT,
                trial_index=0,
            )

    def test_deterministic_serialization(self):
        exp = AllocationExperiment(
            experiment_id="PAE-001",
            hypothesis_id="HYP-001",
            constituents=("AC-0", "AC-1"),
            allocation_method=AllocationMethod.RISK_SCALD,
            parameters={"lookback": 63},
        )
        d1 = exp.to_dict()
        d2 = exp.to_dict()
        assert d1 == d2

    def test_provenance_deterministic(self):
        exp = AllocationExperiment(
            experiment_id="PAE-001",
            hypothesis_id="HYP-001",
            constituents=("AC-0",),
            allocation_method=AllocationMethod.EQUAL_WEIGHT,
        )
        h1 = exp.compute_provenance_hash()
        h2 = exp.compute_provenance_hash()
        assert h1 == h2
        assert len(h1) == 64

    def test_serialization_roundtrip(self):
        exp = AllocationExperiment(
            experiment_id="PAE-001",
            hypothesis_id="HYP-001",
            constituents=("AC-0", "AC-1"),
            allocation_method=AllocationMethod.HRP,
            status=AllocationStatus.COMPLETED,
        )
        d = exp.to_dict()
        exp2 = AllocationExperiment.from_dict(d)
        assert exp2.experiment_id == "PAE-001"
        assert exp2.allocation_method == AllocationMethod.HRP


# ═══════════════════════════════════════════════
#  PORTFOLIO EVIDENCE GATE
# ═══════════════════════════════════════════════

class TestPortfolioEvidenceGate:
    def test_all_pass_candidate(self):
        metrics = {
            "sharpe": 1.0,
            "net_sharpe": 0.8,
            "max_drawdown": 0.15,
            "annual_turnover": 5.0,
            "concentration_hhi": 0.25,
            "n_constituents": 4,
        }
        baseline = {"sharpe": 0.6}
        gate = PortfolioEvidenceGate.evaluate("PE-001", metrics, baseline)
        assert gate.verdict == PortfolioVerdict.CANDIDATE

    def test_cost_failure_rejected(self):
        metrics = {
            "sharpe": 1.0,
            "net_sharpe": -0.1,  # Negative after costs
            "max_drawdown": 0.15,
            "annual_turnover": 5.0,
            "concentration_hhi": 0.25,
            "n_constituents": 4,
        }
        gate = PortfolioEvidenceGate.evaluate("PE-001", metrics)
        assert gate.verdict == PortfolioVerdict.REJECTED

    def test_high_drawdown_inconclusive(self):
        metrics = {
            "sharpe": 1.0,
            "net_sharpe": 0.8,
            "max_drawdown": 0.30,  # > 25%
            "annual_turnover": 5.0,
            "concentration_hhi": 0.25,
            "n_constituents": 4,
        }
        gate = PortfolioEvidenceGate.evaluate("PE-001", metrics)
        assert gate.verdict == PortfolioVerdict.INCONCLUSIVE

    def test_no_baseline_passes(self):
        metrics = {
            "sharpe": 0.5,
            "net_sharpe": 0.3,
            "max_drawdown": 0.10,
            "annual_turnover": 3.0,
            "concentration_hhi": 0.25,
            "n_constituents": 4,
        }
        gate = PortfolioEvidenceGate.evaluate("PE-001", metrics)
        # No baseline → diversification check passes, but Sharpe < 0.5 → INCONCLUSIVE
        assert gate.verdict == PortfolioVerdict.INCONCLUSIVE

    def test_serialization(self):
        metrics = {"sharpe": 1.0, "net_sharpe": 0.8, "max_drawdown": 0.15}
        gate = PortfolioEvidenceGate.evaluate("PE-001", metrics)
        d = gate.to_dict()
        assert d["experiment_id"] == "PE-001"
        assert len(d["checks"]) > 0

    def test_checks_have_results(self):
        metrics = {"sharpe": 1.0, "net_sharpe": 0.8, "max_drawdown": 0.15}
        gate = PortfolioEvidenceGate.evaluate("PE-001", metrics)
        for check in gate.checks:
            assert isinstance(check, EvidenceCheckResult)
            assert check.check in EvidenceCheck


# ═══════════════════════════════════════════════
#  PORTFOLIO RESEARCH ENGINE
# ═══════════════════════════════════════════════

class TestPortfolioResearchEngine:
    def test_research_multiple_candidates(self):
        candidates = _make_candidates(3, eligible=True)
        streams = _make_streams(3, length=200)
        engine = PortfolioResearchEngine()

        result = engine.research(candidates, streams)

        assert result["candidates"] == 3
        assert "equal_weight" in result["methods"]
        assert "risk_scaled" in result["methods"]
        assert result["best_method"] is not None

    def test_research_insufficient_candidates(self):
        candidates = _make_candidates(1, eligible=True)
        streams = _make_streams(1, length=200)
        engine = PortfolioResearchEngine()

        result = engine.research(candidates, streams)

        assert result["status"] == "insufficient_candidates"

    def test_research_no_eligible(self):
        candidates = _make_candidates(3, eligible=False)
        streams = _make_streams(3, length=200)
        engine = PortfolioResearchEngine()

        result = engine.research(candidates, streams)

        # All excluded → no eligible candidates
        assert result.get("status") == "insufficient_candidates" or result.get("candidates", 0) == 0

    def test_research_empty(self):
        engine = PortfolioResearchEngine()
        result = engine.research([], [])
        assert result["status"] == "no_eligible_candidates"

    def test_equal_weight_metrics(self):
        candidates = _make_candidates(3, eligible=True)
        streams = _make_streams(3, length=200)
        engine = PortfolioResearchEngine()

        result = engine.research(candidates, streams)

        ew = result["methods"]["equal_weight"]
        assert ew["method"] == "equal_weight"
        assert "metrics" in ew
        assert "sharpe" in ew["metrics"]
        assert ew["metrics"]["n_constituents"] == 3

    def test_risk_scaled_metrics(self):
        candidates = _make_candidates(3, eligible=True)
        streams = _make_streams(3, length=200)
        engine = PortfolioResearchEngine()

        result = engine.research(candidates, streams)

        rs = result["methods"]["risk_scaled"]
        assert rs["method"] == "risk_scaled"
        assert "metrics" in rs

    def test_evidence_gate_on_best(self):
        candidates = _make_candidates(3, eligible=True)
        streams = _make_streams(3, length=200)
        engine = PortfolioResearchEngine()

        result = engine.research(candidates, streams)

        assert "evidence" in result
        assert "verdict" in result["evidence"]

    def test_diversification_lower_vol(self):
        """Portfolio vol should be lower than average individual vol."""
        candidates = _make_candidates(3, eligible=True)
        streams = _make_streams(3, length=200, seed=42)
        engine = PortfolioResearchEngine()

        result = engine.research(candidates, streams)

        ew = result["methods"]["equal_weight"]
        portfolio_vol = ew["metrics"]["volatility"]
        avg_vol = sum(s.volatility for s in streams) / len(streams)
        assert portfolio_vol < avg_vol

    def test_research_deterministic(self):
        candidates = _make_candidates(3, eligible=True)
        streams = _make_streams(3, length=200)

        r1 = PortfolioResearchEngine().research(candidates, streams)
        r2 = PortfolioResearchEngine().research(candidates, streams)

        assert r1["methods"]["equal_weight"]["metrics"]["sharpe"] == \
               r2["methods"]["equal_weight"]["metrics"]["sharpe"]
