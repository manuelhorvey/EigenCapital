"""Micro-Live Campaign Model — immutable campaign identity and lifecycle.

Campaign lifecycle:
PLANNED → PREFLIGHT → AUTHORIZED → ACTIVE → PAUSED → COMPLETED/EXPIRED/FAILED

No deletion. Campaign history must be immutable/auditable.

H-8 durability: every accepted create/transition event is appended to a
:class:`~eigencapital.live.durable_audit.DurableAudit` store (fsync'd,
append-only JSONL with a write-then-replace mirror) and reloaded in
``CampaignManager.__init__``, so a crash or restart cannot lose history.
"""

from __future__ import annotations

import fcntl
import hashlib
import json
import os
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import Any, Dict, List

from eigencapital.live.durable_audit import DurableAudit

_STORE_ENV_VAR = "EIGENCAPITAL_CAMPAIGN_STORE"
_DEFAULT_STORE = "reports/campaigns.jsonl"


def _resolve_store_path(store_path: Path | None) -> Path:
    """Resolve the campaign store location.

    Injectable for callers/tests; the default follows the repo evidence
    convention (``reports/`` — same directory family durable_audit records
    land in) with an ``EIGENCAPITAL_*`` env override, mirroring how
    ``EIGENCAPITAL_SHADOW_OUT_DIR`` resolves the shadow evidence directory.
    """
    if store_path is not None:
        return Path(store_path)
    return Path(os.environ.get(_STORE_ENV_VAR, _DEFAULT_STORE))


def _mirror_path(path: Path) -> Path:
    """Mirror location, following durable_audit's ``*.mirror.*`` naming."""
    return path.with_name(f"{path.stem}.mirror{path.suffix}")


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

    def to_record(self) -> Dict[str, Any]:
        """Full serialization for the durable store (identity history included)."""
        data = self.to_dict()
        data["status_history"] = [list(entry) for entry in self.status_history]
        data["campaign_fingerprint"] = self.campaign_fingerprint
        return data

    @classmethod
    def from_record(cls, data: Dict[str, Any]) -> MicroLiveCampaign:
        """Rebuild a campaign from a durable-store record."""
        history = data.get("status_history") or ()
        return cls(
            campaign_id=str(data["campaign_id"]),
            strategy_fingerprint=str(data["strategy_fingerprint"]),
            portfolio_fingerprint=str(data["portfolio_fingerprint"]),
            feature_fingerprint=str(data["feature_fingerprint"]),
            risk_fingerprint=str(data["risk_fingerprint"]),
            execution_fingerprint=str(data["execution_fingerprint"]),
            broker_identity=str(data["broker_identity"]),
            account_identity=str(data["account_identity"]),
            capital_limit=float(data["capital_limit"]),
            drawdown_limit=float(data["drawdown_limit"]),
            start_timestamp=str(data["start_timestamp"]),
            expiry_timestamp=str(data["expiry_timestamp"]),
            authorization_id=str(data.get("authorization_id", "")),
            status=str(data.get("status", CampaignStatus.PLANNED.value)),
            status_history=tuple(tuple(str(item) for item in entry) for entry in history),
            campaign_fingerprint=str(data.get("campaign_fingerprint", "")),
        )

    def compute_fingerprint(self) -> str:
        data = self.to_dict()
        payload = json.dumps(data, sort_keys=True).encode("utf-8")
        return hashlib.sha256(payload).hexdigest()

    def can_transition_to(self, new_status: str) -> bool:
        """Check if a state transition is valid."""
        valid_targets = _VALID_TRANSITIONS.get(self.status, [])
        return new_status in valid_targets


