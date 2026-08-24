"""Hypothesis Execution Engine.

Orchestrates the complete research path:
    Hypothesis → Pre-registered Experiment → FeatureSet → Backtest → Validation → Evidence Gate

Critical invariant: The execution engine never invents research decisions.
It consumes pre-registered hypotheses and produces immutable execution records.
"""

from eigencapital.research.execution.engine import ExecutionEngine
from eigencapital.research.execution.record import ExecutionRecord, ExecutionStatus
from eigencapital.research.execution.ledger import ExecutionLedger

__all__ = [
    "ExecutionEngine",
    "ExecutionRecord",
    "ExecutionStatus",
    "ExecutionLedger",
]
