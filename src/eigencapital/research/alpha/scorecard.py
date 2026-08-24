"""Alpha Admission Scorecard — structured evaluation framework.

Prevents EigenCapital from becoming a Sharpe-maximization machine.

Evaluation dimensions:
1. Statistical evidence
2. Economic rationale
3. Robustness
4. Cost survival
5. Capacity
6. Incremental portfolio value
7. Diversification

Final decision integrates all dimensions, not just Sharpe.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from typing import Dict, List, Any, Optional, Tuple


# Scorecard evaluation dimensions — using plain strings for clarity
STATISTICAL_EVIDENCE = "statistical_evidence"
ECONOMIC_RATIONALE = "economic_rationale"
ROBUSTNESS = "robustness"
COST_SURVIVAL = "cost_survival"
CAPACITY = "capacity"
INCREMENTAL_VALUE = "incremental_value"
DIVERSIFICATION = "diversification"
REGIME_STABILITY = "regime_stability"
BREADTH = "breadth"


@dataclass(frozen=True)
class DimensionScore:
    """Score for a single evaluation dimension."""
    dimension: str
    score: float  # 0.0 to 1.0
    passed: bool
    details: str = ""
    evidence: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return {
            "dimension": self.dimension,
            "score": self.score,
            "passed": self.passed,
            "details": self.details,
            "evidence": self.evidence,
        }


@dataclass(frozen=True)
class AlphaAdmissionScorecard:
    """Structured evaluation of a hypothesis candidate.

    Integrates statistical, economic, robustness, cost, capacity,
    incremental, and diversification evidence.
    """
    hypothesis_id: str
    family: str
    dimension_scores: tuple  # tuple of DimensionScore
    overall_score: float  # weighted average
    admitted: bool
    verdict: str  # REJECTED, INCONCLUSIVE, SUPPORTED, PORTFOLIO_USEFUL, PRODUCTION_CANDIDATE
    restrictions: tuple = ()
    notes: str = ""
    evaluation_timestamp: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return {
            "hypothesis_id": self.hypothesis_id,
            "family": self.family,
            "dimension_scores": [d.to_dict() for d in self.dimension_scores],
            "overall_score": self.overall_score,
            "admitted": self.admitted,
            "verdict": self.verdict,
            "restrictions": list(self.restrictions),
            "notes": self.notes,
            "evaluation_timestamp": self.evaluation_timestamp,
        }

    def compute_fingerprint(self) -> str:
        data = self.to_dict()
        payload = json.dumps(data, sort_keys=True).encode("utf-8")
        return hashlib.sha256(payload).hexdigest()


class ScorecardEvaluator:
    """Evaluates hypotheses through the Alpha Admission Scorecard."""

    # Default dimension weights
    DEFAULT_WEIGHTS = {
        STATISTICAL_EVIDENCE: 0.25,
        ECONOMIC_RATIONALE: 0.10,
        ROBUSTNESS: 0.20,
        COST_SURVIVAL: 0.15,
        CAPACITY: 0.05,
        INCREMENTAL_VALUE: 0.15,
        DIVERSIFICATION: 0.05,
        REGIME_STABILITY: 0.03,
        BREADTH: 0.02,
    }

    def __init__(self, weights: Optional[Dict[str, float]] = None) -> None:
        self._weights = weights or self.DEFAULT_WEIGHTS
        self._scorecards: List[AlphaAdmissionScorecard] = []

    def evaluate(
        self,
        hypothesis_id: str,
        family: str,
        metrics: Dict[str, Any],
        timestamp: str = "",
    ) -> AlphaAdmissionScorecard:
        """Evaluate a hypothesis candidate through the scorecard.

        Args:
            hypothesis_id: hypothesis identifier
            family: hypothesis family
            metrics: evaluation metrics with keys for each dimension
            timestamp: evaluation timestamp

        Returns:
            AlphaAdmissionScorecard with verdict
        """
        dimension_scores = []

        # 1. Statistical evidence
        stat_score = self._evaluate_statistical(metrics)
        dimension_scores.append(stat_score)

        # 2. Economic rationale
        econ_score = self._evaluate_economic(metrics)
        dimension_scores.append(econ_score)

        # 3. Robustness
        robust_score = self._evaluate_robustness(metrics)
        dimension_scores.append(robust_score)

        # 4. Cost survival
        cost_score = self._evaluate_cost(metrics)
        dimension_scores.append(cost_score)

        # 5. Capacity
        capacity_score = self._evaluate_capacity(metrics)
        dimension_scores.append(capacity_score)

        # 6. Incremental value
        incr_score = self._evaluate_incremental(metrics)
        dimension_scores.append(incr_score)

        # 7. Diversification
        div_score = self._evaluate_diversification(metrics)
        dimension_scores.append(div_score)

        # 8. Regime stability
        regime_score = self._evaluate_regime(metrics)
        dimension_scores.append(regime_score)

        # 9. Breadth
        breadth_score = self._evaluate_breadth(metrics)
        dimension_scores.append(breadth_score)

        # Compute weighted overall score
        overall = sum(
            ds.score * self._weights.get(ds.dimension, 0.0)
            for ds in dimension_scores
        )

        # Determine verdict
        passed_dims = [ds for ds in dimension_scores if ds.passed]
        failed_critical = [ds for ds in dimension_scores
                          if not ds.passed and ds.dimension in (
                              STATISTICAL_EVIDENCE, COST_SURVIVAL, ROBUSTNESS)]

        restrictions = []
        if not any(ds.dimension == COST_SURVIVAL and ds.passed for ds in dimension_scores):
            restrictions.append("Cost survival not demonstrated")
        if not any(ds.dimension == INCREMENTAL_VALUE and ds.passed for ds in dimension_scores):
            restrictions.append("Incremental portfolio value not demonstrated")

        if failed_critical:
            verdict = "REJECTED"
            admitted = False
        elif len(passed_dims) < 5:
            verdict = "INCONCLUSIVE"
            admitted = False
        elif overall >= 0.7 and incr_score.passed:
            verdict = "PRODUCTION_CANDIDATE"
            admitted = True
        elif overall >= 0.5 and cost_score.passed:
            verdict = "PORTFOLIO_USEFUL"
            admitted = True
        elif overall >= 0.3:
            verdict = "SUPPORTED"
            admitted = True
        else:
            verdict = "REJECTED"
            admitted = False

        notes_parts = []
        if not econ_score.passed:
            notes_parts.append("Weak economic rationale")
        if not regime_score.passed:
            notes_parts.append("Regime instability")
        if not breadth_score.passed:
            notes_parts.append("Insufficient breadth")

        scorecard = AlphaAdmissionScorecard(
            hypothesis_id=hypothesis_id,
            family=family,
            dimension_scores=tuple(dimension_scores),
            overall_score=overall,
            admitted=admitted,
            verdict=verdict,
            restrictions=tuple(restrictions),
            notes="; ".join(notes_parts) if notes_parts else "All dimensions evaluated",
            evaluation_timestamp=timestamp,
        )
        self._scorecards.append(scorecard)
        return scorecard

    def _evaluate_statistical(self, metrics: Dict[str, Any]) -> DimensionScore:
        sharpe = metrics.get("net_sharpe", 0.0)
        t_stat = metrics.get("t_stat", 0.0)
        pbo = metrics.get("pbo", 1.0)

        score = 0.0
        if sharpe > 0.5:
            score += 0.4
        elif sharpe > 0.3:
            score += 0.2
        if t_stat > 2.0:
            score += 0.3
        elif t_stat > 1.5:
            score += 0.15
        if pbo < 0.1:
            score += 0.3
        elif pbo < 0.3:
            score += 0.15

        passed = sharpe > 0.3 and t_stat > 1.5
        return DimensionScore(
            dimension=STATISTICAL_EVIDENCE,
            score=min(score, 1.0),
            passed=passed,
            details=f"sharpe={sharpe:.2f}, t_stat={t_stat:.2f}, pbo={pbo:.2f}",
        )

    def _evaluate_economic(self, metrics: Dict[str, Any]) -> DimensionScore:
        has_rationale = metrics.get("has_economic_rationale", False)
        has_mechanism = metrics.get("has_expected_mechanism", False)
        score = (0.5 if has_rationale else 0.0) + (0.5 if has_mechanism else 0.0)
        return DimensionScore(
            dimension=ECONOMIC_RATIONALE,
            score=score,
            passed=has_rationale,
            details=f"rationale={has_rationale}, mechanism={has_mechanism}",
        )

    def _evaluate_robustness(self, metrics: Dict[str, Any]) -> DimensionScore:
        walk_forward = metrics.get("walk_forward_passed", False)
        parameter_stable = metrics.get("parameter_stability", False)
        regime_stable = metrics.get("regime_stability", False)
        universe_perturbation = metrics.get("universe_perturbation_passed", False)

        score = sum([walk_forward, parameter_stable, regime_stable, universe_perturbation]) / 4.0
        passed = walk_forward and parameter_stable
        return DimensionScore(
            dimension=ROBUSTNESS,
            score=score,
            passed=passed,
            details=f"wf={walk_forward}, param={parameter_stable}, regime={regime_stable}, univ={universe_perturbation}",
        )

    def _evaluate_cost(self, metrics: Dict[str, Any]) -> DimensionScore:
        cost_survived = metrics.get("cost_survived", False)
        turnover = metrics.get("turnover", 1.0)
        spread_survived = metrics.get("spread_survived", False)

        score = 0.0
        if cost_survived:
            score += 0.5
        if turnover < 0.5:
            score += 0.25
        elif turnover < 1.0:
            score += 0.15
        if spread_survived:
            score += 0.25

        passed = cost_survived
        return DimensionScore(
            dimension=COST_SURVIVAL,
            score=min(score, 1.0),
            passed=passed,
            details=f"cost_survived={cost_survived}, turnover={turnover:.2f}, spread={spread_survived}",
        )

    def _evaluate_capacity(self, metrics: Dict[str, Any]) -> DimensionScore:
        capacity_ok = metrics.get("capacity_adequate", True)
        adv_participation = metrics.get("adv_participation", 0.01)
        score = 1.0 if capacity_ok and adv_participation < 0.05 else 0.5
        return DimensionScore(
            dimension=CAPACITY,
            score=score,
            passed=capacity_ok,
            details=f"capacity={capacity_ok}, adv_participation={adv_participation:.4f}",
        )

    def _evaluate_incremental(self, metrics: Dict[str, Any]) -> DimensionScore:
        incremental = metrics.get("incremental_value", False)
        sharpe_delta = metrics.get("incremental_sharpe_delta", 0.0)
        dd_delta = metrics.get("incremental_dd_delta", 0.0)
        correlation = metrics.get("correlation_with_existing", 1.0)

        score = 0.0
        if incremental:
            score += 0.4
        if sharpe_delta > 0:
            score += 0.3
        if dd_delta < 0:  # negative DD delta means lower drawdown (good)
            score += 0.2
        if correlation < 0.7:
            score += 0.1

        passed = incremental and sharpe_delta > 0
        return DimensionScore(
            dimension=INCREMENTAL_VALUE,
            score=min(score, 1.0),
            passed=passed,
            details=f"incremental={incremental}, sharpe_delta={sharpe_delta:.3f}, dd_delta={dd_delta:.3f}, corr={correlation:.2f}",
        )

    def _evaluate_diversification(self, metrics: Dict[str, Any]) -> DimensionScore:
        correlation = metrics.get("correlation_with_existing", 1.0)
        downside_corr = metrics.get("downside_correlation", 1.0)

        score = 0.0
        if correlation < 0.3:
            score += 0.5
        elif correlation < 0.6:
            score += 0.3
        elif correlation < 0.8:
            score += 0.1
        if downside_corr < 0.3:
            score += 0.5
        elif downside_corr < 0.6:
            score += 0.3

        passed = correlation < 0.7
        return DimensionScore(
            dimension=DIVERSIFICATION,
            score=min(score, 1.0),
            passed=passed,
            details=f"correlation={correlation:.2f}, downside_corr={downside_corr:.2f}",
        )

    def _evaluate_regime(self, metrics: Dict[str, Any]) -> DimensionScore:
        regime_stable = metrics.get("regime_stability", False)
        crisis_behavior = metrics.get("crisis_behavior_ok", True)
        score = (0.6 if regime_stable else 0.0) + (0.4 if crisis_behavior else 0.0)
        return DimensionScore(
            dimension=REGIME_STABILITY,
            score=min(score, 1.0),
            passed=regime_stable,
            details=f"regime={regime_stable}, crisis={crisis_behavior}",
        )

    def _evaluate_breadth(self, metrics: Dict[str, Any]) -> DimensionScore:
        concentration = metrics.get("concentration", 0.0)
        breadth_ok = metrics.get("breadth_ok", True)

        score = 0.0
        if concentration < 0.2:
            score += 0.6
        elif concentration < 0.5:
            score += 0.3
        if breadth_ok:
            score += 0.4

        return DimensionScore(
            dimension=BREADTH,
            score=min(score, 1.0),
            passed=breadth_ok and concentration < 0.5,
            details=f"concentration={concentration:.2f}, breadth={breadth_ok}",
        )

    def get_scorecards(self) -> List[AlphaAdmissionScorecard]:
        return list(self._scorecards)

    def get_latest(self) -> Optional[AlphaAdmissionScorecard]:
        return self._scorecards[-1] if self._scorecards else None
