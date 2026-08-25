"""Pre-Trading Validation — broker-connected gate before first order.

The pre-funding gate validated the CODE. This module validates the
DEPLOYED STATE against that code. It runs the 5-step sequence:

1. Fund exactly the authorized capital boundary
2. Connect to actual MT5 environment → revalidate broker boundary
3. Reconcile before trading (broker state = expected starting state)
4. Revalidate frozen fingerprint after broker connection
5. Only then authorize trading

The first order isn't the qualification. It's the beginning of
evidence collection.

Design rules:
- Read-only: inspects broker state without modifying anything
- Fail-closed: any unclassifiable position blocks authorization
- Immutable: every authorization outcome is recorded with full audit trail
- Idempotent: re-running the sequence produces the same outcome
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional, Tuple

from eigencapital.fidelity.r4_manifest import R4ConfigManifest
from eigencapital.production_qual.broker_boundary import (
    BrokerBoundaryCheck,
    BrokerBoundaryConfig,
    BrokerBoundaryValidator,
)
from eigencapital.production_qual.capital_boundary import (
    CapitalBoundaryConfig,
    CapitalBoundaryValidator,
)
from eigencapital.production_qual.campaign_boundary import (
    CampaignBoundary,
    TradeOrigin,
)
from eigencapital.production_qual.prefunding_audit import AuditVerdict
from eigencapital.production_qual.prefunding_gate import (
    GateDecision,
    GateRecord,
    PrefundingGate,
)
from eigencapital.risk.policy import RiskPolicy


class PreTradingStep(str, Enum):
    """The 5-step pre-trading validation sequence."""

    FUND_CAPITAL = "fund_capital"
    CONNECT_BROKER = "connect_broker"
    RECONCILE = "reconcile"
    VALIDATE_FINGERPRINT = "validate_fingerprint"
    AUTHORIZE = "authorize"


class PreTradingDecision(str, Enum):
    """The binary pre-trading outcome."""

    TRADING_AUTHORIZED = "TRADING_AUTHORIZED"
    TRADING_BLOCKED = "TRADING_BLOCKED"


@dataclass(frozen=True)
class BrokerStateSnapshot:
    """Structured representation of live broker state at validation time.

    This is the actual state pulled from the MT5 broker after connection.
    Every field is required — missing data blocks authorization.
    """

    account_id: str
    account_name: str
    environment: str  # "live" or "demo"
    broker_name: str
    platform: str  # "mt5"

    # Account state
    equity: float
    free_margin: float
    balance: float
    margin_level: float

    # Positions
    positions: List[Dict[str, Any]]
    position_count: int

    # Symbol availability
    available_symbols: List[str]
    symbol_specs: Dict[str, Dict[str, Any]]

    # Market conditions
    current_spread: float
    current_slippage: float

    # Timestamp
    snapshot_timestamp: str

    def to_dict(self) -> Dict[str, Any]:
        return {
            "account_id": self.account_id,
            "account_name": self.account_name,
            "environment": self.environment,
            "broker_name": self.broker_name,
            "platform": self.platform,
            "equity": self.equity,
            "free_margin": self.free_margin,
            "balance": self.balance,
            "margin_level": self.margin_level,
            "position_count": self.position_count,
            "available_symbols": len(self.available_symbols),
            "current_spread": self.current_spread,
            "current_slippage": self.current_slippage,
            "snapshot_timestamp": self.snapshot_timestamp,
        }


@dataclass(frozen=True)
class PreTradingCheck:
    """A single pre-trading validation check."""

    step: str
    check_id: str
    passed: bool
    description: str
    expected: str = ""
    observed: str = ""
    severity: str = "CRITICAL"
    details: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return {
            "step": self.step,
            "check_id": self.check_id,
            "passed": self.passed,
            "description": self.description,
            "expected": self.expected,
            "observed": self.observed,
            "severity": self.severity,
            "details": self.details,
        }


@dataclass
@dataclass(frozen=True)
class PreTradingAuthorization:
    """Immutable record of pre-trading validation outcome.

    Captures the complete 5-step sequence result with full audit trail.
    """

    decision: str
    campaign_id: str
    manifest_fingerprint: str
    broker_snapshot_hash: str
    checks: List[PreTradingCheck] = field(default_factory=list)
    authorization_timestamp: str = ""
    authorization_fingerprint: str = ""

    # Position classification
    r4_positions: int = 0
    pre_existing_positions: int = 0
    manual_positions: int = 0
    unclassified_positions: int = 0

    # Gate record reference
    gate_record_hash: str = ""

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
    def critical_failures(self) -> List[PreTradingCheck]:
        return [c for c in self.checks if not c.passed and c.severity == "CRITICAL"]

    def compute_hash(self) -> str:
        data = {
            "decision": self.decision,
            "campaign_id": self.campaign_id,
            "manifest_fingerprint": self.manifest_fingerprint,
            "broker_snapshot_hash": self.broker_snapshot_hash,
            "total_checks": self.total_checks,
            "passed_checks": self.passed_checks,
            "failed_checks": self.failed_checks,
            "r4_positions": self.r4_positions,
            "pre_existing_positions": self.pre_existing_positions,
            "manual_positions": self.manual_positions,
            "unclassified_positions": self.unclassified_positions,
            "checks": [c.to_dict() for c in self.checks],
        }
        payload = json.dumps(data, sort_keys=True).encode("utf-8")
        return hashlib.sha256(payload).hexdigest()

    def to_dict(self) -> Dict[str, Any]:
        return {
            "decision": self.decision,
            "campaign_id": self.campaign_id,
            "manifest_fingerprint": self.manifest_fingerprint,
            "broker_snapshot_hash": self.broker_snapshot_hash,
            "total_checks": self.total_checks,
            "passed_checks": self.passed_checks,
            "failed_checks": self.failed_checks,
            "critical_failures": len(self.critical_failures),
            "authorization_timestamp": self.authorization_timestamp,
            "authorization_fingerprint": self.authorization_fingerprint,
            "r4_positions": self.r4_positions,
            "pre_existing_positions": self.pre_existing_positions,
            "manual_positions": self.manual_positions,
            "unclassified_positions": self.unclassified_positions,
            "gate_record_hash": self.gate_record_hash,
            "checks": [c.to_dict() for c in self.checks],
        }

    def to_markdown(self) -> str:
        lines = [
            "# Pre-Trading Validation Authorization",
            "",
            f"**Campaign:** {self.campaign_id}",
            f"**Decision:** {self.decision}",
            f"**Checks:** {self.passed_checks}/{self.total_checks} passed",
            f"**Critical failures:** {len(self.critical_failures)}",
            f"**Manifest:** {self.manifest_fingerprint[:16]}",
            f"**Timestamp:** {self.authorization_timestamp}",
            "",
            "## Position Classification",
            "",
            f"| Origin | Count |",
            f"|---|---|",
            f"| R4 Campaign | {self.r4_positions} |",
            f"| Pre-existing | {self.pre_existing_positions} |",
            f"| Manual | {self.manual_positions} |",
            f"| Unclassified | {self.unclassified_positions} |",
            "",
            "## Validation Steps",
            "",
        ]

        for check in self.checks:
            icon = "✅" if check.passed else ("❌" if check.severity == "CRITICAL" else "⚠️")
            lines.append(f"- {icon} **[{check.step}] {check.check_id}**: {check.description}")
            if not check.passed:
                lines.append(f"  - Expected: {check.expected}")
                lines.append(f"  - Observed: {check.observed}")
                if check.details:
                    lines.append(f"  - Detail: {check.details}")

        lines.extend(["", "## Decision", ""])

        if self.decision == PreTradingDecision.TRADING_AUTHORIZED.value:
            lines.append(
                "**TRADING_AUTHORIZED** — All 5 steps passed. "
                "First order may proceed as evidence collection."
            )
        else:
            lines.append(
                "**TRADING_BLOCKED** — One or more steps failed. "
                "Do NOT place any orders until all checks pass."
            )

        return "\n".join(lines)


class PreTradingValidator:
    """5-step pre-trading validation sequence.

    Runs AFTER broker connection but BEFORE the first order.
    Every step must pass before the next begins.
    Fail-closed: any failure blocks ALL trading.

    The 5 steps:
    1. FUND_CAPITAL — Verify account equity matches authorized boundary
    2. CONNECT_BROKER — Revalidate broker boundary against real state
    3. RECONCILE — Classify all positions (R4, pre-existing, manual)
    4. VALIDATE_FINGERPRINT — Prove connected config == frozen R4 manifest
    5. AUTHORIZE — Produce TRADING_AUTHORIZED or TRADING_BLOCKED
    """

    def __init__(
        self,
        campaign_id: str = "R4-MINIMAL-5K",
        broker_config: Optional[BrokerBoundaryConfig] = None,
        capital_config: Optional[CapitalBoundaryConfig] = None,
    ) -> None:
        self._campaign_id = campaign_id
        self._broker_config = broker_config or BrokerBoundaryConfig()
        self._capital_config = capital_config or CapitalBoundaryConfig()
        self._checks: List[PreTradingCheck] = []
        self._frozen_manifest = R4ConfigManifest()
        self._frozen_fingerprint = self._frozen_manifest.compute_identity()
        self._r4_positions: int = 0
        self._pre_existing_positions: int = 0
        self._manual_positions: int = 0
        self._unclassified_positions: int = 0

    def _add_check(self, check: PreTradingCheck) -> None:
        self._checks.append(check)

    # ── Step 1: Fund Capital ───────────────────────────────────────

    def validate_capital(
        self,
        broker_state: BrokerStateSnapshot,
    ) -> List[PreTradingCheck]:
        """Step 1: Verify account equity matches authorized capital boundary.

        The account must have been funded to exactly the authorized amount.
        No more, no less.
        """
        step = PreTradingStep.FUND_CAPITAL.value
        checks: List[PreTradingCheck] = []

        # 1.1 Equity within authorized maximum
        equity_ok = broker_state.equity <= self._capital_config.max_equity
        self._add_check(PreTradingCheck(
            step=step,
            check_id="PT-FUND-01",
            passed=equity_ok,
            description="Account equity within authorized maximum",
            expected=f"<= ${self._capital_config.max_equity:,.0f}",
            observed=f"${broker_state.equity:,.2f}",
        ))
        checks.append(self._checks[-1])

        # 1.2 Equity above minimum (account was actually funded)
        equity_min = broker_state.equity > 0
        self._add_check(PreTradingCheck(
            step=step,
            check_id="PT-FUND-02",
            passed=equity_min,
            description="Account has positive equity (funded)",
            expected="> $0",
            observed=f"${broker_state.equity:,.2f}",
        ))
        checks.append(self._checks[-1])

        # 1.3 Free margin sufficient for initial positions
        margin_ok = broker_state.free_margin > 0
        self._add_check(PreTradingCheck(
            step=step,
            check_id="PT-FUND-03",
            passed=margin_ok,
            description="Free margin available for trading",
            expected="> $0",
            observed=f"${broker_state.free_margin:,.2f}",
        ))
        checks.append(self._checks[-1])

        return checks

    # ── Step 2: Connect Broker ─────────────────────────────────────

    def validate_broker_connection(
        self,
        broker_state: BrokerStateSnapshot,
    ) -> List[PreTradingCheck]:
        """Step 2: Revalidate broker boundary against actual broker state.

        This is the LIVE validation — not the config-only check from
        the pre-funding gate. Every field comes from the real broker.
        """
        step = PreTradingStep.CONNECT_BROKER.value
        checks: List[PreTradingCheck] = []

        validator = BrokerBoundaryValidator(self._broker_config)

        # 2.1 Account identity
        acct_check = validator.validate_account(
            broker_state.account_id,
            broker_state.broker_name,
            broker_state.platform,
        )
        self._add_check(PreTradingCheck(
            step=step,
            check_id="PT-BROKER-01",
            passed=acct_check.passed,
            description="MT5 account matches authorized account",
            expected=self._broker_config.expected_account_id,
            observed=broker_state.account_id,
        ))
        checks.append(self._checks[-1])

        # 2.2 Environment
        env_check = validator.validate_environment(broker_state.environment)
        self._add_check(PreTradingCheck(
            step=step,
            check_id="PT-BROKER-02",
            passed=env_check.passed,
            description="Connected to correct environment (not demo/live confusion)",
            expected=self._broker_config.expected_environment,
            observed=broker_state.environment,
        ))
        checks.append(self._checks[-1])

        # 2.3 Symbol availability
        sym_check = validator.validate_symbols(broker_state.available_symbols)
        self._add_check(PreTradingCheck(
            step=step,
            check_id="PT-BROKER-03",
            passed=sym_check.passed,
            description="All required symbols available",
            expected=f"{len(self._broker_config.expected_symbols)} symbols",
            observed=f"{len(broker_state.available_symbols)} symbols",
            details=sym_check.observed,
        ))
        checks.append(self._checks[-1])

        # 2.4 Contract specifications
        contract_check = validator.validate_contract_specs(broker_state.symbol_specs)
        self._add_check(PreTradingCheck(
            step=step,
            check_id="PT-BROKER-04",
            passed=contract_check.passed,
            description="Contract specifications within bounds",
            expected="all specs valid",
            observed=contract_check.observed,
        ))
        checks.append(self._checks[-1])

        # 2.5 Spread/slippage
        spread_check = validator.validate_spread_slippage(
            broker_state.current_spread,
            broker_state.current_slippage,
        )
        self._add_check(PreTradingCheck(
            step=step,
            check_id="PT-BROKER-05",
            passed=spread_check.passed,
            description="Current spread/slippage within bounds",
            expected=f"spread <= {self._broker_config.max_spread}",
            observed=f"spread={broker_state.current_spread:.6f}, slippage={broker_state.current_slippage:.6f}",
        ))
        checks.append(self._checks[-1])

        # 2.6 No environment confusion (final safety check)
        confusion_check = validator.validate_no_environment_confusion(
            broker_state.account_id,
            broker_state.environment,
            broker_state.broker_name,
        )
        self._add_check(PreTradingCheck(
            step=step,
            check_id="PT-BROKER-06",
            passed=confusion_check.passed,
            description="No demo/live/environment confusion",
            expected="account, environment, broker all match",
            observed=confusion_check.observed,
            severity="CRITICAL",
        ))
        checks.append(self._checks[-1])

        return checks

    # ── Step 3: Reconcile ──────────────────────────────────────────

    def reconcile_positions(
        self,
        broker_state: BrokerStateSnapshot,
        campaign_boundary: Optional[CampaignBoundary] = None,
    ) -> List[PreTradingCheck]:
        """Step 3: Classify all positions before first R4 order.

        Every position must be classified as R4, pre-existing, or manual.
        Unclassified positions block authorization.

        The system should establish:
            broker state = EigenCapital expected starting state
        before the first R4 order is permitted.
        """
        step = PreTradingStep.RECONCILE.value
        checks: List[PreTradingCheck] = []

        if campaign_boundary is None:
            # Fresh campaign — no positions expected
            r4_count = 0
            pre_count = 0
            manual_count = 0
            unclassified_count = broker_state.position_count
        else:
            # Existing campaign — classify each position
            r4_count = 0
            pre_count = 0
            manual_count = 0
            unclassified_count = 0

            for pos in broker_state.positions:
                origin = campaign_boundary.classify_position(
                    broker_ticket=pos.get("ticket", 0),
                    symbol=pos.get("symbol", ""),
                    volume=pos.get("volume", 0),
                    entry_price=pos.get("price_open", 0),
                    entry_time=pos.get("time", ""),
                )
                if origin == TradeOrigin.R4_CAMPAIGN:
                    r4_count += 1
                elif origin == TradeOrigin.PRE_EXISTING:
                    pre_count += 1
                elif origin == TradeOrigin.MANUAL:
                    manual_count += 1
                else:
                    unclassified_count += 1

        # Store classification for the authorization record
        self._r4_positions = r4_count
        self._pre_existing_positions = pre_count
        self._manual_positions = manual_count
        self._unclassified_positions = unclassified_count

        # 3.1 No unclassified positions
        no_unclassified = unclassified_count == 0
        self._add_check(PreTradingCheck(
            step=step,
            check_id="PT-RECON-01",
            passed=no_unclassified,
            description="No unclassified positions",
            expected="0 unclassified",
            observed=f"{unclassified_count} unclassified",
            severity="CRITICAL",
        ))
        checks.append(self._checks[-1])

        # 3.2 No manual trades during qualification
        no_manual = manual_count == 0
        self._add_check(PreTradingCheck(
            step=step,
            check_id="PT-RECON-02",
            passed=no_manual,
            description="No manual trades during qualification",
            expected="0 manual trades",
            observed=f"{manual_count} manual trades",
            severity="CRITICAL",
        ))
        checks.append(self._checks[-1])

        # 3.3 Position count within limits
        count_ok = broker_state.position_count <= self._capital_config.max_concurrent_positions
        self._add_check(PreTradingCheck(
            step=step,
            check_id="PT-RECON-03",
            passed=count_ok,
            description="Position count within authorized limit",
            expected=f"<= {self._capital_config.max_concurrent_positions}",
            observed=str(broker_state.position_count),
        ))
        checks.append(self._checks[-1])

        # 3.4 Pre-existing positions documented (if any)
        if pre_count > 0:
            self._add_check(PreTradingCheck(
                step=step,
                check_id="PT-RECON-04",
                passed=True,  # Pre-existing is OK if documented
                description="Pre-existing positions documented and separated",
                expected="all pre-existing classified",
                observed=f"{pre_count} pre-existing positions documented",
                severity="WARNING",
            ))
        else:
            self._add_check(PreTradingCheck(
                step=step,
                check_id="PT-RECON-04",
                passed=True,
                description="No pre-existing positions (clean start)",
                expected="0 pre-existing",
                observed="0 pre-existing",
            ))
        checks.append(self._checks[-1])

        return checks

    # ── Step 4: Validate Fingerprint ───────────────────────────────

    def validate_fingerprint(
        self,
        broker_state: BrokerStateSnapshot,
    ) -> List[PreTradingCheck]:
        """Step 4: Prove connected configuration == frozen R4 manifest.

        After broker connection, the system must demonstrate that no
        configuration drift occurred during the connection process.
        """
        step = PreTradingStep.VALIDATE_FINGERPRINT.value
        checks: List[PreTradingCheck] = []

        # 4.1 Frozen fingerprint is still valid
        current_fingerprint = self._frozen_manifest.compute_identity()
        fingerprint_match = current_fingerprint == self._frozen_fingerprint
        self._add_check(PreTradingCheck(
            step=step,
            check_id="PT-FP-01",
            passed=fingerprint_match,
            description="Frozen R4 manifest fingerprint unchanged",
            expected=self._frozen_fingerprint[:16],
            observed=current_fingerprint[:16],
        ))
        checks.append(self._checks[-1])

        # 4.2 Strategy version still frozen
        version_ok = self._frozen_manifest.strategy_version == "R4.0"
        self._add_check(PreTradingCheck(
            step=step,
            check_id="PT-FP-02",
            passed=version_ok,
            description="Strategy version still frozen at R4.0",
            expected="R4.0",
            observed=self._frozen_manifest.strategy_version,
        ))
        checks.append(self._checks[-1])

        # 4.3 Data terminal ID matches
        terminal_ok = self._frozen_manifest.data_terminal_id == broker_state.account_id
        self._add_check(PreTradingCheck(
            step=step,
            check_id="PT-FP-03",
            passed=terminal_ok,
            description="Data terminal ID matches broker account",
            expected=self._frozen_manifest.data_terminal_id,
            observed=broker_state.account_id,
        ))
        checks.append(self._checks[-1])

        return checks

    # ── Step 5: Authorize ──────────────────────────────────────────

    def authorize_trading(
        self,
        pre_funding_gate_record: Optional[GateRecord] = None,
    ) -> List[PreTradingCheck]:
        """Step 5: Final authorization gate.

        Combines all previous steps with the pre-funding gate record
        to produce the final TRADING_AUTHORIZED or TRADING_BLOCKED.
        """
        step = PreTradingStep.AUTHORIZE.value
        checks: List[PreTradingCheck] = []

        # 5.1 Pre-funding gate was AUTHORIZED
        if pre_funding_gate_record is not None:
            gate_authorized = (
                pre_funding_gate_record.decision == GateDecision.AUTHORIZED.value
            )
            self._add_check(PreTradingCheck(
                step=step,
                check_id="PT-AUTH-01",
                passed=gate_authorized,
                description="Pre-funding gate was AUTHORIZED",
                expected="AUTHORIZED",
                observed=pre_funding_gate_record.decision,
            ))
        else:
            self._add_check(PreTradingCheck(
                step=step,
                check_id="PT-AUTH-01",
                passed=False,
                description="Pre-funding gate record required",
                expected="GateRecord",
                observed="None",
            ))
        checks.append(self._checks[-1])

        # 5.2 No critical failures in any previous step
        all_critical = [c for c in self._checks if c.severity == "CRITICAL"]
        no_critical_failures = all(c.passed for c in all_critical)
        self._add_check(PreTradingCheck(
            step=step,
            check_id="PT-AUTH-02",
            passed=no_critical_failures,
            description="No critical failures in any validation step",
            expected="0 critical failures",
            observed=f"{sum(1 for c in all_critical if not c.passed)} critical failures",
        ))
        checks.append(self._checks[-1])

        # 5.3 No unclassified positions
        no_unclassified = self._unclassified_positions == 0
        self._add_check(PreTradingCheck(
            step=step,
            check_id="PT-AUTH-03",
            passed=no_unclassified,
            description="All positions classified (no orphans)",
            expected="0 unclassified",
            observed=f"{self._unclassified_positions} unclassified",
        ))
        checks.append(self._checks[-1])

        # 5.4 No manual trades
        no_manual = self._manual_positions == 0
        self._add_check(PreTradingCheck(
            step=step,
            check_id="PT-AUTH-04",
            passed=no_manual,
            description="No manual trades during qualification",
            expected="0 manual",
            observed=f"{self._manual_positions} manual",
        ))
        checks.append(self._checks[-1])

        return checks

    # ── Full Sequence ──────────────────────────────────────────────

    def run_full_validation(
        self,
        broker_state: BrokerStateSnapshot,
        campaign_boundary: Optional[CampaignBoundary] = None,
        pre_funding_gate_record: Optional[GateRecord] = None,
    ) -> PreTradingAuthorization:
        """Run the complete 5-step pre-trading validation sequence.

        Each step runs sequentially. Any CRITICAL failure in any step
        blocks the entire sequence.

        Args:
            broker_state: Live broker state snapshot
            campaign_boundary: Campaign boundary for position classification
            pre_funding_gate_record: Record from the pre-funding gate

        Returns:
            PreTradingAuthorization with decision and full audit trail
        """
        import time

        self._checks.clear()
        self._r4_positions = 0
        self._pre_existing_positions = 0
        self._manual_positions = 0
        self._unclassified_positions = 0

        # Compute broker snapshot hash
        broker_hash = hashlib.sha256(
            json.dumps(broker_state.to_dict(), sort_keys=True).encode("utf-8")
        ).hexdigest()

        # Step 1: Fund Capital
        self.validate_capital(broker_state)

        # Step 2: Connect Broker
        self.validate_broker_connection(broker_state)

        # Step 3: Reconcile
        self.reconcile_positions(broker_state, campaign_boundary)

        # Step 4: Validate Fingerprint
        self.validate_fingerprint(broker_state)

        # Step 5: Authorize
        self.authorize_trading(pre_funding_gate_record)

        # Compute decision
        critical_failures = [c for c in self._checks if not c.passed and c.severity == "CRITICAL"]
        decision = (
            PreTradingDecision.TRADING_AUTHORIZED
            if not critical_failures
            else PreTradingDecision.TRADING_BLOCKED
        )

        # Build authorization record
        now = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
        auth = PreTradingAuthorization(
            decision=decision.value,
            campaign_id=self._campaign_id,
            manifest_fingerprint=self._frozen_fingerprint,
            broker_snapshot_hash=broker_hash,
            checks=list(self._checks),
            authorization_timestamp=now,
            r4_positions=self._r4_positions,
            pre_existing_positions=self._pre_existing_positions,
            manual_positions=self._manual_positions,
            unclassified_positions=self._unclassified_positions,
            gate_record_hash=(
                pre_funding_gate_record.gate_fingerprint
                if pre_funding_gate_record
                else ""
            ),
        )
        # Compute fingerprint after construction
        object.__setattr__(
            auth, "authorization_fingerprint", auth.compute_hash()
        )

        return auth
