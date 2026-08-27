"""Phase 1U — Production Qualification.

Scaling fidelity from micro-live to meaningful capital.
Proves that the system remains safe at larger sizes.
"""

from eigencapital.production_qual.event_ledger import EventLedger, EventType, Event
from eigencapital.production_qual.live_qualification import (
    R4LiveQualificationDataset,
    QualificationTrade,
    ExecutionFidelity,
    EntryQuality,
    HoldingPeriodMetrics,
    DownsideMetrics,
    ExitReason,
)
from eigencapital.production_qual.evidence_maturity import (
    EvidenceMaturityTracker,
    EvidenceLevel,
)
from eigencapital.production_qual.phase2_report import Phase2ReportGenerator
from eigencapital.production_qual.fingerprint_verifier import FingerprintVerifier

__all__ = [
    "EventLedger",
    "EventType",
    "Event",
    "R4LiveQualificationDataset",
    "QualificationTrade",
    "ExecutionFidelity",
    "EntryQuality",
    "HoldingPeriodMetrics",
    "DownsideMetrics",
    "ExitReason",
    "EvidenceMaturityTracker",
    "EvidenceLevel",
    "Phase2ReportGenerator",
    "FingerprintVerifier",
]
