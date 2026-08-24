"""Micro-Live Campaign Model — immutable campaign identity and lifecycle.

Campaign lifecycle:
PLANNED → PREFLIGHT → AUTHORIZED → ACTIVE → PAUSED → COMPLETED/EXPIRED/FAILED

No deletion. Campaign history must be immutable/auditable.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from enum import Enum
from typing import Dict, List, Optional, Any


class CampaignStatus(str, Enum):
    """Campaign lifecycle status."""

    PLANNED = "planned"
    PREFLIGHT = "preflight"
    AUTHORIZED = "authorized"
    ACTIVE = "active"
    PAUSED = "paused"
    STOPPED = "stopped"
    EXPIRED = "expired"
    FAILED = "failed"
    COMPLETED = "completed"


# Valid state transitions
_VALID_TRANSITIONS: Dict[str, List[str]] = {
    CampaignStatus.PLANNED.value: [
        CampaignStatus.PREFLIGHT.value,
        CampaignStatus.FAILED.value,
    ],
    CampaignStatus.PREFLIGHT.value: [
        CampaignStatus.AUTHORIZED.value,
        CampaignStatus.FAILED.value,
    ],
    CampaignStatus.AUTHORIZED.value: [
        CampaignStatus.ACTIVE.value,
        CampaignStatus.STOPPED.value,
    ],
    CampaignStatus.ACTIVE.value: [
        CampaignStatus.PAUSED.value,
        CampaignStatus.STOPPED.value,
        CampaignStatus.EXPIRED.value,
        CampaignStatus.FAILED.value,
        CampaignStatus.COMPLETED.value,
    ],
    CampaignStatus.PAUSED.value: [
        CampaignStatus.ACTIVE.value,
        CampaignStatus.STOPPED.value,
        CampaignStatus.FAILED.value,
    ],
    CampaignStatus.STOPPED.value: [],
    CampaignStatus.EXPIRED.value: [],
    CampaignStatus.FAILED.value: [],
    CampaignStatus.COMPLETED.value: [],
}


@dataclass(frozen=True)
class MicroLiveCampaign:
    """First-class micro-live campaign with immutable identity.

    Campaign history is append-only and auditable.
    """

    campaign_id: str
    strategy_fingerprint: str
    portfolio_fingerprint: str
    feature_fingerprint: str
    risk_fingerprint: str
    execution_fingerprint: str
    broker_identity: str
    account_identity: str
    capital_limit: float
    drawdown_limit: float
    start_timestamp: str
    expiry_timestamp: str
    authorization_id: str = ""
    status: str = CampaignStatus.PLANNED.value
    status_history: tuple = ()  # immutable tuple of (status, timestamp) tuples
    campaign_fingerprint: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return {
            "campaign_id": self.campaign_id,
            "strategy_fingerprint": self.strategy_fingerprint,
            "portfolio_fingerprint": self.portfolio_fingerprint,
            "feature_fingerprint": self.feature_fingerprint,
            "risk_fingerprint": self.risk_fingerprint,
            "execution_fingerprint": self.execution_fingerprint,
            "broker_identity": self.broker_identity,
            "account_identity": self.account_identity,
            "capital_limit": self.capital_limit,
            "drawdown_limit": self.drawdown_limit,
            "start_timestamp": self.start_timestamp,
            "expiry_timestamp": self.expiry_timestamp,
            "authorization_id": self.authorization_id,
            "status": self.status,
        }

    def compute_fingerprint(self) -> str:
        data = self.to_dict()
        payload = json.dumps(data, sort_keys=True).encode("utf-8")
        return hashlib.sha256(payload).hexdigest()

    def can_transition_to(self, new_status: str) -> bool:
        """Check if a state transition is valid."""
        valid_targets = _VALID_TRANSITIONS.get(self.status, [])
        return new_status in valid_targets


class CampaignManager:
    """Manages micro-live campaign lifecycle with immutable audit trail."""

    def __init__(self) -> None:
        self._campaigns: Dict[str, MicroLiveCampaign] = {}
        self._events: List[Dict[str, Any]] = []

    def create_campaign(self, campaign: MicroLiveCampaign) -> MicroLiveCampaign:
        """Create a new campaign."""
        self._campaigns[campaign.campaign_id] = campaign
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

        # Create new immutable campaign with updated status
        updated = MicroLiveCampaign(
            campaign_id=campaign.campaign_id,
            strategy_fingerprint=campaign.strategy_fingerprint,
            portfolio_fingerprint=campaign.portfolio_fingerprint,
            feature_fingerprint=campaign.feature_fingerprint,
            risk_fingerprint=campaign.risk_fingerprint,
            execution_fingerprint=campaign.execution_fingerprint,
            broker_identity=campaign.broker_identity,
            account_identity=campaign.account_identity,
            capital_limit=campaign.capital_limit,
            drawdown_limit=campaign.drawdown_limit,
            start_timestamp=campaign.start_timestamp,
            expiry_timestamp=campaign.expiry_timestamp,
            authorization_id=campaign.authorization_id,
            status=new_status,
            status_history=campaign.status_history + ((new_status, timestamp),),
            campaign_fingerprint=campaign.campaign_fingerprint,
        )
        self._campaigns[campaign_id] = updated
        self._record_event("STATUS_CHANGED", campaign_id, new_status, reason=reason)
        return True

    def get_campaign(self, campaign_id: str) -> Optional[MicroLiveCampaign]:
        """Get a campaign by ID."""
        return self._campaigns.get(campaign_id)

    def get_all_campaigns(self) -> List[MicroLiveCampaign]:
        """Get all campaigns."""
        return list(self._campaigns.values())

    def get_campaigns_by_status(self, status: str) -> List[MicroLiveCampaign]:
        """Get campaigns by status."""
        return [c for c in self._campaigns.values() if c.status == status]

    def _record_event(
        self,
        event_type: str,
        campaign_id: str,
        status: str,
        reason: str = "",
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
