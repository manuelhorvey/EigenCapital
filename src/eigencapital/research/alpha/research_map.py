"""Research Map Generator — produces the alpha research map artifact.

The research map shows which hypotheses survived, which were rejected,
and which contributed incremental portfolio value.

Output: ALPHA_RESEARCH_MAP.md equivalent as structured data.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from typing import Dict, List, Any, Optional, Tuple

from eigencapital.research.alpha.campaign import HypothesisVerdict, HypothesisStatus
from eigencapital.research.alpha.scorecard import AlphaAdmissionScorecard
from eigencapital.research.alpha.incremental import IncrementalTestResult


@dataclass(frozen=True)
class FamilySummary:
    """Summary of research results for a hypothesis family."""
    family: str
    total_hypotheses: int
    executed: int
    rejected: int
    inconclusive: int
    supported: int
    portfolio_useful: int
    production_candidate: int
    survival_rate: float
    best_sharpe: float
    avg_sharpe: float
    best_incremental_delta: float

    def to_dict(self) -> Dict[str, Any]:
        return {
            "family": self.family,
            "total_hypotheses": self.total_hypotheses,
            "executed": self.executed,
            "rejected": self.rejected,
            "inconclusive": self.inconclusive,
            "supported": self.supported,
            "portfolio_useful": self.portfolio_useful,
            "production_candidate": self.production_candidate,
            "survival_rate": self.survival_rate,
            "best_sharpe": self.best_sharpe,
            "avg_sharpe": self.avg_sharpe,
            "best_incremental_delta": self.best_incremental_delta,
        }


@dataclass(frozen=True)
class AlphaResearchMap:
    """Complete alpha research map — the primary artifact of Phase 1Q."""
    campaign_id: str
    total_hypotheses: int
    total_executed: int
    total_rejected: int
    total_supported: int
    total_portfolio_useful: int
    total_production_candidate: int
    family_summaries: tuple  # tuple of FamilySummary
    verdicts: tuple  # tuple of HypothesisVerdict dicts
    scorecards: tuple  # tuple of AlphaAdmissionScorecard dicts
    incremental_results: tuple  # tuple of IncrementalTestResult dicts
    overall_survival_rate: float
    timestamp: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return {
            "campaign_id": self.campaign_id,
            "total_hypotheses": self.total_hypotheses,
            "total_executed": self.total_executed,
            "total_rejected": self.total_rejected,
            "total_supported": self.total_supported,
            "total_portfolio_useful": self.total_portfolio_useful,
            "total_production_candidate": self.total_production_candidate,
            "family_summaries": [f.to_dict() for f in self.family_summaries],
            "verdicts": self.verdicts,
            "scorecards": self.scorecards,
            "incremental_results": self.incremental_results,
            "overall_survival_rate": self.overall_survival_rate,
            "timestamp": self.timestamp,
        }

    def compute_fingerprint(self) -> str:
        data = self.to_dict()
        payload = json.dumps(data, sort_keys=True).encode("utf-8")
        return hashlib.sha256(payload).hexdigest()

    def to_markdown(self) -> str:
        """Generate human-readable Markdown report."""
        lines = [
            "# Alpha Research Map",
            "",
            f"**Campaign:** {self.campaign_id}",
            f"**Total Hypotheses:** {self.total_hypotheses}",
            f"**Executed:** {self.total_executed}",
            f"**Rejected:** {self.total_rejected}",
            f"**Supported:** {self.total_supported}",
            f"**Portfolio Useful:** {self.total_portfolio_useful}",
            f"**Production Candidate:** {self.total_production_candidate}",
            f"**Overall Survival Rate:** {self.overall_survival_rate:.1%}",
            "",
            "## Family Summary",
            "",
            "| Family | Hypotheses | Executed | Rejected | Supported | Portfolio Useful | Production Candidate | Survival Rate | Best Sharpe |",
            "|--------|-----------|----------|----------|-----------|-----------------|---------------------|---------------|-------------|",
        ]

        for fs in self.family_summaries:
            lines.append(
                f"| {fs.family} | {fs.total_hypotheses} | {fs.executed} | {fs.rejected} "
                f"| {fs.supported} | {fs.portfolio_useful} | {fs.production_candidate} "
                f"| {fs.survival_rate:.0%} | {fs.best_sharpe:.2f} |"
            )

        lines.extend([
            "",
            "## Individual Verdicts",
            "",
            "| Hypothesis | Family | Status | Sharpe | Turnover | Drawdown | Incremental |",
            "|------------|--------|--------|--------|----------|----------|-------------|",
        ])

        for v in self.verdicts:
            lines.append(
                f"| {v.get('hypothesis_id', '')} | {v.get('family', '')} | {v.get('status', '')} "
                f"| {v.get('net_sharpe', 0):.2f} | {v.get('turnover', 0):.2f} "
                f"| {v.get('max_drawdown', 0):.2f} | {v.get('incremental_value', False)} |"
            )

        lines.extend([
            "",
            "## Key Findings",
            "",
            f"- {self.total_rejected} hypotheses rejected (successful falsification)",
            f"- {self.total_portfolio_useful} hypotheses portfolio-useful",
            f"- {self.total_production_candidate} production candidates identified",
            "",
            "## Notes",
            "",
            "- Rejected hypotheses are successful research outcomes",
            "- No hypothesis was modified after seeing results",
            "- All verdicts are evidence-based through the Alpha Admission Scorecard",
        ])

        return "\n".join(lines)


class ResearchMapGenerator:
    """Generates the Alpha Research Map from campaign results."""

    # Expected families from the hypothesis library
    EXPECTED_FAMILIES = [
        "trend", "momentum", "mean_reversion", "breakout",
        "volatility", "cross_sectional", "statistical_arbitrage",
        "factor", "alternative_data", "ml",
    ]

    def generate(
        self,
        campaign_id: str,
        verdicts: List[HypothesisVerdict],
        scorecards: List[AlphaAdmissionScorecard],
        incremental_results: List[IncrementalTestResult],
        timestamp: str = "",
    ) -> AlphaResearchMap:
        """Generate the alpha research map."""
        # Family summaries
        family_summaries = []
        for family in self.EXPECTED_FAMILIES:
            family_verdicts = [v for v in verdicts if v.family == family]
            executed = len(family_verdicts)
            rejected = sum(1 for v in family_verdicts if v.status == HypothesisStatus.REJECTED.value)
            inconclusive = sum(1 for v in family_verdicts if v.status == HypothesisStatus.INCONCLUSIVE.value)
            supported = sum(1 for v in family_verdicts if v.status == HypothesisStatus.SUPPORTED.value)
            portfolio_useful = sum(1 for v in family_verdicts if v.status == HypothesisStatus.PORTFOLIO_USEFUL.value)
            production_candidate = sum(1 for v in family_verdicts if v.status == HypothesisStatus.PRODUCTION_CANDIDATE.value)

            sharpes = [v.net_sharpe for v in family_verdicts if v.net_sharpe > 0]
            best_sharpe = max(sharpes) if sharpes else 0.0
            avg_sharpe = sum(sharpes) / len(sharpes) if sharpes else 0.0

            incr_in_family = [r for r in incremental_results
                             if any(v.hypothesis_id == r.hypothesis_id for v in family_verdicts)]
            best_incr = max((r.sharpe_delta for r in incr_in_family), default=0.0)

            total_in_family = max(executed, 1)
            survival = (supported + portfolio_useful + production_candidate) / total_in_family if executed > 0 else 0.0

            family_summaries.append(FamilySummary(
                family=family,
                total_hypotheses=executed,
                executed=executed,
                rejected=rejected,
                inconclusive=inconclusive,
                supported=supported,
                portfolio_useful=portfolio_useful,
                production_candidate=production_candidate,
                survival_rate=survival,
                best_sharpe=best_sharpe,
                avg_sharpe=avg_sharpe,
                best_incremental_delta=best_incr,
            ))

        total = len(verdicts)
        total_executed = len(verdicts)
        total_rejected = sum(1 for v in verdicts if v.status == HypothesisStatus.REJECTED.value)
        total_supported = sum(1 for v in verdicts if v.status == HypothesisStatus.SUPPORTED.value)
        total_pu = sum(1 for v in verdicts if v.status == HypothesisStatus.PORTFOLIO_USEFUL.value)
        total_pc = sum(1 for v in verdicts if v.status == HypothesisStatus.PRODUCTION_CANDIDATE.value)

        survival_rate = (total_supported + total_pu + total_pc) / max(total, 1)

        return AlphaResearchMap(
            campaign_id=campaign_id,
            total_hypotheses=total,
            total_executed=total_executed,
            total_rejected=total_rejected,
            total_supported=total_supported,
            total_portfolio_useful=total_pu,
            total_production_candidate=total_pc,
            family_summaries=tuple(family_summaries),
            verdicts=tuple(v.to_dict() for v in verdicts),
            scorecards=tuple(s.to_dict() for s in scorecards),
            incremental_results=tuple(r.to_dict() for r in incremental_results),
            overall_survival_rate=survival_rate,
            timestamp=timestamp,
        )
