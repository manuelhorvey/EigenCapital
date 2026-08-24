"""Adversarial tests for Phase 1L Paper-Trading Validation & Qualification.

Tests cover:
- PaperCampaign creation and lifecycle
- ParityChecker divergence classification
- ExecutionAttribution computation
- QualificationResult evaluation
- Edge cases: critical failures, missing evidence, restart safety
"""

import pytest

from eigencapital.paper.campaign import PaperCampaign, CampaignStatus
from eigencapital.paper.parity import (
    ParityChecker,
    DivergenceCategory,
    DivergenceSeverity,
)
from eigencapital.paper.qualification import (
    QualificationResult,
    QualificationVerdict,
)


# ═══════════════════════════════════════════════
#  PAPER CAMPAIGN
# ═══════════════════════════════════════════════


class TestPaperCampaign:
    def test_basic_creation(self):
        campaign = PaperCampaign(
            campaign_id="PC-001",
            strategy_id="trend_v1",
            strategy_version="v1",
        )
        assert campaign.campaign_id == "PC-001"
        assert campaign.status == CampaignStatus.CREATED

    def test_missing_campaign_id(self):
        with pytest.raises(ValueError, match="campaign_id"):
            PaperCampaign(
                campaign_id="",
                strategy_id="trend_v1",
                strategy_version="v1",
            )

    def test_missing_strategy_id(self):
        with pytest.raises(ValueError, match="strategy_id"):
            PaperCampaign(
                campaign_id="PC-001",
                strategy_id="",
                strategy_version="v1",
            )

    def test_deterministic_serialization(self):
        campaign = PaperCampaign(
            campaign_id="PC-001",
            strategy_id="trend_v1",
            strategy_version="v1",
            universe={"instruments": ["ES", "NQ"]},
        )
        d1 = campaign.to_dict()
        d2 = campaign.to_dict()
        assert d1 == d2

    def test_provenance_deterministic(self):
        campaign = PaperCampaign(
            campaign_id="PC-001",
            strategy_id="trend_v1",
            strategy_version="v1",
        )
        h1 = campaign.compute_provenance_hash()
        h2 = campaign.compute_provenance_hash()
        assert h1 == h2
        assert len(h1) == 64

    def test_serialization_roundtrip(self):
        campaign = PaperCampaign(
            campaign_id="PC-001",
            strategy_id="trend_v1",
            strategy_version="v1",
            status=CampaignStatus.RUNNING,
            initial_capital=200000,
        )
        d = campaign.to_dict()
        c2 = PaperCampaign.from_dict(d)
        assert c2.campaign_id == "PC-001"
        assert c2.status == CampaignStatus.RUNNING
        assert c2.initial_capital == 200000

    def test_lifecycle_statuses(self):
        statuses = [
            CampaignStatus.CREATED,
            CampaignStatus.ARMED,
            CampaignStatus.RUNNING,
            CampaignStatus.PAUSED,
            CampaignStatus.COMPLETED,
            CampaignStatus.ABORTED,
            CampaignStatus.QUALIFIED,
            CampaignStatus.NOT_QUALIFIED,
        ]
        for status in statuses:
            campaign = PaperCampaign(
                campaign_id="PC-001",
                strategy_id="trend_v1",
                strategy_version="v1",
                status=status,
            )
            assert campaign.status == status


# ═══════════════════════════════════════════════
#  PARITY CHECKER
# ═══════════════════════════════════════════════


