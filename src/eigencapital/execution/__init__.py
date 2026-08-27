"""Paper-Trading Execution Infrastructure.

Implements the complete paper-trading execution path:
    Order → PaperBroker → Fill → Position → Account → AccountReconciliation

Critical invariant: Paper-only boundary. No live broker connectivity.
"""

from eigencapital.execution.broker import PaperBroker
from eigencapital.execution.position_manager import PositionManager
from eigencapital.execution.account import AccountState, AccountSnapshot
from eigencapital.execution.events import AuditEvent, AuditLog

__all__ = [
    "PaperBroker",
    "PositionManager",
    "AccountState",
    "AccountSnapshot",
    "AuditEvent",
    "AuditLog",
]
