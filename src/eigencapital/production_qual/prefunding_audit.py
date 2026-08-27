"""Pre-Funding Gate Audit — independent qualification before capital deployment.

Runs seven audit categories with deterministic pass/fail per check.
Every critical failure produces a predetermined safe outcome.
The auditor never mutates live state — it only reads and evaluates.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List


class AuditVerdict(str, Enum):
    """Pre-funding gate verdict."""

    GO = "GO"
    RESTRICTED = "RESTRICTED"
    NO_GO = "NO_GO"


class AuditCategory(str, Enum):
    """The seven audit categories."""

    IDENTITY = "identity"
    RISK = "risk"
    EXECUTION = "execution"
    HEALTH = "health"
    OBSERVABILITY = "observability"
    BROKER = "broker_boundary"
    CAPITAL = "capital_boundary"


@dataclass(frozen=True)
class AuditCheck:
    """A single audit check result."""

    check_id: str
    category: str
    description: str
    passed: bool
    severity: str = "CRITICAL"  # CRITICAL or WARNING
    details: str = ""
    expected: str = ""
    observed: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return {
            "check_id": self.check_id,
            "category": self.category,
            "description": self.description,
            "passed": self.passed,
            "severity": self.severity,
            "details": self.details,
            "expected": self.expected,
            "observed": self.observed,
        }


@dataclass
class AuditReport:
    """Complete pre-funding audit report."""

    campaign_id: str
    verdict: AuditVerdict
    checks: List[AuditCheck] = field(default_factory=list)
    manifest_fingerprint: str = ""
    report_hash: str = ""
    category_results: Dict[str, Dict[str, Any]] = field(default_factory=dict)

    @property
    def total_checks(self) -> int:
        return len(self.checks)

    @property
    def passed_checks(self) -> int:
        return sum(1 for c in self.checks if c.passed)

    @property
    def failed_checks(self) -> int:
        return self.total_checks - self.passed_checks

    @property
    def critical_failures(self) -> List[AuditCheck]:
        return [c for c in self.checks if not c.passed and c.severity == "CRITICAL"]

    @property
    def warnings(self) -> List[AuditCheck]:
        return [c for c in self.checks if not c.passed and c.severity == "WARNING"]

    def compute_hash(self) -> str:
        data = {
            "campaign_id": self.campaign_id,
            "verdict": self.verdict.value,
            "total_checks": self.total_checks,
            "passed_checks": self.passed_checks,
            "failed_checks": self.failed_checks,
            "checks": [c.to_dict() for c in self.checks],
        }
        payload = json.dumps(data, sort_keys=True).encode("utf-8")
        return hashlib.sha256(payload).hexdigest()

    def to_dict(self) -> Dict[str, Any]:
        return {
            "campaign_id": self.campaign_id,
            "verdict": self.verdict.value,
            "total_checks": self.total_checks,
            "passed_checks": self.passed_checks,
            "failed_checks": self.failed_checks,
            "critical_failures": len(self.critical_failures),
            "warnings": len(self.warnings),
            "manifest_fingerprint": self.manifest_fingerprint,
            "category_results": self.category_results,
            "checks": [c.to_dict() for c in self.checks],
            "report_hash": self.report_hash,
        }

    def to_markdown(self) -> str:
        lines = [
            "# Pre-Funding Gate Audit Report",
            "",
            f"**Campaign:** {self.campaign_id}",
            f"**Verdict:** {self.verdict.value}",
            f"**Checks:** {self.passed_checks}/{self.total_checks} passed",
            f"**Critical failures:** {len(self.critical_failures)}",
            f"**Manifest:** {self.manifest_fingerprint[:16]}",
            "",
        ]

        # Per-category summary
        lines.append("## Category Summary")
        lines.append("")
        lines.append("| Category | Passed | Failed | Status |")
        lines.append("|---|---|---|---|")
        for cat_name, cat_data in self.category_results.items():
            p = cat_data.get("passed", 0)
            f = cat_data.get("failed", 0)
            status = "✅" if f == 0 else "❌"
            lines.append(f"| {cat_name} | {p} | {f} | {status} |")

        lines.extend(["", "## Detailed Checks", ""])

        for check in self.checks:
            icon = "✅" if check.passed else ("❌" if check.severity == "CRITICAL" else "⚠️")
            lines.append(f"- {icon} **[{check.category}] {check.check_id}**: {check.description}")
            if not check.passed:
                lines.append(f"  - Expected: {check.expected}")
                lines.append(f"  - Observed: {check.observed}")
                if check.details:
                    lines.append(f"  - Detail: {check.details}")

        lines.extend(["", "## Verdict", ""])

        if self.verdict == AuditVerdict.GO:
            lines.append("**GO** — All critical checks passed. System is safe to deploy $5K capital.")
        elif self.verdict == AuditVerdict.RESTRICTED:
            lines.append(
                "**RESTRICTED** — Some checks passed with warnings. Deployment permitted with documented constraints."
            )
        else:
            lines.append(
                "**NO-GO** — Critical failures detected. "
                "Capital deployment is NOT authorized. Fix all critical failures and re-audit."
            )

        return "\n".join(lines)


class PrefundingGateAuditor:
    """Runs the full 7-category pre-funding audit.

    This auditor evaluates system state without mutating it.
    Each category produces independent checks; a CRITICAL failure
    in any category results in NO-GO.
    """

    def __init__(self) -> None:
        self._checks: List[AuditCheck] = []

    def reset(self) -> None:
        self._checks.clear()

    def _add_check(self, check: AuditCheck) -> None:
        self._checks.append(check)

    # ── 1. Identity ───────────────────────────────────────────────

    def audit_identity(
        self,
        frozen_manifest_fingerprint: str,
        production_config_fingerprint: str,
        manifest_computed_identity: str,
        golden_manifest_guard_passes: bool,
        strategy_version: str = "R4.0",
        data_terminal_id: str = "168966110",
    ) -> List[AuditCheck]:
        """Verify frozen R4 manifest matches production configuration."""
        checks: List[AuditCheck] = []
        cat = AuditCategory.IDENTITY.value

        # 1.1 Frozen manifest fingerprint is present
        has_fingerprint = bool(frozen_manifest_fingerprint)
        self._add_check(
            AuditCheck(
                check_id="ID-01",
                category=cat,
                description="Frozen R4 manifest fingerprint is non-empty",
                passed=has_fingerprint,
                expected="non-empty fingerprint",
                observed=frozen_manifest_fingerprint[:16] if frozen_manifest_fingerprint else "(empty)",
            )
        )
        checks.append(self._checks[-1])

        # 1.2 Production config hashes to frozen identity
        config_matches = production_config_fingerprint == frozen_manifest_fingerprint
        self._add_check(
            AuditCheck(
                check_id="ID-02",
                category=cat,
                description="Production configuration matches frozen identity",
                passed=config_matches,
                expected=frozen_manifest_fingerprint[:16],
                observed=production_config_fingerprint[:16] if production_config_fingerprint else "(empty)",
                details="Production config must hash to the same fingerprint as the frozen manifest",
            )
        )
        checks.append(self._checks[-1])

        # 1.3 Manifest computed identity matches frozen fingerprint
        identity_matches = manifest_computed_identity == frozen_manifest_fingerprint
        self._add_check(
            AuditCheck(
                check_id="ID-03",
                category=cat,
                description="Manifest computed identity matches frozen fingerprint",
                passed=identity_matches,
                expected=frozen_manifest_fingerprint[:16],
                observed=manifest_computed_identity[:16] if manifest_computed_identity else "(empty)",
            )
        )
        checks.append(self._checks[-1])

        # 1.4 Strategy version is frozen
        version_ok = strategy_version == "R4.0"
        self._add_check(
            AuditCheck(
                check_id="ID-04",
                category=cat,
                description="Strategy version is frozen at R4.0",
                passed=version_ok,
                expected="R4.0",
                observed=strategy_version,
            )
        )
        checks.append(self._checks[-1])

        # 1.5 Golden manifest guard passes
        self._add_check(
            AuditCheck(
                check_id="ID-05",
                category=cat,
                description="Golden manifest guard passes",
                passed=golden_manifest_guard_passes,
                expected="guard pass",
                observed="pass" if golden_manifest_guard_passes else "FAIL",
            )
        )
        checks.append(self._checks[-1])

        # 1.6 No strategy/risk/execution parameter drift
        # (Drift is detected if config fingerprint != frozen fingerprint)
        no_drift = config_matches and identity_matches
        self._add_check(
            AuditCheck(
                check_id="ID-06",
                category=cat,
                description="No strategy/risk/execution parameter drift",
                passed=no_drift,
                expected="no drift detected",
                observed="clean" if no_drift else "DRIFT DETECTED",
                severity="CRITICAL",
            )
        )
        checks.append(self._checks[-1])

        return checks

    # ── 2. Risk ───────────────────────────────────────────────────

    def audit_risk(
        self,
        risk_policy_is_authority: bool,
        exposure_maps_populated: bool,
        concentration_enforced: bool,
        asset_class_enforced: bool,
        drawdown_verified: bool,
        daily_loss_verified: bool,
        leverage_verified: bool,
        position_limit_verified: bool,
        order_limit_verified: bool,
        kill_switch_verified: bool,
        missing_state_fails_closed: bool,
    ) -> List[AuditCheck]:
        """Verify RiskPolicy is the sole account-level authority."""
        checks: List[AuditCheck] = []
        cat = AuditCategory.RISK.value

        self._add_check(
            AuditCheck(
                check_id="RK-01",
                category=cat,
                description="RiskPolicy is sole account-level authority",
                passed=risk_policy_is_authority,
                expected="RiskPolicy sole authority",
                observed="sole authority" if risk_policy_is_authority else "NOT sole authority",
            )
        )
        checks.append(self._checks[-1])

        self._add_check(
            AuditCheck(
                check_id="RK-02",
                category=cat,
                description="Position and asset-class exposure maps populated from broker state",
                passed=exposure_maps_populated,
                expected="exposure maps populated",
                observed="populated" if exposure_maps_populated else "EMPTY",
            )
        )
        checks.append(self._checks[-1])

        self._add_check(
            AuditCheck(
                check_id="RK-03",
                category=cat,
                description="Concentration limits enforced (not diagnostic-only)",
                passed=concentration_enforced,
                expected="enforced",
                observed="enforced" if concentration_enforced else "diagnostic-only",
            )
        )
        checks.append(self._checks[-1])

        self._add_check(
            AuditCheck(
                check_id="RK-04",
                category=cat,
                description="Asset-class limits enforced (not diagnostic-only)",
                passed=asset_class_enforced,
                expected="enforced",
                observed="enforced" if asset_class_enforced else "diagnostic-only",
            )
        )
        checks.append(self._checks[-1])

        self._add_check(
            AuditCheck(
                check_id="RK-05",
                category=cat,
                description="Drawdown limits verified",
                passed=drawdown_verified,
                expected="verified",
                observed="verified" if drawdown_verified else "NOT verified",
            )
        )
        checks.append(self._checks[-1])

        self._add_check(
            AuditCheck(
                check_id="RK-06",
                category=cat,
                description="Daily loss limits verified",
                passed=daily_loss_verified,
                expected="verified",
                observed="verified" if daily_loss_verified else "NOT verified",
            )
        )
        checks.append(self._checks[-1])

        self._add_check(
            AuditCheck(
                check_id="RK-07",
                category=cat,
                description="Leverage limits verified",
                passed=leverage_verified,
                expected="verified",
                observed="verified" if leverage_verified else "NOT verified",
            )
        )
        checks.append(self._checks[-1])

        self._add_check(
            AuditCheck(
                check_id="RK-08",
                category=cat,
                description="Position count limits verified",
                passed=position_limit_verified,
                expected="verified",
                observed="verified" if position_limit_verified else "NOT verified",
            )
        )
        checks.append(self._checks[-1])

        self._add_check(
            AuditCheck(
                check_id="RK-09",
                category=cat,
                description="Order frequency limits verified",
                passed=order_limit_verified,
                expected="verified",
                observed="verified" if order_limit_verified else "NOT verified",
            )
        )
        checks.append(self._checks[-1])

        self._add_check(
            AuditCheck(
                check_id="RK-10",
                category=cat,
                description="Kill switch verified",
                passed=kill_switch_verified,
                expected="verified",
                observed="verified" if kill_switch_verified else "NOT verified",
            )
        )
        checks.append(self._checks[-1])

        self._add_check(
            AuditCheck(
                check_id="RK-11",
                category=cat,
                description="Missing state fails closed",
                passed=missing_state_fails_closed,
                expected="fail closed on missing state",
                observed="fail closed" if missing_state_fails_closed else "FAIL OPEN (unsafe)",
                severity="CRITICAL",
            )
        )
        checks.append(self._checks[-1])

        return checks

    # ── 3. Execution ──────────────────────────────────────────────

    def audit_execution(
        self,
        partial_fill_active: bool,
        broker_reconciliation_authoritative: bool,
        duplicate_fill_protection: bool,
        disconnect_reconcile_resume_enforced: bool,
        no_reconnect_only_trading: bool,
        kill_freeze_independently_tested: bool,
    ) -> List[AuditCheck]:
        """Verify execution safety: partial fills, reconciliation, duplicates."""
        checks: List[AuditCheck] = []
        cat = AuditCategory.EXECUTION.value

        self._add_check(
            AuditCheck(
                check_id="EX-01",
                category=cat,
                description="Partial-fill state machine active",
                passed=partial_fill_active,
                expected="active",
                observed="active" if partial_fill_active else "INACTIVE",
            )
        )
        checks.append(self._checks[-1])

        self._add_check(
            AuditCheck(
                check_id="EX-02",
                category=cat,
                description="Broker-authoritative reconciliation",
                passed=broker_reconciliation_authoritative,
                expected="broker authoritative",
                observed="authoritative" if broker_reconciliation_authoritative else "NOT authoritative",
            )
        )
        checks.append(self._checks[-1])

        self._add_check(
            AuditCheck(
                check_id="EX-03",
                category=cat,
                description="Duplicate fill protection",
                passed=duplicate_fill_protection,
                expected="protected",
                observed="protected" if duplicate_fill_protection else "UNPROTECTED",
            )
        )
        checks.append(self._checks[-1])

        self._add_check(
            AuditCheck(
                check_id="EX-04",
                category=cat,
                description="Disconnect → reconcile → resume sequence enforced",
                passed=disconnect_reconcile_resume_enforced,
                expected="sequence enforced",
                observed="enforced" if disconnect_reconcile_resume_enforced else "NOT enforced",
            )
        )
        checks.append(self._checks[-1])

        self._add_check(
            AuditCheck(
                check_id="EX-05",
                category=cat,
                description="No reconnect-only trading",
                passed=no_reconnect_only_trading,
                expected="reconnect alone does not grant permission",
                observed="safe" if no_reconnect_only_trading else "UNSAFE: reconnect grants trading",
            )
        )
        checks.append(self._checks[-1])

        self._add_check(
            AuditCheck(
                check_id="EX-06",
                category=cat,
                description="Kill/freeze mechanisms independently tested",
                passed=kill_freeze_independently_tested,
                expected="tested",
                observed="tested" if kill_freeze_independently_tested else "UNTESTED",
            )
        )
        checks.append(self._checks[-1])

        return checks

    # ── 4. Health ─────────────────────────────────────────────────

    def audit_health(
        self,
        healthy_permits_trade: bool,
        degraded_manage_only: bool,
        critical_halts: bool,
        frozen_halts: bool,
        stale_halts: bool,
        unparseable_halts: bool,
        exception_halts: bool,
        manual_reset_required: bool,
    ) -> List[AuditCheck]:
        """Verify health gate state machine semantics."""
        checks: List[AuditCheck] = []
        cat = AuditCategory.HEALTH.value

        self._add_check(
            AuditCheck(
                check_id="HL-01",
                category=cat,
                description="HEALTHY → TRADE",
                passed=healthy_permits_trade,
                expected="TRADE action",
                observed="TRADE" if healthy_permits_trade else "NOT TRADE",
            )
        )
        checks.append(self._checks[-1])

        self._add_check(
            AuditCheck(
                check_id="HL-02",
                category=cat,
                description="DEGRADED → MANAGE_ONLY",
                passed=degraded_manage_only,
                expected="MANAGE_ONLY action",
                observed="MANAGE_ONLY" if degraded_manage_only else "NOT MANAGE_ONLY",
            )
        )
        checks.append(self._checks[-1])

        self._add_check(
            AuditCheck(
                check_id="HL-03",
                category=cat,
                description="CRITICAL → HALT",
                passed=critical_halts,
                expected="HALT action",
                observed="HALT" if critical_halts else "NOT HALT",
            )
        )
        checks.append(self._checks[-1])

        self._add_check(
            AuditCheck(
                check_id="HL-04",
                category=cat,
                description="FROZEN → HALT",
                passed=frozen_halts,
                expected="HALT action",
                observed="HALT" if frozen_halts else "NOT HALT",
            )
        )
        checks.append(self._checks[-1])

        self._add_check(
            AuditCheck(
                check_id="HL-05",
                category=cat,
                description="Stale health snapshot → HALT",
                passed=stale_halts,
                expected="HALT",
                observed="HALT" if stale_halts else "NOT HALT",
            )
        )
        checks.append(self._checks[-1])

        self._add_check(
            AuditCheck(
                check_id="HL-06",
                category=cat,
                description="Unparseable health state → HALT",
                passed=unparseable_halts,
                expected="HALT",
                observed="HALT" if unparseable_halts else "NOT HALT",
            )
        )
        checks.append(self._checks[-1])

        self._add_check(
            AuditCheck(
                check_id="HL-07",
                category=cat,
                description="Monitor exception → HALT (fail closed)",
                passed=exception_halts,
                expected="HALT",
                observed="HALT" if exception_halts else "NOT HALT",
            )
        )
        checks.append(self._checks[-1])

        self._add_check(
            AuditCheck(
                check_id="HL-08",
                category=cat,
                description="Manual reset required for frozen state",
                passed=manual_reset_required,
                expected="manual reset required",
                observed="manual reset" if manual_reset_required else "auto-reset (unsafe)",
            )
        )
        checks.append(self._checks[-1])

        return checks

    # ── 5. Observability ──────────────────────────────────────────

    def audit_observability(
        self,
        events_durably_recorded: bool,
        alert_delivery_works: bool,
        alert_failure_cannot_weaken_safety: bool,
        tamper_evident_log_verifies: bool,
    ) -> List[AuditCheck]:
        """Verify observability: durable records, alerts, tamper evidence."""
        checks: List[AuditCheck] = []
        cat = AuditCategory.OBSERVABILITY.value

        self._add_check(
            AuditCheck(
                check_id="OB-01",
                category=cat,
                description="Critical events durably recorded",
                passed=events_durably_recorded,
                expected="durably recorded",
                observed="recorded" if events_durably_recorded else "NOT recorded",
            )
        )
        checks.append(self._checks[-1])

        self._add_check(
            AuditCheck(
                check_id="OB-02",
                category=cat,
                description="Alert delivery works",
                passed=alert_delivery_works,
                expected="delivery functional",
                observed="functional" if alert_delivery_works else "BROKEN",
            )
        )
        checks.append(self._checks[-1])

        self._add_check(
            AuditCheck(
                check_id="OB-03",
                category=cat,
                description="Alert failure cannot weaken safety state",
                passed=alert_failure_cannot_weaken_safety,
                expected="safety state unchanged on alert failure",
                observed="safety preserved" if alert_failure_cannot_weaken_safety else "SAFETY COMPROMISED",
                severity="CRITICAL",
            )
        )
        checks.append(self._checks[-1])

        self._add_check(
            AuditCheck(
                check_id="OB-04",
                category=cat,
                description="Tamper-evident health history verifies correctly",
                passed=tamper_evident_log_verifies,
                expected="chain verifies",
                observed="verified" if tamper_evident_log_verifies else "CHAIN BROKEN",
            )
        )
        checks.append(self._checks[-1])

        return checks

    # ── 6. Broker Boundary ────────────────────────────────────────

    def audit_broker_boundary(
        self,
        correct_account: bool,
        correct_environment: bool,
        correct_symbol_mapping: bool,
        correct_contract_specs: bool,
        correct_volume_price_constraints: bool,
        spread_slippage_controls: bool,
        no_environment_confusion: bool,
    ) -> List[AuditCheck]:
        """Verify broker boundary: correct account, environment, symbols."""
        checks: List[AuditCheck] = []
        cat = AuditCategory.BROKER.value

        self._add_check(
            AuditCheck(
                check_id="BB-01",
                category=cat,
                description="Correct MT5 account",
                passed=correct_account,
                expected="correct account",
                observed="correct" if correct_account else "WRONG ACCOUNT",
            )
        )
        checks.append(self._checks[-1])

        self._add_check(
            AuditCheck(
                check_id="BB-02",
                category=cat,
                description="Correct environment (demo vs live)",
                passed=correct_environment,
                expected="correct environment",
                observed="correct" if correct_environment else "WRONG ENVIRONMENT",
            )
        )
        checks.append(self._checks[-1])

        self._add_check(
            AuditCheck(
                check_id="BB-03",
                category=cat,
                description="Correct symbol mapping",
                passed=correct_symbol_mapping,
                expected="correct mapping",
                observed="correct" if correct_symbol_mapping else "WRONG MAPPING",
            )
        )
        checks.append(self._checks[-1])

        self._add_check(
            AuditCheck(
                check_id="BB-04",
                category=cat,
                description="Correct contract specifications",
                passed=correct_contract_specs,
                expected="correct specs",
                observed="correct" if correct_contract_specs else "WRONG SPECS",
            )
        )
        checks.append(self._checks[-1])

        self._add_check(
            AuditCheck(
                check_id="BB-05",
                category=cat,
                description="Correct volume/price constraints",
                passed=correct_volume_price_constraints,
                expected="correct constraints",
                observed="correct" if correct_volume_price_constraints else "WRONG CONSTRAINTS",
            )
        )
        checks.append(self._checks[-1])

        self._add_check(
            AuditCheck(
                check_id="BB-06",
                category=cat,
                description="Spread/slippage controls active",
                passed=spread_slippage_controls,
                expected="controls active",
                observed="active" if spread_slippage_controls else "INACTIVE",
            )
        )
        checks.append(self._checks[-1])

        self._add_check(
            AuditCheck(
                check_id="BB-07",
                category=cat,
                description="No accidental demo/live/environment confusion",
                passed=no_environment_confusion,
                expected="no confusion",
                observed="clean" if no_environment_confusion else "CONFUSION DETECTED",
                severity="CRITICAL",
            )
        )
        checks.append(self._checks[-1])

        return checks

    # ── 7. Capital Boundary ───────────────────────────────────────

    def audit_capital_boundary(
        self,
        max_capital_enforced: bool,
        campaign_duration_preregistered: bool,
        risk_envelope_preregistered: bool,
        r4_positions_separated: bool,
        pre_existing_separated: bool,
        no_manual_trading: bool,
    ) -> List[AuditCheck]:
        """Verify capital boundary: $5K max, duration, risk envelope, separation."""
        checks: List[AuditCheck] = []
        cat = AuditCategory.CAPITAL.value

        self._add_check(
            AuditCheck(
                check_id="CB-01",
                category=cat,
                description="$5K is maximum authorized campaign equity",
                passed=max_capital_enforced,
                expected="$5,000 max",
                observed="$5,000 enforced" if max_capital_enforced else "NOT enforced",
            )
        )
        checks.append(self._checks[-1])

        self._add_check(
            AuditCheck(
                check_id="CB-02",
                category=cat,
                description="Campaign duration pre-registered",
                passed=campaign_duration_preregistered,
                expected="duration registered",
                observed="registered" if campaign_duration_preregistered else "NOT registered",
            )
        )
        checks.append(self._checks[-1])

        self._add_check(
            AuditCheck(
                check_id="CB-03",
                category=cat,
                description="Risk envelope pre-registered for MINIMAL scale",
                passed=risk_envelope_preregistered,
                expected="envelope registered",
                observed="registered" if risk_envelope_preregistered else "NOT registered",
            )
        )
        checks.append(self._checks[-1])

        self._add_check(
            AuditCheck(
                check_id="CB-04",
                category=cat,
                description="R4-owned positions explicitly separated",
                passed=r4_positions_separated,
                expected="separated",
                observed="separated" if r4_positions_separated else "NOT separated",
            )
        )
        checks.append(self._checks[-1])

        self._add_check(
            AuditCheck(
                check_id="CB-05",
                category=cat,
                description="Pre-existing positions separated from R4",
                passed=pre_existing_separated,
                expected="separated",
                observed="separated" if pre_existing_separated else "NOT separated",
            )
        )
        checks.append(self._checks[-1])

        self._add_check(
            AuditCheck(
                check_id="CB-06",
                category=cat,
                description="No manual trading during qualification",
                passed=no_manual_trading,
                expected="zero manual trades",
                observed="zero" if no_manual_trading else "MANUAL TRADES DETECTED",
                severity="CRITICAL",
            )
        )
        checks.append(self._checks[-1])

        return checks

    # ── Verdict Computation ───────────────────────────────────────

    def compute_verdict(
        self,
        checks: List[AuditCheck] | None = None,
    ) -> AuditVerdict:
        """Compute the gate verdict from all checks.

        Rules:
        - NO-GO: any CRITICAL check failed
        - RESTRICTED: WARNING checks failed but no CRITICAL failures
        - GO: all checks passed
        """
        all_checks = checks if checks is not None else self._checks

        critical_failures = [c for c in all_checks if not c.passed and c.severity == "CRITICAL"]
        warning_failures = [c for c in all_checks if not c.passed and c.severity == "WARNING"]

        if critical_failures:
            return AuditVerdict.NO_GO
        if warning_failures:
            return AuditVerdict.RESTRICTED
        return AuditVerdict.GO

    # ── Run All Categories ────────────────────────────────────────

    def run_full_audit(
        self,
        campaign_id: str,
        # Identity params
        frozen_manifest_fingerprint: str = "",
        production_config_fingerprint: str = "",
        manifest_computed_identity: str = "",
        golden_manifest_guard_passes: bool = False,
        strategy_version: str = "R4.0",
        data_terminal_id: str = "168966110",
        # Risk params
        risk_policy_is_authority: bool = False,
        exposure_maps_populated: bool = False,
        concentration_enforced: bool = False,
        asset_class_enforced: bool = False,
        drawdown_verified: bool = False,
        daily_loss_verified: bool = False,
        leverage_verified: bool = False,
        position_limit_verified: bool = False,
        order_limit_verified: bool = False,
        kill_switch_verified: bool = False,
        missing_state_fails_closed: bool = False,
        # Execution params
        partial_fill_active: bool = False,
        broker_reconciliation_authoritative: bool = False,
        duplicate_fill_protection: bool = False,
        disconnect_reconcile_resume_enforced: bool = False,
        no_reconnect_only_trading: bool = False,
        kill_freeze_independently_tested: bool = False,
        # Health params
        healthy_permits_trade: bool = False,
        degraded_manage_only: bool = False,
        critical_halts: bool = False,
        frozen_halts: bool = False,
        stale_halts: bool = False,
        unparseable_halts: bool = False,
        exception_halts: bool = False,
        manual_reset_required: bool = False,
        # Observability params
        events_durably_recorded: bool = False,
        alert_delivery_works: bool = False,
        alert_failure_cannot_weaken_safety: bool = False,
        tamper_evident_log_verifies: bool = False,
        # Broker boundary params
        correct_account: bool = False,
        correct_environment: bool = False,
        correct_symbol_mapping: bool = False,
        correct_contract_specs: bool = False,
        correct_volume_price_constraints: bool = False,
        spread_slippage_controls: bool = False,
        no_environment_confusion: bool = False,
        # Capital boundary params
        max_capital_enforced: bool = False,
        campaign_duration_preregistered: bool = False,
        risk_envelope_preregistered: bool = False,
        r4_positions_separated: bool = False,
        pre_existing_separated: bool = False,
        no_manual_trading: bool = False,
    ) -> AuditReport:
        """Run the complete 7-category audit and produce a report."""
        self.reset()

        # Run each category
        self.audit_identity(
            frozen_manifest_fingerprint=frozen_manifest_fingerprint,
            production_config_fingerprint=production_config_fingerprint,
            manifest_computed_identity=manifest_computed_identity,
            golden_manifest_guard_passes=golden_manifest_guard_passes,
            strategy_version=strategy_version,
            data_terminal_id=data_terminal_id,
        )
        self.audit_risk(
            risk_policy_is_authority=risk_policy_is_authority,
            exposure_maps_populated=exposure_maps_populated,
            concentration_enforced=concentration_enforced,
            asset_class_enforced=asset_class_enforced,
            drawdown_verified=drawdown_verified,
            daily_loss_verified=daily_loss_verified,
            leverage_verified=leverage_verified,
            position_limit_verified=position_limit_verified,
            order_limit_verified=order_limit_verified,
            kill_switch_verified=kill_switch_verified,
            missing_state_fails_closed=missing_state_fails_closed,
        )
        self.audit_execution(
            partial_fill_active=partial_fill_active,
            broker_reconciliation_authoritative=broker_reconciliation_authoritative,
            duplicate_fill_protection=duplicate_fill_protection,
            disconnect_reconcile_resume_enforced=disconnect_reconcile_resume_enforced,
            no_reconnect_only_trading=no_reconnect_only_trading,
            kill_freeze_independently_tested=kill_freeze_independently_tested,
        )
        self.audit_health(
            healthy_permits_trade=healthy_permits_trade,
            degraded_manage_only=degraded_manage_only,
            critical_halts=critical_halts,
            frozen_halts=frozen_halts,
            stale_halts=stale_halts,
            unparseable_halts=unparseable_halts,
            exception_halts=exception_halts,
            manual_reset_required=manual_reset_required,
        )
        self.audit_observability(
            events_durably_recorded=events_durably_recorded,
            alert_delivery_works=alert_delivery_works,
            alert_failure_cannot_weaken_safety=alert_failure_cannot_weaken_safety,
            tamper_evident_log_verifies=tamper_evident_log_verifies,
        )
        self.audit_broker_boundary(
            correct_account=correct_account,
            correct_environment=correct_environment,
            correct_symbol_mapping=correct_symbol_mapping,
            correct_contract_specs=correct_contract_specs,
            correct_volume_price_constraints=correct_volume_price_constraints,
            spread_slippage_controls=spread_slippage_controls,
            no_environment_confusion=no_environment_confusion,
        )
        self.audit_capital_boundary(
            max_capital_enforced=max_capital_enforced,
            campaign_duration_preregistered=campaign_duration_preregistered,
            risk_envelope_preregistered=risk_envelope_preregistered,
            r4_positions_separated=r4_positions_separated,
            pre_existing_separated=pre_existing_separated,
            no_manual_trading=no_manual_trading,
        )

        # Compute verdict
        verdict = self.compute_verdict()

        # Build category results
        category_results: Dict[str, Dict[str, Any]] = {}
        for cat in AuditCategory:
            cat_checks = [c for c in self._checks if c.category == cat.value]
            cat_passed = sum(1 for c in cat_checks if c.passed)
            cat_failed = len(cat_checks) - cat_passed
            category_results[cat.value] = {
                "total": len(cat_checks),
                "passed": cat_passed,
                "failed": cat_failed,
            }

        report = AuditReport(
            campaign_id=campaign_id,
            verdict=verdict,
            checks=list(self._checks),
            manifest_fingerprint=frozen_manifest_fingerprint,
            category_results=category_results,
        )
        report.report_hash = report.compute_hash()

        return report
