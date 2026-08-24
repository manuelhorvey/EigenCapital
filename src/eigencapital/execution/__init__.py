"""Paper-Trading Execution Infrastructure.

Implements the complete paper-trading execution path:
    Order → PaperBroker → Fill → Position → Account → Reconciliation

Critical invariant: Paper-only boundary. No live broker connectivity.
"""

from eigencapital.execution.broker import PaperBroker
from eigencapital.execution.position_manager import PositionManager
from eigencapital.execution.account import AccountState, AccountSnapshot
from eigencapital.execution.reconciliation import ReconciliationEngine, ReconciliationStatus
from eigencapital.execution.events import AuditEvent, AuditLog

__all__ = [
    "PaperBroker",
    "PositionManager",
    "AccountState",
    "AccountSnapshot",
    "ReconciliationEngine",
    "ReconciliationStatus",
    "AuditEvent",
    "AuditLog",
]
