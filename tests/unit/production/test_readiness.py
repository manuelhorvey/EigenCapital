"""Adversarial tests for Phase 1M Production Readiness & Governance.

Tests cover:
- ReadinessResult evaluation and verdict logic
- SecurityBoundary verification
- ConfigurationManifest integrity
- SecurityAudit findings
- Edge cases: critical failures, missing evidence, no live connectivity
"""

import pytest

from eigencapital.production.readiness import (
    ReadinessResult,
    ReadinessVerdict,
    ReadinessCheck,
)
from eigencapital.production.security import (
    SecurityBoundary,
    ConfigurationManifest,
    SecurityAudit,
)


# ═══════════════════════════════════════════════
#  READINESS GATE
# ═══════════════════════════════════════════════

class TestReadinessGate:
    def test_production_ready_for_shadow(self):
        metrics = {
            "architecture_intact": True,
            "open_bypass_paths": 0,
            "risk_bypasses": 0,
            "research_execution_separated": True,
            "has_live_connectivity": False,
            "provenance_complete": True,
            "paper_qualified": True,
            "security_defined": True,
            "monitoring_defined": True,
            "disaster_recovery_tested": True,
            "capital_governance_defined": True,
            "configuration_drift_detected": False,
        }
        result = ReadinessResult.evaluate(metrics)
        assert result.verdict == ReadinessVerdict.PRODUCTION_READY_FOR_SHADOW

    def test_not_ready_critical_bypass(self):
        metrics = {
            "architecture_intact": True,
            "open_bypass_paths": 3,
            "risk_bypasses": 0,
            "research_execution_separated": True,
            "has_live_connectivity": False,
            "provenance_complete": True,
            "paper_qualified": True,
            "security_defined": True,
            "monitoring_defined": True,
            "disaster_recovery_tested": True,
            "capital_governance_defined": True,
            "configuration_drift_detected": False,
        }
        result = ReadinessResult.evaluate(metrics)
        assert result.verdict == ReadinessVerdict.NOT_READY

    def test_not_ready_risk_bypass(self):
        metrics = {
            "architecture_intact": True,
            "open_bypass_paths": 0,
            "risk_bypasses": 1,
            "research_execution_separated": True,
            "has_live_connectivity": False,
            "provenance_complete": True,
            "paper_qualified": True,
            "security_defined": True,
            "monitoring_defined": True,
            "disaster_recovery_tested": True,
            "capital_governance_defined": True,
            "configuration_drift_detected": False,
        }
        result = ReadinessResult.evaluate(metrics)
        assert result.verdict == ReadinessVerdict.NOT_READY

    def test_not_ready_live_connectivity(self):
        metrics = {
            "architecture_intact": True,
            "open_bypass_paths": 0,
            "risk_bypasses": 0,
            "research_execution_separated": True,
            "has_live_connectivity": True,
            "provenance_complete": True,
            "paper_qualified": True,
            "security_defined": True,
            "monitoring_defined": True,
            "disaster_recovery_tested": True,
            "capital_governance_defined": True,
            "configuration_drift_detected": False,
        }
        result = ReadinessResult.evaluate(metrics)
        assert result.verdict == ReadinessVerdict.NOT_READY

    def test_conditional_warnings(self):
        metrics = {
            "architecture_intact": True,
            "open_bypass_paths": 0,
            "risk_bypasses": 0,
            "research_execution_separated": True,
            "has_live_connectivity": False,
            "provenance_complete": False,
            "paper_qualified": False,
            "security_defined": True,
            "monitoring_defined": True,
            "disaster_recovery_tested": False,
            "capital_governance_defined": True,
            "configuration_drift_detected": False,
        }
        result = ReadinessResult.evaluate(metrics)
        assert result.verdict == ReadinessVerdict.CONDITIONAL

    def test_never_unrestricted_live(self):
        """Verdict should never be unrestricted LIVE_READY."""
        metrics = {
            "architecture_intact": True,
            "open_bypass_paths": 0,
            "risk_bypasses": 0,
            "research_execution_separated": True,
            "has_live_connectivity": False,
            "provenance_complete": True,
            "paper_qualified": True,
            "security_defined": True,
            "monitoring_defined": True,
            "disaster_recovery_tested": True,
            "capital_governance_defined": True,
            "configuration_drift_detected": False,
        }
        result = ReadinessResult.evaluate(metrics)
        assert result.verdict != "live_ready"

    def test_missing_evidence_not_pass(self):
        """Missing evidence must not equal pass."""
        metrics = {
            "architecture_intact": True,
            "open_bypass_paths": 0,
            "risk_bypasses": 0,
            "research_execution_separated": True,
            "has_live_connectivity": False,
            "provenance_complete": True,
            "paper_qualified": False,  # Missing paper qualification
            "security_defined": True,
            "monitoring_defined": True,
            "disaster_recovery_tested": True,
            "capital_governance_defined": True,
            "configuration_drift_detected": False,
        }
        result = ReadinessResult.evaluate(metrics)
        assert result.verdict != ReadinessVerdict.PRODUCTION_READY_FOR_SHADOW

    def test_checks_all_present(self):
        metrics = {
            "architecture_intact": True,
            "open_bypass_paths": 0,
            "risk_bypasses": 0,
            "research_execution_separated": True,
            "has_live_connectivity": False,
            "provenance_complete": True,
            "paper_qualified": True,
            "security_defined": True,
            "monitoring_defined": True,
            "disaster_recovery_tested": True,
            "capital_governance_defined": True,
            "configuration_drift_detected": False,
        }
        result = ReadinessResult.evaluate(metrics)
        assert len(result.checks) >= 10

    def test_serialization(self):
        metrics = {
            "architecture_intact": True,
            "open_bypass_paths": 0,
            "risk_bypasses": 0,
            "research_execution_separated": True,
            "has_live_connectivity": False,
            "provenance_complete": True,
            "paper_qualified": True,
            "security_defined": True,
            "monitoring_defined": True,
            "disaster_recovery_tested": True,
            "capital_governance_defined": True,
            "configuration_drift_detected": False,
        }
        result = ReadinessResult.evaluate(metrics)
        d = result.to_dict()
        assert d["verdict"] == "production_ready_for_shadow"
        assert len(d["checks"]) >= 10


