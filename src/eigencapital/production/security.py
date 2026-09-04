"""Security Model — credential handling, access control, privilege separation.

Verifies that:
- Research code cannot submit live orders
- Live credentials cannot be consumed by research paths
- Configuration changes are auditable
- No real credentials exist in the repository

Unlike a pure record-keeping ledger, :class:`SecurityAudit` runs automated
static scans (hardcoded credentials, research/live import separation) and
records their outcomes as verified boundaries with evidence (S6).
"""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from pathlib import Path
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

    # ── Automated scans (S6: audit must enforce, not just record) ────

    def scan_for_hardcoded_credentials(self, src_dir: Path) -> None:
        """Scan the source tree for hardcoded credentials and record findings.

        Results are exposed both as ``findings`` (CRITICAL) and as a verified/
        failed SecurityBoundary record so ``all_boundaries_verified`` reflects
        the actual scan outcome rather than a manual assertion.
        """
        patterns = [
            re.compile(r"""(?:password|passwd)\s*=\s*["'][^"']+["']""", re.IGNORECASE),
            re.compile(r"""(?:api_key|apikey|api_secret)\s*=\s*["'][A-Za-z0-9_\-]{20,}["']""", re.IGNORECASE),
        ]
        violations: List[str] = []
        for py_file in sorted(src_dir.rglob("*.py")):
            if "test_" in py_file.name:
                continue
            content = py_file.read_text(errors="replace")
            for pattern in patterns:
                for match in pattern.finditer(content):
                    line_no = content[: match.start()].count("\n") + 1
                    violations.append(f"{py_file}:{line_no}: {match.group()[:80]}")

        evidence = "No hardcoded credentials found" if not violations else "\n".join(violations[:10])
        if violations:
            for v in violations:
                self.record_finding(
                    category="credentials",
                    severity="CRITICAL",
                    description=v,
                    recommendation="Move credential to environment variable / config secret store.",
                )
        self._boundaries.append(
            SecurityBoundary(
                component_a="codebase",
                component_b="credentials",
                separation_rule="no hardcoded passwords/api keys in source",
                verified=not violations,
                evidence=evidence,
            )
        )

    def scan_research_live_separation(self, src_dir: Path) -> None:
        """Verify research code never imports live execution (boundary scan)."""
        research_dir = src_dir / "eigencapital" / "research"
        violations: List[str] = []
        if research_dir.exists():
            for py_file in sorted(research_dir.rglob("*.py")):
                content = py_file.read_text(errors="replace")
                if "from eigencapital.execution" in content or "from eigencapital.live" in content:
                    violations.append(str(py_file))

        evidence = (
            "Research code does not import live/execution modules" if not violations else "\n".join(violations[:10])
        )
        if violations:
            self.record_finding(
                category="research_execution_separation",
                severity="CRITICAL",
                description=f"{len(violations)} research file(s) import live/execution code",
                recommendation="Move shared primitives into core/ instead of importing live code from research.",
            )
        self._boundaries.append(
            SecurityBoundary(
                component_a="research",
                component_b="execution/live",
                separation_rule="research cannot submit live orders",
                verified=not violations,
                evidence=evidence,
            )
        )

    def run_automated_checks(self, src_dir: Path) -> None:
        """Run all automated static security scans.

        ``all_boundaries_verified`` then reflects automated scan outcomes plus
        any manually asserted boundaries, so a green security audit requires
        both to pass.
        """
        self.scan_for_hardcoded_credentials(src_dir)
        self.scan_research_live_separation(src_dir)

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