class TestParityChecker:
    def test_no_divergence(self):
        checker = ParityChecker("PC-001")
        result = checker.check_signal("2025-01-15T10:00:00Z", "ES", 0.05, 0.05)
        assert result is None
        assert checker.divergence_count == 0

    def test_signal_divergence(self):
        checker = ParityChecker("PC-001")
        result = checker.check_signal("2025-01-15T10:00:00Z", "ES", 0.05, 0.06)
        assert result is not None
        assert result.category == DivergenceCategory.SIGNAL
        assert checker.divergence_count == 1

    def test_position_divergence_critical(self):
        checker = ParityChecker("PC-001")
        result = checker.check_position("2025-01-15T10:00:00Z", "ES", 10.0, 5.0)
        assert result is not None
        assert result.severity == DivergenceSeverity.CRITICAL
        assert result.magnitude == 5.0

    def test_position_divergence_warning(self):
        checker = ParityChecker("PC-001")
        result = checker.check_position("2025-01-15T10:00:00Z", "ES", 10.0, 9.5)
        assert result is not None
        assert result.severity == DivergenceSeverity.WARNING

    def test_order_divergence(self):
        checker = ParityChecker("PC-001")
        result = checker.check_order(
            "2025-01-15T10:00:00Z",
            "ES",
            "BUY",
            10,
            "SELL",
            10,
        )
        assert result is not None
        assert result.category == DivergenceCategory.ORDER

    def test_fill_price_slippage(self):
        checker = ParityChecker("PC-001")
        result = checker.check_fill_price(
            "2025-01-15T10:00:00Z",
            "ES",
            5000.0,
            5001.0,
            max_slippage=0.5,
        )
        assert result is not None
        assert result.magnitude == pytest.approx(1.0)

    def test_execution_attribution(self):
        checker = ParityChecker("PC-001")
        attr = checker.compute_attribution(
            expected_price=5000.0,
            actual_price=5002.0,
            spread_cost=1.0,
            delay_cost=0.5,
        )
        assert attr.spread_cost == 1.0
        assert attr.slippage_cost == pytest.approx(2.0)
        assert attr.total_execution_drag == pytest.approx(3.5)

    def test_filter_by_severity(self):
        checker = ParityChecker("PC-001")
        checker.check_position("2025-01-15T10:00:00Z", "ES", 10.0, 5.0)  # CRITICAL
        checker.check_signal("2025-01-15T10:00:00Z", "ES", 0.05, 0.06)  # WARNING

        critical = checker.get_divergences(severity=DivergenceSeverity.CRITICAL)
        assert len(critical) == 1

    def test_has_critical(self):
        checker = ParityChecker("PC-001")
        assert not checker.has_critical
        checker.check_position("2025-01-15T10:00:00Z", "ES", 10.0, 5.0)
        assert checker.has_critical

    def test_divergence_serialization(self):
        checker = ParityChecker("PC-001")
        result = checker.check_signal("2025-01-15T10:00:00Z", "ES", 0.05, 0.06)
        d = result.to_dict()
        assert d["category"] == "signal_divergence"
        assert d["severity"] == "warning"


# ═══════════════════════════════════════════════
#  QUALIFICATION
# ═══════════════════════════════════════════════


