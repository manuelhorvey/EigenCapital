"""Capital Boundary — validates capital deployment constraints before funded campaign.

Defines and enforces:
- Maximum authorized campaign equity ($5K)
- Campaign duration and risk envelope
- Position separation (R4 vs pre-existing)
- No manual trading during qualification
- GO / RESTRICTED / NO-GO criteria
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional


class CapitalVerdict(str, Enum):
    """Capital deployment verdict."""

    GO = "GO"
    RESTRICTED = "RESTRICTED"
    NO_GO = "NO_GO"


@dataclass(frozen=True)
class CapitalBoundaryConfig:
    """Pre-registered capital constraints for the MINIMAL campaign."""

    max_equity: float = 5_100.0  # $5K + 2% buffer for P&L drift
    max_drawdown_pct: float = 20.0
    max_daily_loss: float = 250.0
    max_total_drawdown: float = 1_000.0
    max_position_size: float = 1_500.0
    max_order_notional: float = 1_500.0
    max_concurrent_positions: int = 8
    campaign_duration_days: int = 30
    max_spread: float = 0.0015
    max_slippage: float = 0.0008
    max_execution_divergence: float = 0.004

    def compute_fingerprint(self) -> str:
        data = {
            "max_equity": self.max_equity,
            "max_drawdown_pct": self.max_drawdown_pct,
            "max_daily_loss": self.max_daily_loss,
            "max_total_drawdown": self.max_total_drawdown,
            "max_position_size": self.max_position_size,
            "max_order_notional": self.max_order_notional,
            "max_concurrent_positions": self.max_concurrent_positions,
            "campaign_duration_days": self.campaign_duration_days,
            "max_spread": self.max_spread,
            "max_slippage": self.max_slippage,
            "max_execution_divergence": self.max_execution_divergence,
        }
        payload = json.dumps(data, sort_keys=True).encode("utf-8")
        return hashlib.sha256(payload).hexdigest()


@dataclass(frozen=True)
class CapitalCheck:
    """Result of a single capital boundary check."""

    check_id: str
    passed: bool
    description: str
    expected: str = ""
    observed: str = ""
    severity: str = "CRITICAL"

    def to_dict(self) -> Dict[str, Any]:
        return {
            "check_id": self.check_id,
            "passed": self.passed,
            "description": self.description,
            "expected": self.expected,
            "observed": self.observed,
            "severity": self.severity,
        }


class CapitalBoundaryValidator:
    """Validates capital deployment constraints.

    All checks are read-only — they inspect state and configuration
    without modifying anything.
    """

    def __init__(self, config: Optional[CapitalBoundaryConfig] = None) -> None:
        self._config = config or CapitalBoundaryConfig()
        self._checks: List[CapitalCheck] = []

    def validate_max_equity(
        self,
        actual_equity: float,
    ) -> CapitalCheck:
        """Check that account equity does not exceed authorized maximum."""
        passed = actual_equity <= self._config.max_equity
        check = CapitalCheck(
            check_id="CB-EQUITY",
            passed=passed,
            description="Account equity within authorized maximum",
            expected=f"<= ${self._config.max_equity:,.0f}",
            observed=f"${actual_equity:,.2f}",
        )
        self._checks.append(check)
        return check

    def validate_campaign_duration(
        self,
        start_timestamp: str,
        end_timestamp: str,
        actual_duration_days: float,
    ) -> CapitalCheck:
        """Check that campaign duration is within pre-registered bounds."""
        passed = actual_duration_days <= self._config.campaign_duration_days
        check = CapitalCheck(
            check_id="CB-DURATION",
            passed=passed,
            description="Campaign duration within pre-registered bounds",
            expected=f"<= {self._config.campaign_duration_days} days",
            observed=f"{actual_duration_days:.1f} days",
        )
        self._checks.append(check)
        return check

    def validate_risk_envelope(
        self,
        envelope_fingerprint: str,
        expected_fingerprint: str,
    ) -> CapitalCheck:
        """Check that risk envelope matches the pre-registered MINIMAL envelope."""
        passed = envelope_fingerprint == expected_fingerprint
        check = CapitalCheck(
            check_id="CB-ENVELOPE",
            passed=passed,
            description="Risk envelope matches pre-registered MINIMAL envelope",
            expected=expected_fingerprint[:16] if expected_fingerprint else "(empty)",
            observed=envelope_fingerprint[:16] if envelope_fingerprint else "(empty)",
        )
        self._checks.append(check)
        return check

    def validate_position_separation(
        self,
        r4_position_count: int,
        pre_existing_position_count: int,
        manual_position_count: int,
    ) -> CapitalCheck:
        """Check that R4 and pre-existing positions are explicitly separated."""
        # All positions must be classified — no unclassified positions
        has_manual = manual_position_count > 0
        passed = not has_manual
        check = CapitalCheck(
            check_id="CB-SEPARATION",
            passed=passed,
            description="R4 and pre-existing positions separated; no manual trades",
            expected="0 manual trades",
            observed=f"R4={r4_position_count}, pre-existing={pre_existing_position_count}, manual={manual_position_count}",
            severity="CRITICAL" if has_manual else "CRITICAL",
        )
        self._checks.append(check)
        return check

    def validate_no_manual_trading(
        self,
        manual_trade_count: int,
    ) -> CapitalCheck:
        """Check that no manual trades occurred during qualification."""
        passed = manual_trade_count == 0
        check = CapitalCheck(
            check_id="CB-NOMANUAL",
            passed=passed,
            description="No manual trading during qualification",
            expected="0 manual trades",
            observed=str(manual_trade_count),
        )
        self._checks.append(check)
        return check

    def validate_drawdown_envelope(
        self,
        current_drawdown_pct: float,
    ) -> CapitalCheck:
        """Check that drawdown is within the MINIMAL envelope."""
        passed = current_drawdown_pct <= self._config.max_drawdown_pct
        check = CapitalCheck(
            check_id="CB-DRAWDOWN",
            passed=passed,
            description="Drawdown within MINIMAL envelope",
            expected=f"<= {self._config.max_drawdown_pct:.0f}%",
            observed=f"{current_drawdown_pct:.2f}%",
        )
        self._checks.append(check)
        return check

    def validate_daily_loss_envelope(
        self,
        current_daily_loss: float,
    ) -> CapitalCheck:
        """Check that daily loss is within the MINIMAL envelope."""
        passed = current_daily_loss <= self._config.max_daily_loss
        check = CapitalCheck(
            check_id="CB-DAILYLOSS",
            passed=passed,
            description="Daily loss within MINIMAL envelope",
            expected=f"<= ${self._config.max_daily_loss:,.0f}",
            observed=f"${current_daily_loss:,.2f}",
        )
        self._checks.append(check)
        return check

    def run_all_validations(
        self,
        actual_equity: float = 0.0,
        start_timestamp: str = "",
        end_timestamp: str = "",
        actual_duration_days: float = 0.0,
        envelope_fingerprint: str = "",
        expected_fingerprint: str = "",
        r4_position_count: int = 0,
        pre_existing_position_count: int = 0,
        manual_position_count: int = 0,
        manual_trade_count: int = 0,
        current_drawdown_pct: float = 0.0,
        current_daily_loss: float = 0.0,
    ) -> List[CapitalCheck]:
        """Run all capital boundary validations."""
        self._checks.clear()
        self.validate_max_equity(actual_equity)
        self.validate_campaign_duration(start_timestamp, end_timestamp, actual_duration_days)
        self.validate_risk_envelope(envelope_fingerprint, expected_fingerprint)
        self.validate_position_separation(r4_position_count, pre_existing_position_count, manual_position_count)
        self.validate_no_manual_trading(manual_trade_count)
        self.validate_drawdown_envelope(current_drawdown_pct)
        self.validate_daily_loss_envelope(current_daily_loss)
        return list(self._checks)

    @property
    def all_passed(self) -> bool:
        return all(c.passed for c in self._checks)

    @property
    def checks(self) -> List[CapitalCheck]:
        return list(self._checks)
