"""Pre-Funding Gate — hard enforcement of GO/RESTRICTED/NO-GO verdict.

The gate is the final arbiter: it reads an AuditReport and either
authorizes capital deployment or blocks it.  It never mutates the
report; it only makes the binary decision and records the outcome.
"""

from __future__ import annotations

import hashlib
import json
import time
from dataclasses import dataclass
from enum import Enum
from typing import Any, Dict, List, Optional, Tuple

from eigencapital.production_qual.prefunding_audit import (
    AuditReport,
    AuditVerdict,
)


class GateDecision(str, Enum):
    """The binary gate output."""

    AUTHORIZED = "AUTHORIZED"
    BLOCKED = "BLOCKED"


@dataclass(frozen=True)
class GateRecord:
    """Immutable record of a gate decision."""

    decision: str
    campaign_id: str
    verdict: str
    report_hash: str
    decision_timestamp: str
    total_checks: int
    passed_checks: int
    critical_failures: int
    gate_fingerprint: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return {
            "decision": self.decision,
            "campaign_id": self.campaign_id,
            "verdict": self.verdict,
            "report_hash": self.report_hash,
            "decision_timestamp": self.decision_timestamp,
            "total_checks": self.total_checks,
            "passed_checks": self.passed_checks,
            "critical_failures": self.critical_failures,
            "gate_fingerprint": self.gate_fingerprint,
        }

    def compute_fingerprint(self) -> str:
        data = self.to_dict()
        payload = json.dumps(data, sort_keys=True).encode("utf-8")
        return hashlib.sha256(payload).hexdigest()


class PrefundingGate:
    """Enforcement gate: reads AuditReport → decides AUTHORIZED or BLOCKED.

    Rules:
    - GO verdict → AUTHORIZED
    - RESTRICTED verdict → AUTHORIZED (with documented constraints)
    - NO-GO verdict → BLOCKED

    The gate records every decision as an immutable GateRecord.
    """

    def __init__(self) -> None:
        self._records: List[GateRecord] = []

    def evaluate(self, report: AuditReport) -> Tuple[GateDecision, GateRecord]:
        """Evaluate an audit report and produce a gate decision."""
        now = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())

        if report.verdict == AuditVerdict.NO_GO:
            decision = GateDecision.BLOCKED
        else:
            decision = GateDecision.AUTHORIZED

        record = GateRecord(
            decision=decision.value,
            campaign_id=report.campaign_id,
            verdict=report.verdict.value,
            report_hash=report.report_hash,
            decision_timestamp=now,
            total_checks=report.total_checks,
            passed_checks=report.passed_checks,
            critical_failures=len(report.critical_failures),
        )
        # Compute fingerprint after construction
        object.__setattr__(record, "gate_fingerprint", record.compute_fingerprint())

        self._records.append(record)
        return decision, record

    def is_authorized(self, campaign_id: str) -> bool:
        """Check if the most recent decision for a campaign is AUTHORIZED."""
        for record in reversed(self._records):
            if record.campaign_id == campaign_id:
                return record.decision == GateDecision.AUTHORIZED.value
        return False

    def get_records(self) -> List[GateRecord]:
        return list(self._records)

    def get_record(self, campaign_id: str) -> Optional[GateRecord]:
        for record in reversed(self._records):
            if record.campaign_id == campaign_id:
                return record
        return None