class TestQualification:
    def test_paper_qualified(self):
        metrics = {
            "reconciliation_failures": 0,
            "risk_bypasses": 0,
            "accounting_errors": 0,
            "critical_divergences": 0,
            "duplicate_fills": 0,
            "restart_errors": 0,
            "total_execution_drag": 0.005,
            "max_allowed_drag": 0.01,
            "provenance_complete": True,
        }
        result = QualificationResult.evaluate("PC-001", metrics)
        assert result.verdict == QualificationVerdict.PAPER_QUALIFIED

    def test_not_qualified_critical(self):
        metrics = {
            "reconciliation_failures": 3,
            "risk_bypasses": 0,
            "accounting_errors": 0,
            "critical_divergences": 0,
            "duplicate_fills": 0,
            "restart_errors": 0,
            "provenance_complete": True,
        }
        result = QualificationResult.evaluate("PC-001", metrics)
        assert result.verdict == QualificationVerdict.NOT_QUALIFIED

    def test_conditional_warnings(self):
        metrics = {
            "reconciliation_failures": 0,
            "risk_bypasses": 0,
            "accounting_errors": 0,
            "critical_divergences": 0,
            "duplicate_fills": 0,
            "restart_errors": 5,
            "total_execution_drag": 0.05,
            "max_allowed_drag": 0.01,
            "provenance_complete": True,
        }
        result = QualificationResult.evaluate("PC-001", metrics)
        assert result.verdict == QualificationVerdict.CONDITIONAL

    def test_not_qualified_risk_bypass(self):
        metrics = {
            "reconciliation_failures": 0,
            "risk_bypasses": 1,
            "accounting_errors": 0,
            "critical_divergences": 0,
            "duplicate_fills": 0,
            "restart_errors": 0,
            "provenance_complete": True,
        }
        result = QualificationResult.evaluate("PC-001", metrics)
        assert result.verdict == QualificationVerdict.NOT_QUALIFIED

    def test_not_qualified_duplicate_fills(self):
        metrics = {
            "reconciliation_failures": 0,
            "risk_bypasses": 0,
            "accounting_errors": 0,
            "critical_divergences": 0,
            "duplicate_fills": 2,
            "restart_errors": 0,
            "provenance_complete": True,
        }
        result = QualificationResult.evaluate("PC-001", metrics)
        assert result.verdict == QualificationVerdict.NOT_QUALIFIED

    def test_missing_evidence_not_pass(self):
        """Missing evidence should not equal PASS."""
        metrics = {
            "reconciliation_failures": 0,
            "risk_bypasses": 0,
            "accounting_errors": 0,
            "critical_divergences": 0,
            "duplicate_fills": 0,
            "restart_errors": 0,
            "provenance_complete": False,
        }
        result = QualificationResult.evaluate("PC-001", metrics)
        # Provenance incomplete should not be PAPER_QUALIFIED
        assert result.verdict != QualificationVerdict.PAPER_QUALIFIED

    def test_checks_all_present(self):
        metrics = {
            "reconciliation_failures": 0,
            "risk_bypasses": 0,
            "accounting_errors": 0,
            "critical_divergences": 0,
            "duplicate_fills": 0,
            "restart_errors": 0,
            "provenance_complete": True,
        }
        result = QualificationResult.evaluate("PC-001", metrics)
        assert len(result.checks) >= 8

    def test_serialization(self):
        metrics = {
            "reconciliation_failures": 0,
            "risk_bypasses": 0,
            "accounting_errors": 0,
            "critical_divergences": 0,
            "duplicate_fills": 0,
            "restart_errors": 0,
            "provenance_complete": True,
        }
        result = QualificationResult.evaluate("PC-001", metrics)
        d = result.to_dict()
        assert d["campaign_id"] == "PC-001"
        assert d["verdict"] == "paper_qualified"


# ═══════════════════════════════════════════════
#  ADVERSARIAL — PROPERTIES
# ═══════════════════════════════════════════════


class TestProperties:
    def test_divergence_always_recorded(self):
        """Every divergence must be recorded."""
        checker = ParityChecker("PC-001")
        for i in range(10):
            checker.check_signal(f"2025-01-{15 + i:02d}T10:00:00Z", "ES", 0.05, 0.06)
        assert checker.divergence_count == 10

    def test_no_critical_passes_qualification(self):
        """No critical failures should not block qualification."""
        metrics = {
            "reconciliation_failures": 0,
            "risk_bypasses": 0,
            "accounting_errors": 0,
            "critical_divergences": 0,
            "duplicate_fills": 0,
            "restart_errors": 0,
            "provenance_complete": True,
        }
        result = QualificationResult.evaluate("PC-001", metrics)
        assert result.verdict == QualificationVerdict.PAPER_QUALIFIED

    def test_critical_fails_qualification(self):
        """Any critical failure must block qualification."""
        for field_name in [
            "reconciliation_failures",
            "risk_bypasses",
            "accounting_errors",
            "critical_divergences",
            "duplicate_fills",
        ]:
            metrics = {
                "reconciliation_failures": 0,
                "risk_bypasses": 0,
                "accounting_errors": 0,
                "critical_divergences": 0,
                "duplicate_fills": 0,
                "restart_errors": 0,
                "provenance_complete": True,
                field_name: 1,
            }
            result = QualificationResult.evaluate("PC-001", metrics)
            assert result.verdict == QualificationVerdict.NOT_QUALIFIED, (
                f"Field {field_name} should cause NOT_QUALIFIED"
            )
