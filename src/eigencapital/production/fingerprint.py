"""Production Fingerprint — frozen configuration identity for live campaigns.

Every live campaign records the exact configuration fingerprint.
If anything changes materially: qualification invalidated, requalification required.

Tracks:
- strategy_hash
- portfolio_hash
- feature_registry_hash
- risk_config_hash
- broker_config_hash
- execution_config_hash
- code_commit
- data/version identifiers
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from typing import Any, Dict


@dataclass(frozen=True)
class ProductionFingerprint:
    """Immutable production configuration identity.

    Records the exact system configuration that produced live evidence.
    Any material change invalidates qualification.
    """

    strategy_hash: str
    portfolio_hash: str
    feature_registry_hash: str
    risk_config_hash: str
    broker_config_hash: str
    execution_config_hash: str
    code_commit: str
    data_version: str = ""
    environment: str = "live"
    created_timestamp: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return {
            "strategy_hash": self.strategy_hash,
            "portfolio_hash": self.portfolio_hash,
            "feature_registry_hash": self.feature_registry_hash,
            "risk_config_hash": self.risk_config_hash,
            "broker_config_hash": self.broker_config_hash,
            "execution_config_hash": self.execution_config_hash,
            "code_commit": self.code_commit,
            "data_version": self.data_version,
            "environment": self.environment,
            "created_timestamp": self.created_timestamp,
        }

    def compute_identity(self) -> str:
        """Compute deterministic fingerprint of the entire production config."""
        data = self.to_dict()
        payload = json.dumps(data, sort_keys=True).encode("utf-8")
        return hashlib.sha256(payload).hexdigest()

    def matches(self, other: ProductionFingerprint) -> bool:
        """Check if two fingerprints match exactly."""
        return self.compute_identity() == other.compute_identity()

    def material_matches(self, other: ProductionFingerprint) -> bool:
        """Check if material fields match (excludes timestamp)."""
        return (
            self.strategy_hash == other.strategy_hash
            and self.portfolio_hash == other.portfolio_hash
            and self.feature_registry_hash == other.feature_registry_hash
            and self.risk_config_hash == other.risk_config_hash
            and self.broker_config_hash == other.broker_config_hash
            and self.execution_config_hash == other.execution_config_hash
            and self.code_commit == other.code_commit
            and self.data_version == other.data_version
        )


class FingerprintRegistry:
    """Registry of production fingerprints with drift detection."""

    def __init__(self) -> None:
        self._fingerprints: Dict[str, ProductionFingerprint] = {}
        self._drift_events: list = []

    def register(self, fingerprint_id: str, fingerprint: ProductionFingerprint) -> None:
        """Register a production fingerprint."""
        self._fingerprints[fingerprint_id] = fingerprint

    def get(self, fingerprint_id: str) -> ProductionFingerprint | None:
        """Get a registered fingerprint."""
        return self._fingerprints.get(fingerprint_id)

    def check_drift(self, fingerprint_id: str, current: ProductionFingerprint) -> Dict[str, Any]:
        """Check if current config drifts from registered fingerprint.

        Returns:
            {"drifted": bool, "changed_fields": [...], "details": str}
        """
        registered = self._fingerprints.get(fingerprint_id)
        if registered is None:
            return {
                "drifted": True,
                "changed_fields": ["all"],
                "details": "Fingerprint not registered",
            }

        changed = []
        if registered.strategy_hash != current.strategy_hash:
            changed.append("strategy_hash")
        if registered.portfolio_hash != current.portfolio_hash:
            changed.append("portfolio_hash")
        if registered.feature_registry_hash != current.feature_registry_hash:
            changed.append("feature_registry_hash")
        if registered.risk_config_hash != current.risk_config_hash:
            changed.append("risk_config_hash")
        if registered.broker_config_hash != current.broker_config_hash:
            changed.append("broker_config_hash")
        if registered.execution_config_hash != current.execution_config_hash:
            changed.append("execution_config_hash")
        if registered.code_commit != current.code_commit:
            changed.append("code_commit")
        if registered.data_version != current.data_version:
            changed.append("data_version")

        drifted = len(changed) > 0
        if drifted:
            self._drift_events.append(
                {
                    "fingerprint_id": fingerprint_id,
                    "changed_fields": changed,
                }
            )

        return {
            "drifted": drifted,
            "changed_fields": changed,
            "details": f"Changed: {', '.join(changed)}" if drifted else "No drift",
        }

    def get_drift_events(self) -> list:
        return list(self._drift_events)
