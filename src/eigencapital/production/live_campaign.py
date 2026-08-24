"""Live Campaign Engine — orchestrates controlled live campaigns.

Campaign lifecycle:
PLANNED → CONNECTIVITY → MINIMAL_EXPOSURE → EXTENDED_OBSERVATION → QUALIFICATION → COMPLETED/FAILED

Records:
- campaign identity
- production fingerprint
- execution evidence
- divergence tracking
- risk-boundary verification
- reconciliation evidence
- qualification verdict
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from enum import Enum
from typing import Dict, List, Optional, Any

from eigencapital.production.fingerprint import ProductionFingerprint
from eigencapital.production.evidence import (
    ExecutionEvidenceCollector,
    ExecutionSummary,
)


class LiveCampaignStatus(str, Enum):
    """Live campaign lifecycle."""

    PLANNED = "planned"
    CONNECTIVITY = "connectivity"
    MINIMAL_EXPOSURE = "minimal_exposure"
    EXTENDED_OBSERVATION = "extended_observation"
    QUALIFICATION = "qualification"
    COMPLETED = "completed"
    FAILED = "failed"
    STOPPED = "stopped"


# Valid state transitions
_VALID_LIVE_TRANSITIONS: Dict[str, List[str]] = {
    LiveCampaignStatus.PLANNED.value: [
        LiveCampaignStatus.CONNECTIVITY.value,
        LiveCampaignStatus.FAILED.value,
    ],
    LiveCampaignStatus.CONNECTIVITY.value: [
        LiveCampaignStatus.MINIMAL_EXPOSURE.value,
        LiveCampaignStatus.FAILED.value,
        LiveCampaignStatus.STOPPED.value,
    ],
    LiveCampaignStatus.MINIMAL_EXPOSURE.value: [
        LiveCampaignStatus.EXTENDED_OBSERVATION.value,
        LiveCampaignStatus.FAILED.value,
        LiveCampaignStatus.STOPPED.value,
    ],
    LiveCampaignStatus.EXTENDED_OBSERVATION.value: [
        LiveCampaignStatus.QUALIFICATION.value,
        LiveCampaignStatus.FAILED.value,
        LiveCampaignStatus.STOPPED.value,
    ],
    LiveCampaignStatus.QUALIFICATION.value: [
        LiveCampaignStatus.COMPLETED.value,
        LiveCampaignStatus.FAILED.value,
    ],
    LiveCampaignStatus.COMPLETED.value: [],
    LiveCampaignStatus.FAILED.value: [],
    LiveCampaignStatus.STOPPED.value: [],
}


@dataclass(frozen=True)
class LiveCampaign:
    """Immutable live campaign identity with frozen production fingerprint."""

    campaign_id: str
    production_fingerprint: ProductionFingerprint
    authorization_id: str
    max_capital: float
    max_drawdown: float
    start_timestamp: str
    expiry_timestamp: str
    strategy_id: str = ""
    portfolio_id: str = ""
    broker_identity: str = ""
    account_identity: str = ""
    status: str = LiveCampaignStatus.PLANNED.value
    status_history: tuple = ()
    campaign_fingerprint: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return {
            "campaign_id": self.campaign_id,
            "production_fingerprint": self.production_fingerprint.to_dict(),
            "authorization_id": self.authorization_id,
            "max_capital": self.max_capital,
            "max_drawdown": self.max_drawdown,
            "start_timestamp": self.start_timestamp,
            "expiry_timestamp": self.expiry_timestamp,
            "strategy_id": self.strategy_id,
            "portfolio_id": self.portfolio_id,
            "broker_identity": self.broker_identity,
            "account_identity": self.account_identity,
            "status": self.status,
        }

    def compute_fingerprint(self) -> str:
        data = self.to_dict()
        payload = json.dumps(data, sort_keys=True).encode("utf-8")
        return hashlib.sha256(payload).hexdigest()

    def can_transition_to(self, new_status: str) -> bool:
        valid_targets = _VALID_LIVE_TRANSITIONS.get(self.status, [])
        return new_status in valid_targets


@dataclass(frozen=True)
class LiveCampaignResult:
    """Result of a completed live campaign."""

    campaign_id: str
    production_fingerprint: ProductionFingerprint
    execution_summary: ExecutionSummary
    total_divergences: int
    critical_divergences: int
    risk_boundary_violations: int
    reconciliation_failures: int
    kill_switch_activations: int
    qualification_passed: bool
    verdict: str  # LIVE_BLOCKED, LIVE_INCONCLUSIVE, LIVE_QUALIFIED, LIVE_QUALIFIED_WITH_RESTRICTIONS
    evidence_completeness: float
    restrictions: tuple = ()
    qualification_notes: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return {
            "campaign_id": self.campaign_id,
            "production_fingerprint": self.production_fingerprint.to_dict(),
            "execution_summary": self.execution_summary.to_dict(),
            "total_divergences": self.total_divergences,
            "critical_divergences": self.critical_divergences,
            "risk_boundary_violations": self.risk_boundary_violations,
            "reconciliation_failures": self.reconciliation_failures,
            "kill_switch_activations": self.kill_switch_activations,
            "qualification_passed": self.qualification_passed,
            "verdict": self.verdict,
            "evidence_completeness": self.evidence_completeness,
            "restrictions": list(self.restrictions),
            "qualification_notes": self.qualification_notes,
        }

    def compute_fingerprint(self) -> str:
        data = self.to_dict()
        payload = json.dumps(data, sort_keys=True).encode("utf-8")
        return hashlib.sha256(payload).hexdigest()


class LiveCampaignEngine:
    """Manages live campaign lifecycle and evidence collection."""

    def __init__(self) -> None:
        self._campaigns: Dict[str, LiveCampaign] = {}
        self._evidence_collectors: Dict[str, ExecutionEvidenceCollector] = {}
        self._divergence_counts: Dict[str, Dict[str, int]] = {}
        self._risk_violations: Dict[str, int] = {}
        self._reconciliation_failures: Dict[str, int] = {}
        self._kill_switch_activations: Dict[str, int] = {}
        self._events: List[Dict[str, Any]] = []

    def create_campaign(self, campaign: LiveCampaign) -> LiveCampaign:
        """Create a new live campaign."""
        self._campaigns[campaign.campaign_id] = campaign
        self._evidence_collectors[campaign.campaign_id] = ExecutionEvidenceCollector()
        self._divergence_counts[campaign.campaign_id] = {"total": 0, "critical": 0}
        self._risk_violations[campaign.campaign_id] = 0
        self._reconciliation_failures[campaign.campaign_id] = 0
        self._kill_switch_activations[campaign.campaign_id] = 0
        self._record_event("CAMPAIGN_CREATED", campaign.campaign_id, campaign.status)
        return campaign

    def transition_campaign(
        self,
        campaign_id: str,
        new_status: str,
        timestamp: str,
        reason: str = "",
    ) -> bool:
        """Transition campaign to a new status."""
        campaign = self._campaigns.get(campaign_id)
        if campaign is None:
            return False

        if not campaign.can_transition_to(new_status):
            self._record_event(
                "INVALID_TRANSITION",
                campaign_id,
                f"{campaign.status} -> {new_status} (INVALID)",
                reason=reason,
            )
            return False

        updated = LiveCampaign(
            campaign_id=campaign.campaign_id,
            production_fingerprint=campaign.production_fingerprint,
            authorization_id=campaign.authorization_id,
            max_capital=campaign.max_capital,
            max_drawdown=campaign.max_drawdown,
            start_timestamp=campaign.start_timestamp,
            expiry_timestamp=campaign.expiry_timestamp,
            strategy_id=campaign.strategy_id,
            portfolio_id=campaign.portfolio_id,
            broker_identity=campaign.broker_identity,
            account_identity=campaign.account_identity,
            status=new_status,
            status_history=campaign.status_history + ((new_status, timestamp),),
            campaign_fingerprint=campaign.campaign_fingerprint,
        )
        self._campaigns[campaign_id] = updated
        self._record_event("STATUS_CHANGED", campaign_id, new_status, reason=reason)
        return True

    def record_execution_evidence(self, campaign_id: str, evidence: Any) -> None:
        """Record execution evidence for a campaign."""
        collector = self._evidence_collectors.get(campaign_id)
        if collector is not None:
            collector.record_order(evidence)

    def record_divergence(self, campaign_id: str, is_critical: bool = False) -> None:
        """Record a divergence event."""
        counts = self._divergence_counts.get(campaign_id, {"total": 0, "critical": 0})
        counts["total"] += 1
        if is_critical:
            counts["critical"] += 1
        self._divergence_counts[campaign_id] = counts

    def record_risk_violation(self, campaign_id: str) -> None:
        """Record a risk boundary violation."""
        self._risk_violations[campaign_id] = (
            self._risk_violations.get(campaign_id, 0) + 1
        )

    def record_reconciliation_failure(self, campaign_id: str) -> None:
        """Record a reconciliation failure."""
        self._reconciliation_failures[campaign_id] = (
            self._reconciliation_failures.get(campaign_id, 0) + 1
        )

    def record_kill_switch_activation(self, campaign_id: str) -> None:
        """Record a kill switch activation."""
        self._kill_switch_activations[campaign_id] = (
            self._kill_switch_activations.get(campaign_id, 0) + 1
        )

    def get_campaign(self, campaign_id: str) -> Optional[LiveCampaign]:
        return self._campaigns.get(campaign_id)

    def get_evidence_collector(
        self, campaign_id: str
    ) -> Optional[ExecutionEvidenceCollector]:
        return self._evidence_collectors.get(campaign_id)

    def get_divergence_counts(self, campaign_id: str) -> Dict[str, int]:
        return self._divergence_counts.get(campaign_id, {"total": 0, "critical": 0})

    def get_risk_violations(self, campaign_id: str) -> int:
        return self._risk_violations.get(campaign_id, 0)

    def get_reconciliation_failures(self, campaign_id: str) -> int:
        return self._reconciliation_failures.get(campaign_id, 0)

    def get_kill_switch_activations(self, campaign_id: str) -> int:
        return self._kill_switch_activations.get(campaign_id, 0)

    def _record_event(
        self, event_type: str, campaign_id: str, status: str, reason: str = ""
    ) -> None:
        self._events.append(
            {
                "event_type": event_type,
                "campaign_id": campaign_id,
                "status": status,
                "reason": reason,
            }
        )

    def get_events(self) -> List[Dict[str, Any]]:
        return list(self._events)
