"""Production Qualification — evaluates production readiness.

Produces a verdict based on scaling fidelity, reconciliation,
attribution, and operational stability.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List

from eigencapital.production_qual.campaign_boundary import CampaignBoundary
from eigencapital.production_qual.scaling import ScaleLevel, ScalingMetrics


class ProductionVerdict(str, Enum):
    """Production qualification verdict."""

    BLOCKED = "blocked"
    INCONCLUSIVE = "inconclusive"
    QUALIFIED_WITH_RESTRICTIONS = "qualified_with_restrictions"
    QUALIFIED = "qualified"
    QUALIFIED_FOR_NEXT_SCALE = "qualified_for_next_scale"


@dataclass
class ProductionCheck:
    """A single production qualification check."""

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
class ProductionReport:
    """Complete production qualification report."""

    campaign_id: str
    scale_level: str
    verdict: ProductionVerdict
    checks: List[ProductionCheck]
    total_checks: int
    passed_checks: int
    failed_checks: int
    attribution: Dict[str, Any]
    scaling_metrics: Dict[str, Any]
    report_hash: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return {
            "campaign_id": self.campaign_id,
            "scale_level": self.scale_level,
            "verdict": self.verdict.value,
            "checks": [c.to_dict() for c in self.checks],
            "total_checks": self.total_checks,
            "passed_checks": self.passed_checks,
            "failed_checks": self.failed_checks,
            "attribution": self.attribution,
            "scaling_metrics": self.scaling_metrics,
            "report_hash": self.report_hash,
        }

    def to_markdown(self) -> str:
        lines = [
            "# Production Qualification Report",
            "",
            f"**Campaign:** {self.campaign_id}",
            f"**Scale Level:** {self.scale_level}",
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
                "## P&L Attribution",
                "",
                f"- R4 P&L: ${self.attribution.get('r4_pnl', 0):.2f}",
                f"- Pre-existing P&L: ${self.attribution.get('pre_existing_pnl', 0):.2f}",
                f"- Manual P&L: ${self.attribution.get('manual_pnl', 0):.2f}",
                f"- Total P&L: ${self.attribution.get('total_pnl', 0):.2f}",
                "",
                "## Scaling Metrics",
                "",
                f"- Slippage deterioration: {self.scaling_metrics.get('slippage_deterioration', 0):.2f}x",
                f"- Spread deterioration: {self.scaling_metrics.get('spread_deterioration', 0):.2f}x",
                f"- Fill rate: {self.scaling_metrics.get('fill_rate_at_current', 0):.1%}",
                f"- Margin usage: {self.scaling_metrics.get('margin_usage', 0):.1%}",
                "",
                "## Summary",
                "",
                f"- Passed: {self.passed_checks}/{self.total_checks}",
                f"- Failed: {self.failed_checks}/{self.total_checks}",
                "",
            ]
        )

        if self.verdict == ProductionVerdict.QUALIFIED:
            lines.append("**PRODUCTION QUALIFIED** — System remains safe at this scale.")
        elif self.verdict == ProductionVerdict.QUALIFIED_FOR_NEXT_SCALE:
            lines.append("**QUALIFIED FOR NEXT SCALE** — Ready to increase capital.")
        elif self.verdict == ProductionVerdict.BLOCKED:
            lines.append("**BLOCKED** — Critical scaling or safety issue detected.")
        else:
            lines.append("**INCONCLUSIVE** — Insufficient evidence at this scale.")

        return "\n".join(lines)


class ProductionEvaluator:
    """Evaluates production qualification."""

    def evaluate(
        self,
        campaign_id: str,
        scale_level: ScaleLevel,
        boundary: CampaignBoundary,
        scaling_metrics: ScalingMetrics,
        reconciliation_ok: bool = True,
        drift_detected: bool = False,
    ) -> ProductionReport:
        """Evaluate production readiness."""
        checks: List[ProductionCheck] = []
        attribution = boundary.get_attribution()

        # Check 1: No manual trades
        no_manual = attribution.get("manual_trades", 0) == 0
        checks.append(
            ProductionCheck(
                check_name="no_manual_trades",
                passed=no_manual,
                reason=f"Manual trades: {attribution.get('manual_trades', 0)}",
            )
        )

        # Check 2: R4 attribution clean
        r4_attribution = attribution.get("r4_trades", 0) > 0 or attribution.get("r4_open_positions", 0) > 0
        checks.append(
            ProductionCheck(
                check_name="r4_attribution",
                passed=r4_attribution,
                reason=f"R4 trades: {attribution.get('r4_trades', 0)}, open: {attribution.get('r4_open_positions', 0)}",
            )
        )

        # Check 3: Reconciliation
        checks.append(
            ProductionCheck(
                check_name="reconciliation",
                passed=reconciliation_ok,
                reason="100% broker/internal agreement" if reconciliation_ok else "Reconciliation mismatch",
            )
        )

        # Check 4: No drift
        checks.append(
            ProductionCheck(
                check_name="fingerprint_frozen",
                passed=not drift_detected,
                reason="Fingerprint unchanged" if not drift_detected else "Drift detected",
            )
        )

        # Check 5: Slippage
        slippage_ok = scaling_metrics.slippage_deterioration <= 2.0
        checks.append(
            ProductionCheck(
                check_name="slippage_scaling",
                passed=slippage_ok,
                reason=f"Slippage deterioration: {scaling_metrics.slippage_deterioration:.2f}x",
            )
        )

        # Check 6: Spread
        spread_ok = scaling_metrics.spread_deterioration <= 2.0
        checks.append(
            ProductionCheck(
                check_name="spread_scaling",
                passed=spread_ok,
                reason=f"Spread deterioration: {scaling_metrics.spread_deterioration:.2f}x",
            )
        )

        # Check 7: Fill rate
        fill_ok = scaling_metrics.fill_rate_at_current >= 0.90
        checks.append(
            ProductionCheck(
                check_name="fill_rate",
                passed=fill_ok,
                reason=f"Fill rate: {scaling_metrics.fill_rate_at_current:.1%}",
            )
        )

        # Check 8: Margin
        margin_ok = not scaling_metrics.margin_pressure
        checks.append(
            ProductionCheck(
                check_name="margin_pressure",
                passed=margin_ok,
                reason=f"Margin usage: {scaling_metrics.margin_usage:.1%}",
            )
        )

        # Check 9: Risk proportional
        checks.append(
            ProductionCheck(
                check_name="risk_proportional",
                passed=scaling_metrics.risk_proportional,
                reason=f"Position risk ratio: {scaling_metrics.position_risk_ratio:.2f}",
            )
        )

        # Compute verdict
        passed_count = sum(1 for c in checks if c.passed)
        failed_count = len(checks) - passed_count

        if failed_count == 0:
            if scale_level in (ScaleLevel.MICRO, ScaleLevel.MINIMAL):
                verdict = ProductionVerdict.QUALIFIED_FOR_NEXT_SCALE
            else:
                verdict = ProductionVerdict.QUALIFIED
        elif failed_count <= 2 and no_manual:
            verdict = ProductionVerdict.QUALIFIED_WITH_RESTRICTIONS
        elif failed_count <= 3:
            verdict = ProductionVerdict.INCONCLUSIVE
        else:
            verdict = ProductionVerdict.BLOCKED

        # Compute report hash
        report_data = {
            "campaign_id": campaign_id,
            "scale_level": scale_level.value,
            "verdict": verdict.value,
            "checks": [c.to_dict() for c in checks],
        }
        payload = json.dumps(report_data, sort_keys=True).encode("utf-8")
        report_hash = hashlib.sha256(payload).hexdigest()

        return ProductionReport(
            campaign_id=campaign_id,
            scale_level=scale_level.value,
            verdict=verdict,
            checks=checks,
            total_checks=len(checks),
            passed_checks=passed_count,
            failed_checks=failed_count,
            attribution=attribution,
            scaling_metrics=scaling_metrics.to_dict(),
            report_hash=report_hash,
        )
