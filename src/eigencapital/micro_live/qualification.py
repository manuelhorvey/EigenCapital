"""Micro-Live Qualification — evaluates micro-live campaign results.

Produces a verdict based on evidence, not profitability.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from typing import Dict, List, Any

from eigencapital.micro_live.campaign import (
    MicroLiveCampaign,
    MicroLiveVerdict,
)


@dataclass
class QualificationCheck:
    """A single qualification check."""

    check_name: str
    passed: bool
    reason: str
    details: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "check_name": self.check_name,
            "passed": self.passed,
            "reason": self.reason,
            "details": self.details,
        }


@dataclass
class QualificationReport:
    """Complete micro-live qualification report."""

    campaign_id: str
    envelope_identity: str
    verdict: MicroLiveVerdict
    checks: List[QualificationCheck]
    total_checks: int
    passed_checks: int
    failed_checks: int
    report_hash: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return {
            "campaign_id": self.campaign_id,
            "envelope_identity": self.envelope_identity,
            "verdict": self.verdict.value,
            "checks": [c.to_dict() for c in self.checks],
            "total_checks": self.total_checks,
            "passed_checks": self.passed_checks,
            "failed_checks": self.failed_checks,
            "report_hash": self.report_hash,
        }

    def to_markdown(self) -> str:
        lines = [
            "# Micro-Live Qualification Report",
            "",
            f"**Campaign:** {self.campaign_id}",
            f"**Verdict:** {self.verdict.value}",
            "",
            "## Checks",
            "",
        ]

        for check in self.checks:
            icon = "✅" if check.passed else "❌"
            lines.append(f"- {icon} **{check.check_name}**: {check.reason}")

        lines.extend(
            [
                "",
                "## Summary",
                "",
                f"- Passed: {self.passed_checks}/{self.total_checks}",
                f"- Failed: {self.failed_checks}/{self.total_checks}",
                "",
            ]
        )

        if self.verdict == MicroLiveVerdict.QUALIFIED:
            lines.append(
                "**MICRO-LIVE QUALIFIED** — Live execution remains inside validated envelope."
            )
        elif self.verdict == MicroLiveVerdict.QUALIFIED_WITH_RESTRICTIONS:
            lines.append(
                "**QUALIFIED WITH RESTRICTIONS** — Safe, but specific constraints remain mandatory."
            )
        elif self.verdict == MicroLiveVerdict.BLOCKED:
            lines.append("**BLOCKED** — Critical safety/execution failure detected.")
        else:
            lines.append("**INCONCLUSIVE** — Insufficient live evidence.")

        return "\n".join(lines)


class MicroLiveEvaluator:
    """Evaluates micro-live campaign and produces qualification verdict."""

    # Pre-registered thresholds
    MIN_FILL_RATE: float = 0.80  # 80% fill rate required
    MAX_REJECTION_RATE: float = 0.30  # max 30% rejection rate
    MIN_RECONCILIATION_RATE: float = 1.0  # 100% reconciliation required
    MIN_CAMPAIGN_DURATION_BARS: int = 100  # minimum bars for evidence
    MAX_KILL_EVENTS: int = 0  # zero kills allowed

    def evaluate(self, campaign: MicroLiveCampaign) -> QualificationReport:
        """Evaluate micro-live campaign and produce verdict."""
        checks: List[QualificationCheck] = []
        state = campaign.state
        envelope = campaign.envelope

        # Check 1: No kills
        no_kills = len(campaign._kill_log) == 0
        checks.append(
            QualificationCheck(
                check_name="no_kill_events",
                passed=no_kills,
                reason=f"Kill events: {len(campaign._kill_log)}",
                details={"kill_count": len(campaign._kill_log)},
            )
        )

        # Check 2: Reconciliation
        recon_ok = state.reconciliation_success_rate >= self.MIN_RECONCILIATION_RATE
        checks.append(
            QualificationCheck(
                check_name="reconciliation",
                passed=recon_ok,
                reason=f"Reconciliation rate: {state.reconciliation_success_rate:.1%}",
                details={"rate": state.reconciliation_success_rate},
            )
        )

        # Check 3: Fill rate
        fill_ok = state.fill_rate >= self.MIN_FILL_RATE or state.orders_submitted == 0
        checks.append(
            QualificationCheck(
                check_name="fill_rate",
                passed=fill_ok,
                reason=f"Fill rate: {state.fill_rate:.1%}",
                details={"rate": state.fill_rate},
            )
        )

        # Check 4: Rejection rate
        reject_ok = state.rejection_rate <= self.MAX_REJECTION_RATE
        checks.append(
            QualificationCheck(
                check_name="rejection_rate",
                passed=reject_ok,
                reason=f"Rejection rate: {state.rejection_rate:.1%}",
                details={"rate": state.rejection_rate},
            )
        )

        # Check 5: Drawdown within envelope
        dd_ok = state.current_drawdown <= envelope.max_drawdown_pct
        checks.append(
            QualificationCheck(
                check_name="drawdown_envelope",
                passed=dd_ok,
                reason=f"Drawdown: {state.current_drawdown:.1%} (max: {envelope.max_drawdown_pct:.1%})",
                details={
                    "current": state.current_drawdown,
                    "max": envelope.max_drawdown_pct,
                },
            )
        )

        # Check 6: Position limits
        pos_ok = state.open_positions <= envelope.max_concurrent_positions
        checks.append(
            QualificationCheck(
                check_name="position_limits",
                passed=pos_ok,
                reason=f"Open positions: {state.open_positions} (max: {envelope.max_concurrent_positions})",
                details={
                    "current": state.open_positions,
                    "max": envelope.max_concurrent_positions,
                },
            )
        )

        # Check 7: Sufficient evidence
        sufficient = (
            state.orders_submitted >= self.MIN_CAMPAIGN_DURATION_BARS
            or state.orders_filled > 0
        )
        checks.append(
            QualificationCheck(
                check_name="sufficient_evidence",
                passed=sufficient,
                reason=f"Orders submitted: {state.orders_submitted}",
                details={"orders": state.orders_submitted},
            )
        )

        # Compute verdict
        passed_count = sum(1 for c in checks if c.passed)
        failed_count = len(checks) - passed_count

        if failed_count == 0:
            verdict = MicroLiveVerdict.QUALIFIED
        elif no_kills and recon_ok:
            verdict = MicroLiveVerdict.QUALIFIED_WITH_RESTRICTIONS
        elif failed_count <= 2 and no_kills:
            verdict = MicroLiveVerdict.INCONCLUSIVE
        else:
            verdict = MicroLiveVerdict.BLOCKED

        # Compute report hash
        report_data = {
            "campaign_id": campaign._campaign_id,
            "verdict": verdict.value,
            "checks": [c.to_dict() for c in checks],
        }
        payload = json.dumps(report_data, sort_keys=True).encode("utf-8")
        report_hash = hashlib.sha256(payload).hexdigest()

        return QualificationReport(
            campaign_id=campaign._campaign_id,
            envelope_identity=envelope.compute_identity(),
            verdict=verdict,
            checks=checks,
            total_checks=len(checks),
            passed_checks=passed_count,
            failed_checks=failed_count,
            report_hash=report_hash,
        )
