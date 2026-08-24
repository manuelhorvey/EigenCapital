"""Fidelity Verdict — pre-registered pass/fail criteria for paper fidelity campaign.

The verdict evaluates whether the paper implementation reproduces the validated
R4 research result. Every criterion is pre-registered before the campaign runs.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from enum import Enum
from typing import Dict, List, Optional, Any

from eigencapital.fidelity.r4_manifest import R4ConfigManifest
from eigencapital.fidelity.parity import ParitySummary


class FidelityGate(str, Enum):
    """Fidelity gates that must pass for paper qualification."""

    RESEARCH_PARITY = "research_parity"
    EXECUTION_ACCOUNTING = "execution_accounting"
    RISK_BEHAVIOR = "risk_behavior"
    RECONCILIATION = "reconciliation"
    OPERATIONAL_STABILITY = "operational_stability"
    COST_SLIPPAGE_ENVELOPE = "cost_slippage_envelope"
    NO_CRITICAL_DIVERGENCE = "no_critical_divergence"


class FidelityVerdict(str, Enum):
    """Final fidelity verdict."""

    BLOCKED = "blocked"
    CONDITIONAL = "conditional"
    PAPER_FIDELITY_PASS = "paper_fidelity_pass"


@dataclass(frozen=True)
class GateResult:
    """Result of a single fidelity gate."""

    gate: FidelityGate
    passed: bool
    reason: str
    details: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "gate": self.gate.value,
            "passed": self.passed,
            "reason": self.reason,
            "details": self.details,
        }


@dataclass(frozen=True)
class FidelityReport:
    """Complete fidelity report for a paper campaign."""

    campaign_id: str
    manifest_identity: str
    verdict: FidelityVerdict
    gate_results: List[GateResult]
    parity_summary: Dict[str, Any]
    total_checks: int
    passed_gates: int
    failed_gates: int
    report_hash: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return {
            "campaign_id": self.campaign_id,
            "manifest_identity": self.manifest_identity,
            "verdict": self.verdict.value,
            "gate_results": [g.to_dict() for g in self.gate_results],
            "parity_summary": self.parity_summary,
            "total_checks": self.total_checks,
            "passed_gates": self.passed_gates,
            "failed_gates": self.failed_gates,
            "report_hash": self.report_hash,
        }

    def to_markdown(self) -> str:
        """Generate human-readable fidelity report."""
        lines = [
            "# R4 Paper Fidelity Report",
            "",
            f"**Campaign:** {self.campaign_id}",
            f"**Manifest:** {self.manifest_identity[:16]}...",
            f"**Verdict:** {self.verdict.value}",
            "",
            "## Gate Results",
            "",
        ]

        for gate in self.gate_results:
            status = "✅" if gate.passed else "❌"
            lines.append(f"- {status} **{gate.gate.value}**: {gate.reason}")

        lines.extend([
            "",
            "## Parity Summary",
            "",
            f"- Total checks: {self.parity_summary.get('total_checks', 0)}",
            f"- Exact matches: {self.parity_summary.get('exact_matches', 0)}",
            f"- Expected differences: {self.parity_summary.get('expected_differences', 0)}",
            f"- Tolerable divergences: {self.parity_summary.get('tolerable_divergences', 0)}",
            f"- Unexplained divergences: {self.parity_summary.get('unexplained_divergences', 0)}",
            f"- Critical divergences: {self.parity_summary.get('critical_divergences', 0)}",
            f"- Match rate: {self.parity_summary.get('match_rate', 0.0):.1%}",
            "",
            "## Summary",
            "",
            f"- Passed gates: {self.passed_gates}/{self.total_checks}",
            f"- Failed gates: {self.failed_gates}/{self.total_checks}",
            f"- Report hash: {self.report_hash[:16]}...",
            "",
        ])

        if self.verdict == FidelityVerdict.PAPER_FIDELITY_PASS:
            lines.append("**The paper implementation reproduces the validated R4 research.**")
        elif self.verdict == FidelityVerdict.BLOCKED:
            lines.append("**CRITICAL: Paper implementation does NOT reproduce research.**")
        else:
            lines.append("**CONDITIONAL: Some gates failed but no critical divergence.**")

        return "\n".join(lines)


class FidelityEvaluator:
    """Evaluates fidelity gates and produces a verdict.

    Every criterion is pre-registered before the campaign runs.
    The verdict is evidence-based, not tunable.
    """

    # Pre-registered thresholds (frozen before campaign)
    MIN_MATCH_RATE: float = 0.95          # 95% exact match required
    MAX_UNEXPLAINED: int = 5              # max 5 unexplained divergences
    MAX_CRITICAL: int = 0                 # zero critical divergences
    MAX_COST_DRAG_BPS: float = 20.0       # max 20bp total cost drag
    MAX_SLIPPAGE_BPS: float = 10.0        # max 10bp slippage
    MAX_RECONCILIATION_FAILURES: int = 0  # zero reconciliation failures
    MIN_RECONCILIATION_RATE: float = 1.0  # 100% reconciliation success

    def __init__(self, manifest: R4ConfigManifest) -> None:
        self._manifest = manifest

    def evaluate(
        self,
        campaign_id: str,
        parity_summary: ParitySummary,
        reconciliation_success_rate: float = 1.0,
        total_cost_drag_bps: float = 0.0,
        max_slippage_bps: float = 0.0,
        operational_events: Optional[Dict[str, int]] = None,
    ) -> FidelityReport:
        """Evaluate all fidelity gates and produce a verdict.

        Args:
            campaign_id: the campaign being evaluated
            parity_summary: aggregate parity statistics
            reconciliation_success_rate: fraction of reconciliation checks that passed
            total_cost_drag_bps: total execution cost drag in basis points
            max_slippage_bps: maximum observed slippage in basis points
            operational_events: operational event counts
        """
        gate_results: List[GateResult] = []

        # Gate 1: Research Parity
        match_rate = parity_summary.match_rate
        research_parity_passed = (
            match_rate >= self.MIN_MATCH_RATE
            and parity_summary.critical_divergences == 0
        )
        gate_results.append(
            GateResult(
                gate=FidelityGate.RESEARCH_PARITY,
                passed=research_parity_passed,
                reason=(
                    f"Match rate {match_rate:.1%} "
                    f"({'PASS' if research_parity_passed else 'FAIL'}, "
                    f"threshold {self.MIN_MATCH_RATE:.0%})"
                ),
                details={"match_rate": match_rate},
            )
        )

        # Gate 2: Execution Accounting
        accounting_passed = (
            total_cost_drag_bps <= self.MAX_COST_DRAG_BPS
            and max_slippage_bps <= self.MAX_SLIPPAGE_BPS
        )
        gate_results.append(
            GateResult(
                gate=FidelityGate.EXECUTION_ACCOUNTING,
                passed=accounting_passed,
                reason=(
                    f"Cost drag {total_cost_drag_bps:.1f}bp, "
                    f"max slippage {max_slippage_bps:.1f}bp "
                    f"({'PASS' if accounting_passed else 'FAIL'})"
                ),
                details={
                    "cost_drag_bps": total_cost_drag_bps,
                    "max_slippage_bps": max_slippage_bps,
                },
            )
        )

        # Gate 3: Risk Behavior
        risk_passed = parity_summary.critical_divergences == 0
        gate_results.append(
            GateResult(
                gate=FidelityGate.RISK_BEHAVIOR,
                passed=risk_passed,
                reason=(
                    f"Critical divergences: {parity_summary.critical_divergences} "
                    f"({'PASS' if risk_passed else 'FAIL'})"
                ),
                details={
                    "critical_divergences": parity_summary.critical_divergences
                },
            )
        )

        # Gate 4: Reconciliation
        reconciliation_passed = (
            reconciliation_success_rate >= self.MIN_RECONCILIATION_RATE
        )
        gate_results.append(
            GateResult(
                gate=FidelityGate.RECONCILIATION,
                passed=reconciliation_passed,
                reason=(
                    f"Reconciliation success rate: {reconciliation_success_rate:.1%} "
                    f"({'PASS' if reconciliation_passed else 'FAIL'})"
                ),
                details={"reconciliation_rate": reconciliation_success_rate},
            )
        )

        # Gate 5: Operational Stability
        ops = operational_events or {}
        missing_bars = ops.get("missing_bar", 0)
        stale_events = ops.get("stale_data", 0)
        ops_passed = missing_bars == 0 and stale_events == 0
        gate_results.append(
            GateResult(
                gate=FidelityGate.OPERATIONAL_STABILITY,
                passed=ops_passed,
                reason=(
                    f"Missing bars: {missing_bars}, stale events: {stale_events} "
                    f"({'PASS' if ops_passed else 'FAIL'})"
                ),
                details={"missing_bars": missing_bars, "stale_events": stale_events},
            )
        )

        # Gate 6: Cost/Slippage Envelope
        cost_envelope_passed = (
            total_cost_drag_bps <= self.MAX_COST_DRAG_BPS
            and max_slippage_bps <= self.MAX_SLIPPAGE_BPS
        )
        gate_results.append(
            GateResult(
                gate=FidelityGate.COST_SLIPPAGE_ENVELOPE,
                passed=cost_envelope_passed,
                reason=(
                    f"Within envelope "
                    f"({'PASS' if cost_envelope_passed else 'FAIL'})"
                ),
                details={
                    "cost_bps": total_cost_drag_bps,
                    "slippage_bps": max_slippage_bps,
                },
            )
        )

        # Gate 7: No Critical Divergence
        no_critical_passed = parity_summary.critical_divergences == 0
        gate_results.append(
            GateResult(
                gate=FidelityGate.NO_CRITICAL_DIVERGENCE,
                passed=no_critical_passed,
                reason=(
                    f"Critical divergences: {parity_summary.critical_divergences} "
                    f"({'PASS' if no_critical_passed else 'FAIL'})"
                ),
                details={
                    "critical_count": parity_summary.critical_divergences
                },
            )
        )

        # Compute verdict
        passed_count = sum(1 for g in gate_results if g.passed)
        failed_count = len(gate_results) - passed_count

        if failed_count == 0:
            verdict = FidelityVerdict.PAPER_FIDELITY_PASS
        elif no_critical_passed:
            verdict = FidelityVerdict.CONDITIONAL
        else:
            verdict = FidelityVerdict.BLOCKED

        # Compute report hash
        report_data = {
            "campaign_id": campaign_id,
            "manifest_identity": self._manifest.compute_identity(),
            "verdict": verdict.value,
            "gates": [g.to_dict() for g in gate_results],
        }
        payload = json.dumps(report_data, sort_keys=True).encode("utf-8")
        report_hash = hashlib.sha256(payload).hexdigest()

        return FidelityReport(
            campaign_id=campaign_id,
            manifest_identity=self._manifest.compute_identity(),
            verdict=verdict,
            gate_results=gate_results,
            parity_summary=parity_summary.to_dict(),
            total_checks=len(gate_results),
            passed_gates=passed_count,
            failed_gates=failed_count,
            report_hash=report_hash,
        )
