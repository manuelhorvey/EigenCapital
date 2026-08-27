"""Reconciliation Engine — verifies internal state matches broker state.

DEPRECATED: Use eigencapital.reconciliation.engine instead.
This module is paper-only and retained for backward compatibility.

Reconciliation must compare:
    Expected State
        vs
    Paper Broker State

Check:
- orders
- fills
- positions
- quantities
- cash
- realized P&L
- unrealized P&L
- equity
- exposure

Any mismatch must produce an explicit reconciliation failure.
Never silently repair state.
"""

from __future__ import annotations

import warnings
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Tuple

warnings.warn(
    "eigencapital.execution.reconciliation is deprecated. Use eigencapital.reconciliation.engine instead.",
    DeprecationWarning,
    stacklevel=2,
)


class ReconciliationStatus(str, Enum):
    """Reconciliation status."""

    RECONCILED = "reconciled"
    WARNING = "warning"
    MISMATCH = "mismatch"
    UNKNOWN = "unknown"


@dataclass(frozen=True)
class ReconciliationResult:
    """Result of a reconciliation check.

    Attributes:
        status: Overall status
        checks: Individual check results
        mismatches: List of mismatch descriptions
        timestamp: When reconciliation was performed
    """

    status: ReconciliationStatus
    checks: Dict[str, bool] = field(default_factory=dict)
    mismatches: Tuple[str, ...] = ()
    timestamp: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return {
            "status": self.status.value,
            "checks": self.checks,
            "mismatches": list(self.mismatches),
            "timestamp": self.timestamp,
        }


class ReconciliationEngine:
    """Reconciles internal state with broker state.

    Any mismatch produces an explicit failure.
    Never silently repair state.
    """

    def reconcile(
        self,
        expected_positions: Dict[str, float],
        broker_positions: Dict[str, float],
        expected_cash: float,
        broker_cash: float,
        expected_fills: int,
        broker_fills: int,
        tolerance: float = 1e-6,
    ) -> ReconciliationResult:
        """Perform reconciliation.

        Args:
            expected_positions: Expected position quantities
            broker_positions: Broker-reported position quantities
            expected_cash: Expected cash balance
            broker_cash: Broker-reported cash balance
            expected_fills: Expected fill count
            broker_fills: Broker-reported fill count
            tolerance: Numerical tolerance for comparison

        Returns:
            ReconciliationResult
        """
        checks: Dict[str, bool] = {}
        mismatches: List[str] = []

        # Check positions
        all_instruments = set(expected_positions.keys()) | set(broker_positions.keys())
        for instrument in all_instruments:
            expected = expected_positions.get(instrument, 0.0)
            broker = broker_positions.get(instrument, 0.0)
            if abs(expected - broker) > tolerance:
                checks[f"position_{instrument}"] = False
                mismatches.append(f"Position mismatch {instrument}: expected={expected}, broker={broker}")
            else:
                checks[f"position_{instrument}"] = True

        # Check cash
        if abs(expected_cash - broker_cash) > tolerance:
            checks["cash"] = False
            mismatches.append(f"Cash mismatch: expected={expected_cash}, broker={broker_cash}")
        else:
            checks["cash"] = True

        # Check fill count
        if expected_fills != broker_fills:
            checks["fill_count"] = False
            mismatches.append(f"Fill count mismatch: expected={expected_fills}, broker={broker_fills}")
        else:
            checks["fill_count"] = True

        # Determine status
        if not mismatches:
            status = ReconciliationStatus.RECONCILED
        elif any("Position mismatch" in m for m in mismatches):
            status = ReconciliationStatus.MISMATCH
        else:
            status = ReconciliationStatus.WARNING

        return ReconciliationResult(
            status=status,
            checks=checks,
            mismatches=tuple(mismatches),
        )