# ═══════════════════════════════════════════════
#  SECURITY BOUNDARY
# ═══════════════════════════════════════════════

class TestSecurityBoundary:
    def test_boundary_creation(self):
        boundary = SecurityBoundary(
            component_a="research",
            component_b="execution",
            separation_rule="research cannot submit live orders",
            verified=True,
            evidence="Architecture audit passed",
        )
        assert boundary.verified
        assert boundary.component_a == "research"

    def test_boundary_serialization(self):
        boundary = SecurityBoundary(
            component_a="research",
            component_b="execution",
            separation_rule="separation",
            verified=True,
        )
        d = boundary.to_dict()
        assert d["verified"] is True
        assert d["component_a"] == "research"


# ═══════════════════════════════════════════════
#  CONFIGURATION MANIFEST
# ═══════════════════════════════════════════════

class TestConfigurationManifest:
    def test_manifest_creation(self):
        manifest = ConfigurationManifest(
            strategy_config_hash="abc123",
            risk_config_hash="def456",
            software_version="0.1.0",
        )
        assert manifest.strategy_config_hash == "abc123"
        assert manifest.software_version == "0.1.0"

    def test_manifest_hash_deterministic(self):
        manifest = ConfigurationManifest(
            strategy_config_hash="abc",
            software_version="1.0",
        )
        h1 = manifest.compute_hash()
        h2 = manifest.compute_hash()
        assert h1 == h2
        assert len(h1) == 64

    def test_manifest_serialization(self):
        manifest = ConfigurationManifest(
            strategy_config_hash="abc",
            software_version="1.0",
            environment="paper",
        )
        d = manifest.to_dict()
        assert d["strategy_config_hash"] == "abc"
        assert d["environment"] == "paper"


