"""Broker Boundary — validates broker configuration and prevents environment confusion.

Checks:
- Correct MT5 account/terminal
- Correct environment (demo vs live)
- Correct symbol mapping
- Correct contract specifications
- Correct volume/price constraints
- Spread/slippage controls
- No accidental demo/live confusion
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional


@dataclass(frozen=True)
class BrokerBoundaryConfig:
    """Expected broker configuration for the funded campaign."""

    expected_account_id: str = "436921728"
    expected_environment: str = "demo"  # Exness-MT5Trial9
    expected_broker: str = "exness"
    expected_platform: str = "mt5"
    expected_symbols: Dict[str, str] = field(default_factory=lambda: {
        "AUDUSD": "forex", "AUDCHF": "forex", "AUDCAD": "forex",
        "AUDNZD": "forex", "NZDUSD": "forex", "NZDCHF": "forex",
        "NZDCAD": "forex", "GBPUSD": "forex", "GBPCHF": "forex",
        "EURUSD": "forex", "EURCHF": "forex", "USDCHF": "forex",
        "USDCAD": "forex", "CADCHF": "forex", "EURGBP": "forex",
        "BTCUSD": "crypto",
    })
    max_spread: float = 0.0015
    max_slippage: float = 0.0008
    min_volume: float = 0.01
    max_volume: float = 1.0

    def compute_fingerprint(self) -> str:
        data = {
            "expected_account_id": self.expected_account_id,
            "expected_environment": self.expected_environment,
            "expected_broker": self.expected_broker,
            "expected_platform": self.expected_platform,
            "expected_symbols": dict(sorted(self.expected_symbols.items())),
            "max_spread": self.max_spread,
            "max_slippage": self.max_slippage,
            "min_volume": self.min_volume,
            "max_volume": self.max_volume,
        }
        payload = json.dumps(data, sort_keys=True).encode("utf-8")
        return hashlib.sha256(payload).hexdigest()


@dataclass(frozen=True)
class BrokerBoundaryCheck:
    """Result of a single broker boundary check."""

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


class BrokerBoundaryValidator:
    """Validates broker boundary before capital deployment.

    All checks are read-only — they inspect broker state
    and configuration without modifying anything.
    """

    def __init__(self, config: Optional[BrokerBoundaryConfig] = None) -> None:
        self._config = config or BrokerBoundaryConfig()
        self._checks: List[BrokerBoundaryCheck] = []

    def validate_account(
        self,
        actual_account_id: str,
        actual_broker: str = "",
        actual_platform: str = "",
    ) -> BrokerBoundaryCheck:
        """Check that the broker account matches the expected one."""
        passed = actual_account_id == self._config.expected_account_id
        check = BrokerBoundaryCheck(
            check_id="BB-ACCT",
            passed=passed,
            description="MT5 account matches expected",
            expected=self._config.expected_account_id,
            observed=actual_account_id,
        )
        self._checks.append(check)
        return check

    def validate_environment(
        self,
        actual_environment: str,
    ) -> BrokerBoundaryCheck:
        """Check that we're connected to the correct environment."""
        passed = actual_environment == self._config.expected_environment
        check = BrokerBoundaryCheck(
            check_id="BB-ENV",
            passed=passed,
            description="Environment matches expected (not demo/live confusion)",
            expected=self._config.expected_environment,
            observed=actual_environment,
        )
        self._checks.append(check)
        return check

    def validate_symbols(
        self,
        actual_symbols: List[str],
    ) -> BrokerBoundaryCheck:
        """Check that expected symbols are available."""
        expected_set = set(self._config.expected_symbols.keys())
        actual_set = set(actual_symbols)
        missing = expected_set - actual_set
        extra = actual_set - expected_set

        passed = len(missing) == 0
        detail = ""
        if missing:
            detail = f"Missing: {sorted(missing)}"
        if extra:
            detail += f" Extra: {sorted(extra)}" if detail else f"Extra: {sorted(extra)}"

        check = BrokerBoundaryCheck(
            check_id="BB-SYM",
            passed=passed,
            description="Symbol mapping correct",
            expected=f"{len(expected_set)} symbols",
            observed=f"{len(actual_set)} symbols; {detail}" if detail else f"{len(actual_set)} symbols",
        )
        self._checks.append(check)
        return check

    def validate_contract_specs(
        self,
        symbol_specs: Dict[str, Dict[str, Any]],
    ) -> BrokerBoundaryCheck:
        """Check that contract specifications are reasonable."""
        issues: List[str] = []
        for symbol, specs in symbol_specs.items():
            if symbol not in self._config.expected_symbols:
                continue
            # Check volume constraints
            min_vol = specs.get("volume_min", 0)
            max_vol = specs.get("volume_max", float("inf"))
            if min_vol > self._config.max_volume:
                issues.append(f"{symbol}: min volume {min_vol} > max allowed {self._config.max_volume}")
            if max_vol < self._config.min_volume:
                issues.append(f"{symbol}: max volume {max_vol} < min required {self._config.min_volume}")
            # Check digit precision (crypto=2, forex=4-5, indices=0-2)
            digits = specs.get("digits", 0)
            if digits < 2 or digits > 5:
                issues.append(f"{symbol}: unusual digit precision {digits}")

        passed = len(issues) == 0
        check = BrokerBoundaryCheck(
            check_id="BB-CONTRACT",
            passed=passed,
            description="Contract specifications correct",
            expected="all specs within bounds",
            observed="; ".join(issues) if issues else "all specs valid",
        )
        self._checks.append(check)
        return check

    def validate_volume_price_constraints(
        self,
        order_volume: float,
        order_price: float,
        symbol_spread: float = 0.0,
    ) -> BrokerBoundaryCheck:
        """Check that volume and price constraints are respected."""
        issues: List[str] = []
        if order_volume < self._config.min_volume:
            issues.append(f"Volume {order_volume} < min {self._config.min_volume}")
        if order_volume > self._config.max_volume:
            issues.append(f"Volume {order_volume} > max {self._config.max_volume}")
        if order_price <= 0:
            issues.append(f"Price {order_price} <= 0")

        passed = len(issues) == 0
        check = BrokerBoundaryCheck(
            check_id="BB-VOLPRICE",
            passed=passed,
            description="Volume/price constraints respected",
            expected=f"volume in [{self._config.min_volume}, {self._config.max_volume}], price > 0",
            observed="; ".join(issues) if issues else "constraints OK",
        )
        self._checks.append(check)
        return check

    def validate_spread_slippage(
        self,
        current_spread: float,
        current_slippage: float,
    ) -> BrokerBoundaryCheck:
        """Check that spread and slippage controls are active."""
        issues: List[str] = []
        if current_spread > self._config.max_spread:
            issues.append(f"Spread {current_spread:.6f} > max {self._config.max_spread:.6f}")
        if current_slippage > self._config.max_slippage:
            issues.append(f"Slippage {current_slippage:.6f} > max {self._config.max_slippage:.6f}")

        passed = len(issues) == 0
        check = BrokerBoundaryCheck(
            check_id="BB-SPREAD",
            passed=passed,
            description="Spread/slippage within bounds",
            expected=f"spread <= {self._config.max_spread}, slippage <= {self._config.max_slippage}",
            observed="; ".join(issues) if issues else "within bounds",
        )
        self._checks.append(check)
        return check

    def validate_no_environment_confusion(
        self,
        account_id: str,
        environment: str,
        broker_name: str,
    ) -> BrokerBoundaryCheck:
        """Final safety check: no demo/live confusion."""
        issues: List[str] = []
        if account_id != self._config.expected_account_id:
            issues.append(f"Wrong account: {account_id} != {self._config.expected_account_id}")
        if environment != self._config.expected_environment:
            issues.append(f"Wrong environment: {environment} != {self._config.expected_environment}")
        if broker_name and broker_name.lower() != self._config.expected_broker.lower():
            issues.append(f"Wrong broker: {broker_name} != {self._config.expected_broker}")

        passed = len(issues) == 0
        check = BrokerBoundaryCheck(
            check_id="BB-NOCONFUSION",
            passed=passed,
            description="No demo/live/environment confusion",
            expected="account, environment, broker all match",
            observed="; ".join(issues) if issues else "no confusion",
        )
        self._checks.append(check)
        return check

    def run_all_validations(
        self,
        account_id: str = "",
        environment: str = "",
        broker_name: str = "",
        platform: str = "",
        symbols: Optional[List[str]] = None,
        symbol_specs: Optional[Dict[str, Dict[str, Any]]] = None,
        order_volume: float = 0.1,
        order_price: float = 1.0,
        current_spread: float = 0.0,
        current_slippage: float = 0.0,
    ) -> List[BrokerBoundaryCheck]:
        """Run all broker boundary validations."""
        self._checks.clear()
        self.validate_account(account_id, broker_name, platform)
        self.validate_environment(environment)
        self.validate_symbols(symbols or [])
        if symbol_specs:
            self.validate_contract_specs(symbol_specs)
        self.validate_volume_price_constraints(order_volume, order_price)
        self.validate_spread_slippage(current_spread, current_slippage)
        self.validate_no_environment_confusion(account_id, environment, broker_name)
        return list(self._checks)

    @property
    def all_passed(self) -> bool:
        return all(c.passed for c in self._checks)

    @property
    def checks(self) -> List[BrokerBoundaryCheck]:
        return list(self._checks)
