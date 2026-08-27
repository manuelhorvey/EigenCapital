"""ExecutionLedger — permanent record of all hypothesis executions.

The ledger ensures:
1. Every execution is permanently recorded
2. Failed/rejected experiments remain visible
3. Trial family accounting is preserved
4. Research history is auditable

The ledger is append-only. Records cannot be modified or deleted.
This prevents the "file drawer" problem where failed experiments
are silently discarded.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, List

from eigencapital.research.execution.record import ExecutionRecord, ExecutionStatus


@dataclass
class ExecutionLedger:
    """Append-only ledger of all hypothesis executions.

    The ledger is the permanent research record. Every execution —
    successful, failed, or rejected — is recorded and cannot be
    modified or deleted.
    """

    def __init__(self) -> None:
        self._records: Dict[str, ExecutionRecord] = {}
        self._insertion_order: List[str] = []

    def append(self, record: ExecutionRecord) -> None:
        """Append an execution record to the ledger.

        Raises:
            ValueError: If execution_id already exists
        """
        if record.execution_id in self._records:
            raise ValueError(f"Duplicate execution_id: {record.execution_id}. Ledger is append-only.")
        self._records[record.execution_id] = record
        self._insertion_order.append(record.execution_id)

    def get(self, execution_id: str) -> ExecutionRecord:
        """Get an execution record by ID."""
        if execution_id not in self._records:
            raise KeyError(f"Execution not found: {execution_id}")
        return self._records[execution_id]

    def list_all(self) -> List[ExecutionRecord]:
        """List all records in insertion order."""
        return [self._records[eid] for eid in self._insertion_order]

    def list_by_status(self, status: ExecutionStatus) -> List[ExecutionRecord]:
        """List records filtered by status."""
        return [r for r in self.list_all() if r.status == status]

    def list_by_hypothesis(self, hypothesis_id: str) -> List[ExecutionRecord]:
        """List all executions for a given hypothesis."""
        return [r for r in self.list_all() if r.hypothesis_id == hypothesis_id]

    def list_by_trial_group(self, trial_group_id: str) -> List[ExecutionRecord]:
        """List all executions in a given trial group."""
        return [r for r in self.list_all() if r.trial_group_id == trial_group_id]

    def summary(self) -> Dict[str, Any]:
        """Summary statistics of the ledger."""
        all_records = self.list_all()
        by_status: Dict[str, int] = {}
        for r in all_records:
            s = r.status.value
            by_status[s] = by_status.get(s, 0) + 1

        return {
            "total_executions": len(all_records),
            "by_status": by_status,
            "unique_hypotheses": len({r.hypothesis_id for r in all_records}),
            "unique_trial_groups": len({r.trial_group_id for r in all_records}),
        }

    def to_list(self) -> List[Dict[str, Any]]:
        """Serialize all records to a list of dicts."""
        return [r.to_dict() for r in self.list_all()]

    @classmethod
    def from_list(cls, data: List[Dict[str, Any]]) -> ExecutionLedger:
        """Deserialize from a list of dicts."""
        ledger = cls()
        for d in data:
            record = ExecutionRecord.from_dict(d)
            ledger.append(record)
        return ledger

    def __len__(self) -> int:
        return len(self._records)

    def __contains__(self, execution_id: str) -> bool:
        return execution_id in self._records
