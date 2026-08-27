"""Reconciliation — canonical implementation in reconciliation.engine.

This package provides the production-grade reconciliation engine with
hostile condition detection and SAFE_AUTOFIX/REVIEW/HALT classification.

For backward compatibility, the paper-only execution.reconciliation is
still available but deprecated.
"""

from eigencapital.reconciliation.engine import (
    BrokerState,
    InternalState,
    ReconciliationAction,
    ReconciliationCheck,
    ReconciliationEngine,
    ReconciliationResult,
    ReconciliationSeverity,
)

__all__ = [
    "BrokerState",
    "InternalState",
    "ReconciliationAction",
    "ReconciliationCheck",
    "ReconciliationEngine",
    "ReconciliationResult",
    "ReconciliationSeverity",
]
