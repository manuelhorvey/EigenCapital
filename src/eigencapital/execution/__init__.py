"""Paper-Trading Execution Infrastructure.

Implements the complete paper-trading execution path:
    Order → PaperBroker → Fill → Position → Account → AccountReconciliation

Critical invariant: Paper-only boundary. No live broker connectivity.
"""

from eigencapital.execution.account import AccountSnapshot, AccountState
from eigencapital.execution.broker import PaperBroker
from eigencapital.execution.events import AuditEvent, AuditLog
from eigencapital.execution.position_manager import PositionManager

__all__ = [
    "AccountSnapshot",
    "AccountState",
    "AuditEvent",
    "AuditLog",
    "PaperBroker",
    "PositionManager",
]
