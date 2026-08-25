"""Tests for capital tier governance: tier definitions, promotion gates, evidence requirements, skip prevention."""

import pytest
from eigencapital.production_qual.capital_tier_governance import (
    ALL_TIERS, CapitalTierGovernor, PromotionEvidence, PromotionVerdict,
    TIER_1_QUALIFICATION, TIER_2_PROVISIONAL, get_tier_by_id,
)


class TestTierDefinitions:
    def test_all_tiers_have_fingerprints(self):
        for tier in ALL_TIERS:
            assert len(tier.compute_fingerprint()) == 16

    def test_tier_immutable(self):
        with pytest.raises(AttributeError):
            TIER_1_QUALIFICATION.max_equity = 100_000.0  # type: ignore[misc]

    def test_fingerprint_deterministic(self):
        assert TIER_1_QUALIFICATION.compute_fingerprint() == TIER_1_QUALIFICATION.compute_fingerprint()

    def test_different_tiers_different_fingerprints(self):
        assert TIER_1_QUALIFICATION.compute_fingerprint() != TIER_2_PROVISIONAL.compute_fingerprint()

    def test_known_tier_lookup(self):
        assert get_tier_by_id("T1-QUALIFICATION") is TIER_1_QUALIFICATION
        assert get_tier_by_id("NONEXISTENT") is None


class TestGovernorActivation:
    def test_activate_tier(self):
        gov = CapitalTierGovernor()
        tier = gov.activate_tier("T1-QUALIFICATION")
        assert tier.tier_id == "T1-QUALIFICATION"
        assert gov.active_tier is tier

    def test_activate_unknown_tier_raises(self):
        gov = CapitalTierGovernor()
        with pytest.raises(ValueError, match="Unknown capital tier"):
            gov.activate_tier("T99-NONEXISTENT")

    def test_check_equity_within_tier(self):
        gov = CapitalTierGovernor()
        gov.activate_tier("T1-QUALIFICATION")
        assert gov.check_equity_against_tier(4_000.0) is True
        assert gov.check_equity_against_tier(5_100.0) is True
        assert gov.check_equity_against_tier(6_000.0) is False

    def test_check_equity_no_tier_returns_false(self):
        gov = CapitalTierGovernor()
        assert gov.check_equity_against_tier(4_000.0) is False


class TestPromotionGates:
    def test_approved_when_all_gates_pass(self):
        gov = CapitalTierGovernor()
        gov.activate_tier("T1-QUALIFICATION")
        evidence = PromotionEvidence(stable_days=14, critical_incidents=0,
                                     duplicate_orders=0, unauthorized_orders=0,
                                     broker_stable=True, max_drawdown_pct=5.0)
        result = gov.evaluate_promotion("T2-PROVISIONAL", evidence)
        assert result.verdict == PromotionVerdict.APPROVED

    def test_blocked_insufficient_stable_days(self):
        gov = CapitalTierGovernor()
        gov.activate_tier("T1-QUALIFICATION")
        evidence = PromotionEvidence(stable_days=3, broker_stable=True)
        result = gov.evaluate_promotion("T2-PROVISIONAL", evidence)
        assert result.verdict != PromotionVerdict.APPROVED

    def test_blocked_critical_incidents(self):
        gov = CapitalTierGovernor()
        gov.activate_tier("T1-QUALIFICATION")
        evidence = PromotionEvidence(stable_days=14, critical_incidents=1, broker_stable=True)
        result = gov.evaluate_promotion("T2-PROVISIONAL", evidence)
        assert result.verdict != PromotionVerdict.APPROVED

    def test_blocked_duplicate_orders(self):
        gov = CapitalTierGovernor()
        gov.activate_tier("T1-QUALIFICATION")
        evidence = PromotionEvidence(stable_days=14, duplicate_orders=1, broker_stable=True)
        result = gov.evaluate_promotion("T2-PROVISIONAL", evidence)
        assert result.verdict != PromotionVerdict.APPROVED

    def test_blocked_unauthorized_orders(self):
        gov = CapitalTierGovernor()
        gov.activate_tier("T1-QUALIFICATION")
        evidence = PromotionEvidence(stable_days=14, unauthorized_orders=1, broker_stable=True)
        result = gov.evaluate_promotion("T2-PROVISIONAL", evidence)
        assert result.verdict != PromotionVerdict.APPROVED

    def test_blocked_unstable_broker(self):
        gov = CapitalTierGovernor()
        gov.activate_tier("T1-QUALIFICATION")
        evidence = PromotionEvidence(stable_days=14, broker_stable=False)
        result = gov.evaluate_promotion("T2-PROVISIONAL", evidence)
        assert result.verdict != PromotionVerdict.APPROVED

    def test_blocked_historical_drawdown_exceeds(self):
        gov = CapitalTierGovernor()
        gov.activate_tier("T1-QUALIFICATION")
        evidence = PromotionEvidence(stable_days=14, broker_stable=True, max_drawdown_pct=25.0)
        result = gov.evaluate_promotion("T2-PROVISIONAL", evidence)
        assert result.verdict != PromotionVerdict.APPROVED

    def test_unknown_tier_blocked(self):
        gov = CapitalTierGovernor()
        gov.activate_tier("T1-QUALIFICATION")
        evidence = PromotionEvidence(stable_days=14, broker_stable=True)
        result = gov.evaluate_promotion("T99-FAKE", evidence)
        assert result.verdict == PromotionVerdict.BLOCKED

    def test_cannot_skip_tiers(self):
        gov = CapitalTierGovernor()
        gov.activate_tier("T1-QUALIFICATION")
        evidence = PromotionEvidence(stable_days=90, broker_stable=True)
        result = gov.evaluate_promotion("T3-CONTROLLED", evidence)
        assert result.verdict != PromotionVerdict.APPROVED
        assert any("skip" in r.lower() for r in result.blocking_reasons)