class CampaignManager:
    """Manages micro-live campaign lifecycle with immutable audit trail.

    History is append-only on disk (DurableAudit: fsync'd hash-chained JSONL
    plus an atomic write-then-replace mirror) and reloaded on construction,
    so a crash or restart cannot lose campaigns or transition events.
    """

    def __init__(self, store_path: Path | None = None) -> None:
        path = _resolve_store_path(store_path)
        self._mirror = _mirror_path(path)
        self._store = DurableAudit(path, self._mirror)
        self._campaigns: Dict[str, MicroLiveCampaign] = {}
        self._events: List[Dict[str, Any]] = []
        self._load()

    def _repair_torn_tail(self) -> None:
        """Terminate a torn tail line so the next append gets its own line.

        A crash mid-append leaves a partial record with no trailing newline;
        without this, DurableAudit's next append would concatenate onto the
        garbage line and become unreadable. Append-only repair: exactly one
        delimiter byte is added — no existing byte is ever touched. The check
        and the write share the inter-process lock DurableAudit holds while
        appending, so a concurrent writer can never land between them.
        """
        path = self._store.path
        if not path.exists():
            return
        with open(path, "a+b") as handle:
            fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
            try:
                handle.seek(0, os.SEEK_END)
                if handle.tell() == 0:
                    return
                handle.seek(-1, os.SEEK_END)
                if handle.read(1) == b"\n":
                    return
                handle.write(b"\n")
                handle.flush()
                os.fsync(handle.fileno())
            finally:
                fcntl.flock(handle.fileno(), fcntl.LOCK_UN)

    def _restore_primary_from_mirror(self) -> None:
        """Recreate a lost or zeroed primary from the mirror (stage+fsync+replace).

        The mirror is rewritten write-then-replace after every successful
        append, so it holds the same records the primary had. Restoring it
        before the load also keeps the next append continuing the existing
        hash chain: without this, a fresh primary would restart at seq 1 and
        the following restart would load only that record, silently dropping
        everything the mirror carried. Staging is done on a temp file, so a
        crash mid-restore can never truncate either copy.
        """
        primary = self._store.path
        if primary.exists() and primary.stat().st_size > 0:
            return
        if not self._mirror.exists() or self._mirror.stat().st_size == 0:
            return
        primary.parent.mkdir(parents=True, exist_ok=True)
        staged = primary.with_name(primary.name + ".tmp")
        with open(staged, "wb") as handle:
            handle.write(self._mirror.read_bytes())
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(staged, primary)

    def _load(self) -> None:
        """Rebuild state from the durable store, tolerating crash artifacts.

        Store records are ``{"event": {...}, "campaign": {...}|absent}``
        payloads; replaying them in order rebuilds the same state the
        previous process held. Unparseable lines are torn tail records from
        a crash mid-append and are skipped exactly as durable_audit skips
        them when chaining. Replaying the same records twice is idempotent:
        campaign state is keyed by ``campaign_id``, so the last snapshot for
        an id wins no matter how many times it was written.
        """
        self._restore_primary_from_mirror()
        self._repair_torn_tail()
        path = self._store.path
        if not path.exists():
            return
        with open(path, encoding="utf-8") as handle:
            for line in handle:
                line = line.strip()
                if not line:
                    continue
                try:
                    record = json.loads(line)
                except json.JSONDecodeError:
                    continue  # torn line from a crash mid-append: no record there
                if not isinstance(record, dict):
                    continue  # not a durable_audit record
                payload = record.get("payload")
                if not isinstance(payload, dict):
                    continue  # torn record truncated at a valid-JSON boundary
                event = payload.get("event")
                if isinstance(event, dict):
                    self._events.append(
                        {
                            "event_type": event.get("event_type", ""),
                            "campaign_id": event.get("campaign_id", ""),
                            "status": event.get("status", ""),
                            "reason": event.get("reason", ""),
                        }
                    )
                snapshot = payload.get("campaign")
                if isinstance(snapshot, dict):
                    campaign = MicroLiveCampaign.from_record(snapshot)
                    self._campaigns[campaign.campaign_id] = campaign

    def create_campaign(self, campaign: MicroLiveCampaign) -> MicroLiveCampaign:
        """Create a new campaign."""
        self._record_event("CAMPAIGN_CREATED", campaign.campaign_id, campaign.status, campaign=campaign)
        self._campaigns[campaign.campaign_id] = campaign
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
        # Persist before mutating in-memory state: a failed write can never
        # leave the live view ahead of the durable history.
        self._record_event("STATUS_CHANGED", campaign_id, new_status, reason=reason, campaign=updated)
        self._campaigns[campaign_id] = updated
        return True

    def get_campaign(self, campaign_id: str) -> MicroLiveCampaign | None:
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
        campaign: MicroLiveCampaign | None = None,
    ) -> None:
        event: Dict[str, Any] = {
            "event_type": event_type,
            "campaign_id": campaign_id,
            "status": status,
            "reason": reason,
        }
        payload: Dict[str, Any] = {"event": event}
        if campaign is not None:
            payload["campaign"] = campaign.to_record()
        # Append-only, fsync'd write (never truncates the store); raises on
        # failure so callers never observe memory ahead of disk. The torn-tail
        # check runs first so a tail left by a crashed concurrent writer
        # cannot swallow this record into an unreadable line.
        self._repair_torn_tail()
        self._store.append(event_type, payload)
        self._events.append(event)

    def get_events(self) -> List[Dict[str, Any]]:
        return list(self._events)
