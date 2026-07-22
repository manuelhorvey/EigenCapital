"""DecisionID — globally unique identifier for every provenance decision.

Each decision gets a UUID4.  The ``lineage_id`` links related decisions
across Live / Shadow / Counterfactual / Replay runs so they can be
queried together regardless of which variant produced them.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass


@dataclass(frozen=True)
class DecisionID:
    decision_id: str
    lineage_id: str

    @classmethod
    def generate(cls, lineage_id: str | None = None) -> DecisionID:
        return cls(
            decision_id=str(uuid.uuid4()),
            lineage_id=lineage_id or str(uuid.uuid4()),
        )

    @classmethod
    def from_dict(cls, data: dict) -> DecisionID:
        return cls(
            decision_id=data["decision_id"],
            lineage_id=data["lineage_id"],
        )

    def to_dict(self) -> dict:
        return {
            "decision_id": self.decision_id,
            "lineage_id": self.lineage_id,
        }