class TestPromotionExecution:
    def test_successful_promotion(self):
        gov = CapitalTierGovernor()
        gov.activate_tier("T1-QUALIFICATION")
        evidence = PromotionEvidence(stable_days=14, broker_stable=True, max_drawdown_pct=5.0)
        assert gov.promote("T2-PROVISIONAL", evidence) is True
        assert gov.active_tier.tier_id == "T2-PROVISIONAL"

    def test_failed_promotion_no_change(self):
        gov = CapitalTierGovernor()
        gov.activate_tier("T1-QUALIFICATION")
        evidence = PromotionEvidence(stable_days=1, broker_stable=True)
        assert gov.promote("T2-PROVISIONAL", evidence) is False
        assert gov.active_tier.tier_id == "T1-QUALIFICATION"


class TestAuditTrail:
    def test_activation_audited(self):
        gov = CapitalTierGovernor()
        gov.activate_tier("T1-QUALIFICATION")
        log = gov.get_audit_log()
        assert len(log) == 1
        assert log[0]["event"] == "TIER_ACTIVATED"

    def test_promotion_evaluated_audited(self):
        gov = CapitalTierGovernor()
        gov.activate_tier("T1-QUALIFICATION")
        evidence = PromotionEvidence(stable_days=14, broker_stable=True)
        gov.evaluate_promotion("T2-PROVISIONAL", evidence)
        log = gov.get_audit_log()
        assert any(e["event"] == "PROMOTION_EVALUATED" for e in log)

    def test_audit_log_bounded(self):
        gov = CapitalTierGovernor()
        gov.activate_tier("T1-QUALIFICATION")
        for _ in range(150):
            gov.evaluate_promotion("T2-PROVISIONAL", PromotionEvidence(stable_days=1))
        assert len(gov.get_audit_log()) <= 100


class TestStatus:
    def test_status_before_activation(self):
        gov = CapitalTierGovernor()
        status = gov.get_status()
        assert status["active_tier"] is None
        assert len(status["available_tiers"]) == len(ALL_TIERS)

    def test_status_after_activation(self):
        gov = CapitalTierGovernor()
        gov.activate_tier("T1-QUALIFICATION")
        status = gov.get_status()
        assert status["active_tier"] == "T1-QUALIFICATION"
        assert status["active_tier_fingerprint"] is not None