# ═══════════════════════════════════════════════
#  SECURITY AUDIT
# ═══════════════════════════════════════════════

class TestSecurityAudit:
    def test_verify_boundary(self):
        audit = SecurityAudit()
        boundary = audit.verify_boundary(
            "research", "execution",
            "research cannot submit live orders",
            verified=True,
            evidence="Test passed",
        )
        assert boundary.verified
        assert audit.all_boundaries_verified

    def test_record_finding(self):
        audit = SecurityAudit()
        audit.record_finding(
            category="credential_exposure",
            severity="CRITICAL",
            description="API key found in logs",
            recommendation="Remove from logs",
        )
        assert len(audit.get_findings()) == 1
        assert len(audit.critical_findings) == 1

    def test_all_boundaries_verified(self):
        audit = SecurityAudit()
        audit.verify_boundary("A", "B", "rule1", verified=True)
        audit.verify_boundary("C", "D", "rule2", verified=True)
        assert audit.all_boundaries_verified

    def test_not_all_boundaries_verified(self):
        audit = SecurityAudit()
        audit.verify_boundary("A", "B", "rule1", verified=True)
        audit.verify_boundary("C", "D", "rule2", verified=False)
        assert not audit.all_boundaries_verified

    def test_critical_findings(self):
        audit = SecurityAudit()
        audit.record_finding("cat1", "CRITICAL", "desc1")
        audit.record_finding("cat2", "WARNING", "desc2")
        audit.record_finding("cat3", "CRITICAL", "desc3")
        assert len(audit.critical_findings) == 2


# ═══════════════════════════════════════════════
#  ADVERSARIAL — PROPERTIES
# ═══════════════════════════════════════════════

class TestProperties:
    def test_critical_failure_blocks_readiness(self):
        """Any critical failure must block production readiness."""
        for field_name in ["open_bypass_paths", "risk_bypasses"]:
            metrics = {
                "architecture_intact": True,
                "open_bypass_paths": 0,
                "risk_bypasses": 0,
                "research_execution_separated": True,
                "has_live_connectivity": False,
                "provenance_complete": True,
                "paper_qualified": True,
                "security_defined": True,
                "monitoring_defined": True,
                "disaster_recovery_tested": True,
                "capital_governance_defined": True,
                "configuration_drift_detected": False,
                field_name: 1,
            }
            result = ReadinessResult.evaluate(metrics)
            assert result.verdict == ReadinessVerdict.NOT_READY, \
                f"Field {field_name} should cause NOT_READY"

    def test_live_connectivity_blocks_readiness(self):
        """Live connectivity must always block readiness."""
        metrics = {
            "architecture_intact": True,
            "open_bypass_paths": 0,
            "risk_bypasses": 0,
            "research_execution_separated": True,
            "has_live_connectivity": True,
            "provenance_complete": True,
            "paper_qualified": True,
            "security_defined": True,
            "monitoring_defined": True,
            "disaster_recovery_tested": True,
            "capital_governance_defined": True,
            "configuration_drift_detected": False,
        }
        result = ReadinessResult.evaluate(metrics)
        assert result.verdict == ReadinessVerdict.NOT_READY

    def test_all_checks_pass_shadow(self):
        """All checks passing should produce SHADOW verdict."""
        metrics = {
            "architecture_intact": True,
            "open_bypass_paths": 0,
            "risk_bypasses": 0,
            "research_execution_separated": True,
            "has_live_connectivity": False,
            "provenance_complete": True,
            "paper_qualified": True,
            "security_defined": True,
            "monitoring_defined": True,
            "disaster_recovery_tested": True,
            "capital_governance_defined": True,
            "configuration_drift_detected": False,
        }
        result = ReadinessResult.evaluate(metrics)
        assert result.verdict == ReadinessVerdict.PRODUCTION_READY_FOR_SHADOW
