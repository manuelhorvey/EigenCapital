"""Paper Campaign — domain model for extended paper-trading operations.

A PaperCampaign is an immutable identity that tracks a complete paper-trading
run through the execution stack. It provides:
- Campaign lifecycle management
- Configuration immutability
- Provenance tracking
- Checkpoint support
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from enum import Enum
from typing import Dict, List, Optional, Any


class CampaignStatus(str, Enum):
    """Paper campaign lifecycle status."""
    CREATED = "created"
    ARMED = "armed"
    RUNNING = "running"
    PAUSED = "paused"
    COMPLETED = "completed"
    ABORTED = "aborted"
    QUALIFIED = "qualified"
    NOT_QUALIFIED = "not_qualified"


@dataclass(frozen=True)
class PaperCampaign:
    """Immutable paper campaign identity.

    The campaign must have immutable identity and frozen configuration.
    No field may change after ARMED status.
    """
    campaign_id: str
    strategy_id: str
    strategy_version: str
    experiment_id: str = ""
    hypothesis_id: str = ""
    dataset_version: str = ""
    universe: Dict[str, Any] = field(default_factory=dict)
    initial_capital: float = 100000.0
    risk_policy_hash: str = ""
    cost_model_id: str = ""
    deterministic_seed: Optional[int] = None
    start_timestamp: str = ""
    end_timestamp: str = ""
    status: CampaignStatus = CampaignStatus.CREATED
    provenance_hash: str = ""

    def __post_init__(self) -> None:
        if not self.campaign_id:
            raise ValueError("campaign_id must be non-empty")
        if not self.strategy_id:
            raise ValueError("strategy_id must be non-empty")

    def to_dict(self) -> Dict[str, Any]:
        return {
            "campaign_id": self.campaign_id,
            "strategy_id": self.strategy_id,
            "strategy_version": self.strategy_version,
            "experiment_id": self.experiment_id,
            "hypothesis_id": self.hypothesis_id,
            "dataset_version": self.dataset_version,
            "universe": dict(sorted(self.universe.items())),
            "initial_capital": self.initial_capital,
            "risk_policy_hash": self.risk_policy_hash,
            "cost_model_id": self.cost_model_id,
            "deterministic_seed": self.deterministic_seed,
            "start_timestamp": self.start_timestamp,
            "end_timestamp": self.end_timestamp,
            "status": self.status.value,
        }

    def compute_provenance_hash(self) -> str:
        data = self.to_dict()
        payload = json.dumps(data, sort_keys=True).encode("utf-8")
        return hashlib.sha256(payload).hexdigest()

    @classmethod
    def from_dict(cls, d: Dict[str, Any]) -> PaperCampaign:
        status_str = d.get("status", "created")
        try:
            status = CampaignStatus(status_str)
        except ValueError:
            status = CampaignStatus.CREATED
        return cls(
            campaign_id=d["campaign_id"],
            strategy_id=d["strategy_id"],
            strategy_version=d.get("strategy_version", ""),
            experiment_id=d.get("experiment_id", ""),
            hypothesis_id=d.get("hypothesis_id", ""),
            dataset_version=d.get("dataset_version", ""),
            universe=d.get("universe", {}),
            initial_capital=d.get("initial_capital", 100000.0),
            risk_policy_hash=d.get("risk_policy_hash", ""),
            cost_model_id=d.get("cost_model_id", ""),
            deterministic_seed=d.get("deterministic_seed"),
            start_timestamp=d.get("start_timestamp", ""),
            end_timestamp=d.get("end_timestamp", ""),
            status=status,
        )
