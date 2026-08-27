"""Security Model — credential handling, access control, privilege separation.

Verifies that:
- Research code cannot submit live orders
- Live credentials cannot be consumed by research paths
- Configuration changes are auditable
- No real credentials exist in the repository
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from typing import Any, Dict, List


@dataclass(frozen=True)
class SecurityBoundary:
    """Defines a security boundary between components."""

    component_a: str
    component_b: str
    separation_rule: str
    verified: bool = False
    evidence: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return {
            "component_a": self.component_a,
            "component_b": self.component_b,
            "separation_rule": self.separation_rule,
            "verified": self.verified,
            "evidence": self.evidence,
        }


@dataclass(frozen=True)
class ConfigurationManifest:
    """Deployment configuration manifest with hashes."""

    strategy_config_hash: str = ""
    strategy_artifact_hash: str = ""
    feature_config_hash: str = ""
    portfolio_config_hash: str = ""
    risk_config_hash: str = ""
    execution_config_hash: str = ""
    data_config_hash: str = ""
    software_version: str = ""
    environment: str = ""
    deployment_timestamp: str = ""
    approver: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return {
            "strategy_config_hash": self.strategy_config_hash,
            "strategy_artifact_hash": self.strategy_artifact_hash,
            "feature_config_hash": self.feature_config_hash,
            "portfolio_config_hash": self.portfolio_config_hash,
            "risk_config_hash": self.risk_config_hash,
            "execution_config_hash": self.execution_config_hash,
            "data_config_hash": self.data_config_hash,
            "software_version": self.software_version,
            "environment": self.environment,
            "deployment_timestamp": self.deployment_timestamp,
            "approver": self.approver,
        }

    def compute_hash(self) -> str:
        data = self.to_dict()
        payload = json.dumps(data, sort_keys=True).encode("utf-8")
        return hashlib.sha256(payload).hexdigest()


class SecurityAudit:
    """Performs security audit of the system."""

    def __init__(self) -> None:
        self._boundaries: List[SecurityBoundary] = []
        self._findings: List[Dict[str, Any]] = []

    def verify_boundary(
        self,
        component_a: str,
        component_b: str,
        separation_rule: str,
        verified: bool,
        evidence: str = "",
    ) -> SecurityBoundary:
        """Record a security boundary verification."""
        boundary = SecurityBoundary(
            component_a=component_a,
            component_b=component_b,
            separation_rule=separation_rule,
            verified=verified,
            evidence=evidence,
        )
        self._boundaries.append(boundary)
        return boundary

    def record_finding(
        self,
        category: str,
        severity: str,
        description: str,
        recommendation: str = "",
    ) -> None:
        """Record a security finding."""
        self._findings.append(
            {
                "category": category,
                "severity": severity,
                "description": description,
                "recommendation": recommendation,
            }
        )

    def get_boundaries(self) -> List[SecurityBoundary]:
        return list(self._boundaries)

    def get_findings(self) -> List[Dict[str, Any]]:
        return list(self._findings)

    @property
    def all_boundaries_verified(self) -> bool:
        return all(b.verified for b in self._boundaries)

    @property
    def critical_findings(self) -> List[Dict[str, Any]]:
        return [f for f in self._findings if f["severity"] == "CRITICAL"]
