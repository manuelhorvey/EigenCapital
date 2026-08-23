"""EigenRisk Engine — independent, fail-closed risk boundary.

The risk engine sits between PortfolioTarget and ApprovedTarget.
It asks: "Given current state, is this exposure permitted?"

Strategy code MUST NEVER bypass EigenRisk.

Usage:
    engine = EigenRiskEngine(policy=MODERATE)
    result = engine.evaluate(
        account_state=account_state,
        requested_notional=100_000,
    )
    if result.decision == "REJECTED":
        print(f"Trade rejected: {result.reason}")
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import List, Optional

from eigencapital.core.models.risk_check_result import RiskCheckResult
from eigencapital.risk.policy import RiskPolicy
from eigencapital.risk.checks.account_checks import (
    AccountState,
    run_all_account_checks,
)


@dataclass(frozen=True)
class RiskDecision:
    """Risk engine decision on a proposed exposure.

    Attributes:
        decision: APPROVED, REDUCED, or REJECTED
        approved_quantity: What risk engine allows (0 if REJECTED)
        reason: Explicit text rationale
        checks: All risk check results
    """

    decision: str  # APPROVED, REDUCED, REJECTED
    approved_quantity: float = 0.0
    reason: str = ""
    checks: List[RiskCheckResult] = field(default_factory=list)

    def __post_init__(self) -> None:
        valid = {"APPROVED", "REDUCED", "REJECTED"}
        if self.decision not in valid:
            raise ValueError(f"Invalid decision: {self.decision}")
        if self.decision == "REJECTED" and self.approved_quantity != 0:
            raise ValueError("REJECTED must have approved_quantity = 0")


class EigenRiskEngine:
    """Independent risk engine — fail-closed by default.

    Architecture:
        Strategy → StrategyIntent → PortfolioTarget → EigenRisk → ApprovedTarget

    Strategy code CANNOT bypass this boundary.

    The engine runs all hard constraint checks. If ANY check FAILs:
        - REJECTED (approved_quantity = 0)
    If any check WARNs but none FAIL:
        - APPROVED (with warnings in checks)
    """

    def __init__(self, policy: Optional[RiskPolicy] = None) -> None:
        self.policy = policy or RiskPolicy()

    def evaluate(
        self,
        account_state: AccountState,
        requested_notional: float = 0.0,
        requested_quantity: float = 0.0,
    ) -> RiskDecision:
        """Evaluate a proposed exposure against risk policy.

        Args:
            account_state: Current account state
            requested_notional: Notional value of proposed position
            requested_quantity: Signed quantity of proposed position

        Returns:
            RiskDecision with decision and check results
        """
        # Run all account-level checks
        checks = run_all_account_checks(account_state, self.policy)

        # Determine decision based on check results
        has_fail = any(c.status == "FAIL" for c in checks)
        has_warn = any(c.status == "WARN" for c in checks)

        if has_fail:
            failed_checks = [c for c in checks if c.status == "FAIL"]
            reason = "; ".join(c.message for c in failed_checks)
            return RiskDecision(
                decision="REJECTED",
                approved_quantity=0.0,
                reason=reason,
                checks=checks,
            )

        if has_warn:
            warned_checks = [c for c in checks if c.status == "WARN"]
            reason = "; ".join(c.message for c in warned_checks)
            return RiskDecision(
                decision="APPROVED",
                approved_quantity=requested_quantity,
                reason=f"Approved with warnings: {reason}",
                checks=checks,
            )

        return RiskDecision(
            decision="APPROVED",
            approved_quantity=requested_quantity,
            reason="All checks passed",
            checks=checks,
        )
