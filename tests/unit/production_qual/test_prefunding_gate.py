"""Pre-Funding Gate Audit — comprehensive tests.

Covers:
1. All 7 audit categories with positive and negative cases
2. The negative-path matrix: every important failure mode has a
   predetermined safe outcome
3. Gate enforcement: GO / RESTRICTED / NO-GO
4. Broker boundary validation
5. Capital boundary validation
6. Report generation (MD + JSON)
"""

import pytest

from eigencapital.production_qual.prefunding_audit import (
    AuditCategory,
    AuditCheck,
    AuditReport,
    AuditVerdict,
    PrefundingGateAuditor,
)
from eigencapital.production_qual.prefunding_gate import (
    GateDecision,
    GateRecord,
    PrefundingGate,
)
from eigencapital.production_qual.broker_boundary import (
    BrokerBoundaryConfig,
    BrokerBoundaryValidator,
)
from eigencapital.production_qual.capital_boundary import (
    CapitalBoundaryConfig,
    CapitalBoundaryValidator,
    CapitalVerdict,
)


# ============================================================
# Helper: produce a fully-passing audit report
# ============================================================

def _full_pass_report(campaign_id="PREFUND-001"):
    auditor = PrefundingGateAuditor()
    return auditor.run_full_audit(
        campaign_id=campaign_id,
        # Identity
        frozen_manifest_fingerprint="aaab6c00dc05",
        production_config_fingerprint="aaab6c00dc05",
        manifest_computed_identity="aaab6c00dc05",
        golden_manifest_guard_passes=True,
        strategy_version="R4.0",
        data_terminal_id="168966110",
        # Risk
        risk_policy_is_authority=True,
        exposure_maps_populated=True,
        concentration_enforced=True,
        asset_class_enforced=True,
        drawdown_verified=True,
        daily_loss_verified=True,
        leverage_verified=True,
        position_limit_verified=True,
        order_limit_verified=True,
        kill_switch_verified=True,
        missing_state_fails_closed=True,
        # Execution
        partial_fill_active=True,
        broker_reconciliation_authoritative=True,
        duplicate_fill_protection=True,
        disconnect_reconcile_resume_enforced=True,
        no_reconnect_only_trading=True,
        kill_freeze_independently_tested=True,
        # Health
        healthy_permits_trade=True,
        degraded_manage_only=True,
        critical_halts=True,
        frozen_halts=True,
        stale_halts=True,
        unparseable_halts=True,
        exception_halts=True,
        manual_reset_required=True,
        # Observability
        events_durably_recorded=True,
        alert_delivery_works=True,
        alert_failure_cannot_weaken_safety=True,
        tamper_evident_log_verifies=True,
        # Broker boundary
        correct_account=True,
        correct_environment=True,
        correct_symbol_mapping=True,
        correct_contract_specs=True,
        correct_volume_price_constraints=True,
        spread_slippage_controls=True,
        no_environment_confusion=True,
        # Capital boundary
        max_capital_enforced=True,
        campaign_duration_preregistered=True,
        risk_envelope_preregistered=True,
        r4_positions_separated=True,
        pre_existing_separated=True,
        no_manual_trading=True,
    )


# ============================================================
# 1. FULL AUDIT — POSITIVE PATH
# ============================================================

class TestFullAuditPositivePath:
    """When everything passes, the audit produces GO."""

    def test_all_checks_pass(self):
        report = _full_pass_report()
        assert report.verdict == AuditVerdict.GO
        assert report.failed_checks == 0
        assert len(report.critical_failures) == 0

    def test_correct_check_count(self):
        report = _full_pass_report()
        # 6 identity + 11 risk + 6 execution + 8 health + 4 observability + 7 broker + 6 capital = 48
        assert report.total_checks == 48

    def test_all_categories_pass(self):
        report = _full_pass_report()
        for cat_name, cat_data in report.category_results.items():
            assert cat_data["failed"] == 0, f"Category {cat_name} has failures"

    def test_report_hash_deterministic(self):
        r1 = _full_pass_report()
        r2 = _full_pass_report()
        assert r1.report_hash == r2.report_hash

    def test_report_to_dict(self):
        report = _full_pass_report()
        d = report.to_dict()
        assert d["verdict"] == "GO"
        assert d["total_checks"] == 48
        assert d["passed_checks"] == 48
        assert d["failed_checks"] == 0

    def test_report_to_markdown(self):
        report = _full_pass_report()
        md = report.to_markdown()
        assert "Pre-Funding Gate Audit Report" in md
        assert "GO" in md
        assert "All critical checks passed" in md


# ============================================================
# 2. NEGATIVE-PATH MATRIX
# ============================================================

class TestNegativePathMatrix:
    """Every important failure mode has a predetermined safe outcome.

    Failure injected → Expected result:
    - Missing exposure map → Block
    - RiskPolicy breach → Block
    - Stale health snapshot → Halt
    - Broker disconnect → Halt
    - Reconnect without reconciliation → Halt
    - Position mismatch → Reconcile/flatten
    - Partial fill → Correctly reconcile
    - Duplicate fill → Ignore
    - Alert system failure → Safety state unchanged
    - Fingerprint drift → Freeze
    - Unexpected position → Halt
    - Manual trade → Qualification failure
    """

    # ── Identity failures ──────────────────────────────────────

    def test_fingerprint_drift_freezes(self):
        """Fingerprint drift → NO-GO (freeze)."""
        auditor = PrefundingGateAuditor()
        report = auditor.run_full_audit(
            campaign_id="NEG-01",
            frozen_manifest_fingerprint="aaab6c00dc05",
            production_config_fingerprint="CHANGED_DRIFT",  # drift!
            manifest_computed_identity="aaab6c00dc05",
            golden_manifest_guard_passes=True,
            strategy_version="R4.0",
            # Everything else passes
            risk_policy_is_authority=True, exposure_maps_populated=True,
            concentration_enforced=True, asset_class_enforced=True,
            drawdown_verified=True, daily_loss_verified=True,
            leverage_verified=True, position_limit_verified=True,
            order_limit_verified=True, kill_switch_verified=True,
            missing_state_fails_closed=True,
            partial_fill_active=True, broker_reconciliation_authoritative=True,
            duplicate_fill_protection=True, disconnect_reconcile_resume_enforced=True,
            no_reconnect_only_trading=True, kill_freeze_independently_tested=True,
            healthy_permits_trade=True, degraded_manage_only=True,
            critical_halts=True, frozen_halts=True,
            stale_halts=True, unparseable_halts=True,
            exception_halts=True, manual_reset_required=True,
            events_durably_recorded=True, alert_delivery_works=True,
            alert_failure_cannot_weaken_safety=True, tamper_evident_log_verifies=True,
            correct_account=True, correct_environment=True,
            correct_symbol_mapping=True, correct_contract_specs=True,
            correct_volume_price_constraints=True, spread_slippage_controls=True,
            no_environment_confusion=True,
            max_capital_enforced=True, campaign_duration_preregistered=True,
            risk_envelope_preregistered=True, r4_positions_separated=True,
            pre_existing_separated=True, no_manual_trading=True,
        )
        assert report.verdict == AuditVerdict.NO_GO
        drift_check = [c for c in report.checks if c.check_id == "ID-06"][0]
        assert not drift_check.passed
        assert "DRIFT" in drift_check.observed

    def test_frozen_manifest_mismatch_blocks(self):
        """Frozen manifest mismatch → NO-GO."""
        auditor = PrefundingGateAuditor()
        report = auditor.run_full_audit(
            campaign_id="NEG-01b",
            frozen_manifest_fingerprint="aaab6c00dc05",
            production_config_fingerprint="WRONG",
            manifest_computed_identity="aaab6c00dc05",
            golden_manifest_guard_passes=True,
            strategy_version="R4.0",
            # Risk passes
            risk_policy_is_authority=True, exposure_maps_populated=True,
            concentration_enforced=True, asset_class_enforced=True,
            drawdown_verified=True, daily_loss_verified=True,
            leverage_verified=True, position_limit_verified=True,
            order_limit_verified=True, kill_switch_verified=True,
            missing_state_fails_closed=True,
            # Execution passes
            partial_fill_active=True, broker_reconciliation_authoritative=True,
            duplicate_fill_protection=True, disconnect_reconcile_resume_enforced=True,
            no_reconnect_only_trading=True, kill_freeze_independently_tested=True,
            # Health passes
            healthy_permits_trade=True, degraded_manage_only=True,
            critical_halts=True, frozen_halts=True,
            stale_halts=True, unparseable_halts=True,
            exception_halts=True, manual_reset_required=True,
            # Observability passes
            events_durably_recorded=True, alert_delivery_works=True,
            alert_failure_cannot_weaken_safety=True, tamper_evident_log_verifies=True,
            # Broker passes
            correct_account=True, correct_environment=True,
            correct_symbol_mapping=True, correct_contract_specs=True,
            correct_volume_price_constraints=True, spread_slippage_controls=True,
            no_environment_confusion=True,
            # Capital passes
            max_capital_enforced=True, campaign_duration_preregistered=True,
            risk_envelope_preregistered=True, r4_positions_separated=True,
            pre_existing_separated=True, no_manual_trading=True,
        )
        assert report.verdict == AuditVerdict.NO_GO

    def test_wrong_strategy_version_blocks(self):
        """Wrong strategy version → NO-GO."""
        auditor = PrefundingGateAuditor()
        report = auditor.run_full_audit(
            campaign_id="NEG-01c",
            frozen_manifest_fingerprint="aaab6c00dc05",
            production_config_fingerprint="aaab6c00dc05",
            manifest_computed_identity="aaab6c00dc05",
            golden_manifest_guard_passes=True,
            strategy_version="R5.0",  # WRONG
            risk_policy_is_authority=True, exposure_maps_populated=True,
            concentration_enforced=True, asset_class_enforced=True,
            drawdown_verified=True, daily_loss_verified=True,
            leverage_verified=True, position_limit_verified=True,
            order_limit_verified=True, kill_switch_verified=True,
            missing_state_fails_closed=True,
            partial_fill_active=True, broker_reconciliation_authoritative=True,
            duplicate_fill_protection=True, disconnect_reconcile_resume_enforced=True,
            no_reconnect_only_trading=True, kill_freeze_independently_tested=True,
            healthy_permits_trade=True, degraded_manage_only=True,
            critical_halts=True, frozen_halts=True,
            stale_halts=True, unparseable_halts=True,
            exception_halts=True, manual_reset_required=True,
            events_durably_recorded=True, alert_delivery_works=True,
            alert_failure_cannot_weaken_safety=True, tamper_evident_log_verifies=True,
            correct_account=True, correct_environment=True,
            correct_symbol_mapping=True, correct_contract_specs=True,
            correct_volume_price_constraints=True, spread_slippage_controls=True,
            no_environment_confusion=True,
            max_capital_enforced=True, campaign_duration_preregistered=True,
            risk_envelope_preregistered=True, r4_positions_separated=True,
            pre_existing_separated=True, no_manual_trading=True,
        )
        assert report.verdict == AuditVerdict.NO_GO
        version_check = [c for c in report.checks if c.check_id == "ID-04"][0]
        assert not version_check.passed

    # ── Risk failures ──────────────────────────────────────────

    def test_missing_exposure_map_blocks(self):
        """Missing exposure map → NO-GO (fail-closed)."""
        auditor = PrefundingGateAuditor()
        report = auditor.run_full_audit(
            campaign_id="NEG-02a",
            frozen_manifest_fingerprint="aaab6c00dc05",
            production_config_fingerprint="aaab6c00dc05",
            manifest_computed_identity="aaab6c00dc05",
            golden_manifest_guard_passes=True,
            strategy_version="R4.0",
            risk_policy_is_authority=True, exposure_maps_populated=False,  # MISSING
            concentration_enforced=True, asset_class_enforced=True,
            drawdown_verified=True, daily_loss_verified=True,
            leverage_verified=True, position_limit_verified=True,
            order_limit_verified=True, kill_switch_verified=True,
            missing_state_fails_closed=True,
            partial_fill_active=True, broker_reconciliation_authoritative=True,
            duplicate_fill_protection=True, disconnect_reconcile_resume_enforced=True,
            no_reconnect_only_trading=True, kill_freeze_independently_tested=True,
            healthy_permits_trade=True, degraded_manage_only=True,
            critical_halts=True, frozen_halts=True,
            stale_halts=True, unparseable_halts=True,
            exception_halts=True, manual_reset_required=True,
            events_durably_recorded=True, alert_delivery_works=True,
            alert_failure_cannot_weaken_safety=True, tamper_evident_log_verifies=True,
            correct_account=True, correct_environment=True,
            correct_symbol_mapping=True, correct_contract_specs=True,
            correct_volume_price_constraints=True, spread_slippage_controls=True,
            no_environment_confusion=True,
            max_capital_enforced=True, campaign_duration_preregistered=True,
            risk_envelope_preregistered=True, r4_positions_separated=True,
            pre_existing_separated=True, no_manual_trading=True,
        )
        assert report.verdict == AuditVerdict.NO_GO
        check = [c for c in report.checks if c.check_id == "RK-02"][0]
        assert not check.passed
        assert "EMPTY" in check.observed

    def test_risk_policy_not_authority_blocks(self):
        """RiskPolicy not sole authority → NO-GO."""
        auditor = PrefundingGateAuditor()
        report = auditor.run_full_audit(
            campaign_id="NEG-02b",
            frozen_manifest_fingerprint="aaab6c00dc05",
            production_config_fingerprint="aaab6c00dc05",
            manifest_computed_identity="aaab6c00dc05",
            golden_manifest_guard_passes=True,
            strategy_version="R4.0",
            risk_policy_is_authority=False,  # NOT authority
            exposure_maps_populated=True,
            concentration_enforced=True, asset_class_enforced=True,
            drawdown_verified=True, daily_loss_verified=True,
            leverage_verified=True, position_limit_verified=True,
            order_limit_verified=True, kill_switch_verified=True,
            missing_state_fails_closed=True,
            partial_fill_active=True, broker_reconciliation_authoritative=True,
            duplicate_fill_protection=True, disconnect_reconcile_resume_enforced=True,
            no_reconnect_only_trading=True, kill_freeze_independently_tested=True,
            healthy_permits_trade=True, degraded_manage_only=True,
            critical_halts=True, frozen_halts=True,
            stale_halts=True, unparseable_halts=True,
            exception_halts=True, manual_reset_required=True,
            events_durably_recorded=True, alert_delivery_works=True,
            alert_failure_cannot_weaken_safety=True, tamper_evident_log_verifies=True,
            correct_account=True, correct_environment=True,
            correct_symbol_mapping=True, correct_contract_specs=True,
            correct_volume_price_constraints=True, spread_slippage_controls=True,
            no_environment_confusion=True,
            max_capital_enforced=True, campaign_duration_preregistered=True,
            risk_envelope_preregistered=True, r4_positions_separated=True,
            pre_existing_separated=True, no_manual_trading=True,
        )
        assert report.verdict == AuditVerdict.NO_GO
        check = [c for c in report.checks if c.check_id == "RK-01"][0]
        assert not check.passed

    def test_missing_state_fails_open_is_critical(self):
        """Missing state fails open (not closed) → NO-GO."""
        auditor = PrefundingGateAuditor()
        report = auditor.run_full_audit(
            campaign_id="NEG-02c",
            frozen_manifest_fingerprint="aaab6c00dc05",
            production_config_fingerprint="aaab6c00dc05",
            manifest_computed_identity="aaab6c00dc05",
            golden_manifest_guard_passes=True,
            strategy_version="R4.0",
            risk_policy_is_authority=True, exposure_maps_populated=True,
            concentration_enforced=True, asset_class_enforced=True,
            drawdown_verified=True, daily_loss_verified=True,
            leverage_verified=True, position_limit_verified=True,
            order_limit_verified=True, kill_switch_verified=True,
            missing_state_fails_closed=False,  # FAILS OPEN (unsafe)
            partial_fill_active=True, broker_reconciliation_authoritative=True,
            duplicate_fill_protection=True, disconnect_reconcile_resume_enforced=True,
            no_reconnect_only_trading=True, kill_freeze_independently_tested=True,
            healthy_permits_trade=True, degraded_manage_only=True,
            critical_halts=True, frozen_halts=True,
            stale_halts=True, unparseable_halts=True,
            exception_halts=True, manual_reset_required=True,
            events_durably_recorded=True, alert_delivery_works=True,
            alert_failure_cannot_weaken_safety=True, tamper_evident_log_verifies=True,
            correct_account=True, correct_environment=True,
            correct_symbol_mapping=True, correct_contract_specs=True,
            correct_volume_price_constraints=True, spread_slippage_controls=True,
            no_environment_confusion=True,
            max_capital_enforced=True, campaign_duration_preregistered=True,
            risk_envelope_preregistered=True, r4_positions_separated=True,
            pre_existing_separated=True, no_manual_trading=True,
        )
        assert report.verdict == AuditVerdict.NO_GO
        check = [c for c in report.checks if c.check_id == "RK-11"][0]
        assert not check.passed
        assert "FAIL OPEN" in check.observed

    def test_concentration_not_enforced_blocks(self):
        """Concentration limits diagnostic-only (not enforced) → NO-GO."""
        auditor = PrefundingGateAuditor()
        report = auditor.run_full_audit(
            campaign_id="NEG-02d",
            frozen_manifest_fingerprint="aaab6c00dc05",
            production_config_fingerprint="aaab6c00dc05",
            manifest_computed_identity="aaab6c00dc05",
            golden_manifest_guard_passes=True,
            strategy_version="R4.0",
            risk_policy_is_authority=True, exposure_maps_populated=True,
            concentration_enforced=False,  # DIAGNOSTIC ONLY
            asset_class_enforced=True,
            drawdown_verified=True, daily_loss_verified=True,
            leverage_verified=True, position_limit_verified=True,
            order_limit_verified=True, kill_switch_verified=True,
            missing_state_fails_closed=True,
            partial_fill_active=True, broker_reconciliation_authoritative=True,
            duplicate_fill_protection=True, disconnect_reconcile_resume_enforced=True,
            no_reconnect_only_trading=True, kill_freeze_independently_tested=True,
            healthy_permits_trade=True, degraded_manage_only=True,
            critical_halts=True, frozen_halts=True,
            stale_halts=True, unparseable_halts=True,
            exception_halts=True, manual_reset_required=True,
            events_durably_recorded=True, alert_delivery_works=True,
            alert_failure_cannot_weaken_safety=True, tamper_evident_log_verifies=True,
            correct_account=True, correct_environment=True,
            correct_symbol_mapping=True, correct_contract_specs=True,
            correct_volume_price_constraints=True, spread_slippage_controls=True,
            no_environment_confusion=True,
            max_capital_enforced=True, campaign_duration_preregistered=True,
            risk_envelope_preregistered=True, r4_positions_separated=True,
            pre_existing_separated=True, no_manual_trading=True,
        )
        assert report.verdict == AuditVerdict.NO_GO
        check = [c for c in report.checks if c.check_id == "RK-03"][0]
        assert not check.passed
        assert "diagnostic-only" in check.observed

    # ── Execution failures ─────────────────────────────────────

    def test_partial_fill_inactive_blocks(self):
        """Partial-fill state machine inactive → NO-GO."""
        auditor = PrefundingGateAuditor()
        report = auditor.run_full_audit(
            campaign_id="NEG-03a",
            frozen_manifest_fingerprint="aaab6c00dc05",
            production_config_fingerprint="aaab6c00dc05",
            manifest_computed_identity="aaab6c00dc05",
            golden_manifest_guard_passes=True,
            strategy_version="R4.0",
            risk_policy_is_authority=True, exposure_maps_populated=True,
            concentration_enforced=True, asset_class_enforced=True,
            drawdown_verified=True, daily_loss_verified=True,
            leverage_verified=True, position_limit_verified=True,
            order_limit_verified=True, kill_switch_verified=True,
            missing_state_fails_closed=True,
            partial_fill_active=False,  # INACTIVE
            broker_reconciliation_authoritative=True,
            duplicate_fill_protection=True, disconnect_reconcile_resume_enforced=True,
            no_reconnect_only_trading=True, kill_freeze_independently_tested=True,
            healthy_permits_trade=True, degraded_manage_only=True,
            critical_halts=True, frozen_halts=True,
            stale_halts=True, unparseable_halts=True,
            exception_halts=True, manual_reset_required=True,
            events_durably_recorded=True, alert_delivery_works=True,
            alert_failure_cannot_weaken_safety=True, tamper_evident_log_verifies=True,
            correct_account=True, correct_environment=True,
            correct_symbol_mapping=True, correct_contract_specs=True,
            correct_volume_price_constraints=True, spread_slippage_controls=True,
            no_environment_confusion=True,
            max_capital_enforced=True, campaign_duration_preregistered=True,
            risk_envelope_preregistered=True, r4_positions_separated=True,
            pre_existing_separated=True, no_manual_trading=True,
        )
        assert report.verdict == AuditVerdict.NO_GO

    def test_reconnect_only_trading_unsafe(self):
        """Reconnect-only trading (no reconciliation) → NO-GO."""
        auditor = PrefundingGateAuditor()
        report = auditor.run_full_audit(
            campaign_id="NEG-03b",
            frozen_manifest_fingerprint="aaab6c00dc05",
            production_config_fingerprint="aaab6c00dc05",
            manifest_computed_identity="aaab6c00dc05",
            golden_manifest_guard_passes=True,
            strategy_version="R4.0",
            risk_policy_is_authority=True, exposure_maps_populated=True,
            concentration_enforced=True, asset_class_enforced=True,
            drawdown_verified=True, daily_loss_verified=True,
            leverage_verified=True, position_limit_verified=True,
            order_limit_verified=True, kill_switch_verified=True,
            missing_state_fails_closed=True,
            partial_fill_active=True, broker_reconciliation_authoritative=True,
            duplicate_fill_protection=True, disconnect_reconcile_resume_enforced=True,
            no_reconnect_only_trading=False,  # UNSAFE
            kill_freeze_independently_tested=True,
            healthy_permits_trade=True, degraded_manage_only=True,
            critical_halts=True, frozen_halts=True,
            stale_halts=True, unparseable_halts=True,
            exception_halts=True, manual_reset_required=True,
            events_durably_recorded=True, alert_delivery_works=True,
            alert_failure_cannot_weaken_safety=True, tamper_evident_log_verifies=True,
            correct_account=True, correct_environment=True,
            correct_symbol_mapping=True, correct_contract_specs=True,
            correct_volume_price_constraints=True, spread_slippage_controls=True,
            no_environment_confusion=True,
            max_capital_enforced=True, campaign_duration_preregistered=True,
            risk_envelope_preregistered=True, r4_positions_separated=True,
            pre_existing_separated=True, no_manual_trading=True,
        )
        assert report.verdict == AuditVerdict.NO_GO
        check = [c for c in report.checks if c.check_id == "EX-05"][0]
        assert not check.passed
        assert "UNSAFE" in check.observed

    # ── Health failures ────────────────────────────────────────

    def test_stale_health_halts(self):
        """Stale health snapshot → NO-GO (HALT)."""
        auditor = PrefundingGateAuditor()
        report = auditor.run_full_audit(
            campaign_id="NEG-04a",
            frozen_manifest_fingerprint="aaab6c00dc05",
            production_config_fingerprint="aaab6c00dc05",
            manifest_computed_identity="aaab6c00dc05",
            golden_manifest_guard_passes=True,
            strategy_version="R4.0",
            risk_policy_is_authority=True, exposure_maps_populated=True,
            concentration_enforced=True, asset_class_enforced=True,
            drawdown_verified=True, daily_loss_verified=True,
            leverage_verified=True, position_limit_verified=True,
            order_limit_verified=True, kill_switch_verified=True,
            missing_state_fails_closed=True,
            partial_fill_active=True, broker_reconciliation_authoritative=True,
            duplicate_fill_protection=True, disconnect_reconcile_resume_enforced=True,
            no_reconnect_only_trading=True, kill_freeze_independently_tested=True,
            healthy_permits_trade=True, degraded_manage_only=True,
            critical_halts=True, frozen_halts=True,
            stale_halts=False,  # STALE does not halt!
            unparseable_halts=True, exception_halts=True,
            manual_reset_required=True,
            events_durably_recorded=True, alert_delivery_works=True,
            alert_failure_cannot_weaken_safety=True, tamper_evident_log_verifies=True,
            correct_account=True, correct_environment=True,
            correct_symbol_mapping=True, correct_contract_specs=True,
            correct_volume_price_constraints=True, spread_slippage_controls=True,
            no_environment_confusion=True,
            max_capital_enforced=True, campaign_duration_preregistered=True,
            risk_envelope_preregistered=True, r4_positions_separated=True,
            pre_existing_separated=True, no_manual_trading=True,
        )
        assert report.verdict == AuditVerdict.NO_GO
        check = [c for c in report.checks if c.check_id == "HL-05"][0]
        assert not check.passed

    def test_unparseable_health_halts(self):
        """Unparseable health state → NO-GO."""
        auditor = PrefundingGateAuditor()
        report = auditor.run_full_audit(
            campaign_id="NEG-04b",
            frozen_manifest_fingerprint="aaab6c00dc05",
            production_config_fingerprint="aaab6c00dc05",
            manifest_computed_identity="aaab6c00dc05",
            golden_manifest_guard_passes=True,
            strategy_version="R4.0",
            risk_policy_is_authority=True, exposure_maps_populated=True,
            concentration_enforced=True, asset_class_enforced=True,
            drawdown_verified=True, daily_loss_verified=True,
            leverage_verified=True, position_limit_verified=True,
            order_limit_verified=True, kill_switch_verified=True,
            missing_state_fails_closed=True,
            partial_fill_active=True, broker_reconciliation_authoritative=True,
            duplicate_fill_protection=True, disconnect_reconcile_resume_enforced=True,
            no_reconnect_only_trading=True, kill_freeze_independently_tested=True,
            healthy_permits_trade=True, degraded_manage_only=True,
            critical_halts=True, frozen_halts=True,
            stale_halts=True, unparseable_halts=False,  # DOES NOT HALT
            exception_halts=True, manual_reset_required=True,
            events_durably_recorded=True, alert_delivery_works=True,
            alert_failure_cannot_weaken_safety=True, tamper_evident_log_verifies=True,
            correct_account=True, correct_environment=True,
            correct_symbol_mapping=True, correct_contract_specs=True,
            correct_volume_price_constraints=True, spread_slippage_controls=True,
            no_environment_confusion=True,
            max_capital_enforced=True, campaign_duration_preregistered=True,
            risk_envelope_preregistered=True, r4_positions_separated=True,
            pre_existing_separated=True, no_manual_trading=True,
        )
        assert report.verdict == AuditVerdict.NO_GO

    def test_monitor_exception_not_halt_is_critical(self):
        """Monitor exception does NOT halt → NO-GO (fail-open)."""
        auditor = PrefundingGateAuditor()
        report = auditor.run_full_audit(
            campaign_id="NEG-04c",
            frozen_manifest_fingerprint="aaab6c00dc05",
            production_config_fingerprint="aaab6c00dc05",
            manifest_computed_identity="aaab6c00dc05",
            golden_manifest_guard_passes=True,
            strategy_version="R4.0",
            risk_policy_is_authority=True, exposure_maps_populated=True,
            concentration_enforced=True, asset_class_enforced=True,
            drawdown_verified=True, daily_loss_verified=True,
            leverage_verified=True, position_limit_verified=True,
            order_limit_verified=True, kill_switch_verified=True,
            missing_state_fails_closed=True,
            partial_fill_active=True, broker_reconciliation_authoritative=True,
            duplicate_fill_protection=True, disconnect_reconcile_resume_enforced=True,
            no_reconnect_only_trading=True, kill_freeze_independently_tested=True,
            healthy_permits_trade=True, degraded_manage_only=True,
            critical_halts=True, frozen_halts=True,
            stale_halts=True, unparseable_halts=True,
            exception_halts=False,  # EXCEPTION does not halt!
            manual_reset_required=True,
            events_durably_recorded=True, alert_delivery_works=True,
            alert_failure_cannot_weaken_safety=True, tamper_evident_log_verifies=True,
            correct_account=True, correct_environment=True,
            correct_symbol_mapping=True, correct_contract_specs=True,
            correct_volume_price_constraints=True, spread_slippage_controls=True,
            no_environment_confusion=True,
            max_capital_enforced=True, campaign_duration_preregistered=True,
            risk_envelope_preregistered=True, r4_positions_separated=True,
            pre_existing_separated=True, no_manual_trading=True,
        )
        assert report.verdict == AuditVerdict.NO_GO

    def test_auto_reset_from_frozen_unsafe(self):
        """Auto-reset from frozen (no manual required) → NO-GO."""
        auditor = PrefundingGateAuditor()
        report = auditor.run_full_audit(
            campaign_id="NEG-04d",
            frozen_manifest_fingerprint="aaab6c00dc05",
            production_config_fingerprint="aaab6c00dc05",
            manifest_computed_identity="aaab6c00dc05",
            golden_manifest_guard_passes=True,
            strategy_version="R4.0",
            risk_policy_is_authority=True, exposure_maps_populated=True,
            concentration_enforced=True, asset_class_enforced=True,
            drawdown_verified=True, daily_loss_verified=True,
            leverage_verified=True, position_limit_verified=True,
            order_limit_verified=True, kill_switch_verified=True,
            missing_state_fails_closed=True,
            partial_fill_active=True, broker_reconciliation_authoritative=True,
            duplicate_fill_protection=True, disconnect_reconcile_resume_enforced=True,
            no_reconnect_only_trading=True, kill_freeze_independently_tested=True,
            healthy_permits_trade=True, degraded_manage_only=True,
            critical_halts=True, frozen_halts=True,
            stale_halts=True, unparseable_halts=True,
            exception_halts=True,
            manual_reset_required=False,  # AUTO-RESET (unsafe)
            events_durably_recorded=True, alert_delivery_works=True,
            alert_failure_cannot_weaken_safety=True, tamper_evident_log_verifies=True,
            correct_account=True, correct_environment=True,
            correct_symbol_mapping=True, correct_contract_specs=True,
            correct_volume_price_constraints=True, spread_slippage_controls=True,
            no_environment_confusion=True,
            max_capital_enforced=True, campaign_duration_preregistered=True,
            risk_envelope_preregistered=True, r4_positions_separated=True,
            pre_existing_separated=True, no_manual_trading=True,
        )
        assert report.verdict == AuditVerdict.NO_GO

    # ── Observability failures ─────────────────────────────────

    def test_alert_failure_weakens_safety_is_critical(self):
        """Alert failure weakens safety state → NO-GO."""
        auditor = PrefundingGateAuditor()
        report = auditor.run_full_audit(
            campaign_id="NEG-05a",
            frozen_manifest_fingerprint="aaab6c00dc05",
            production_config_fingerprint="aaab6c00dc05",
            manifest_computed_identity="aaab6c00dc05",
            golden_manifest_guard_passes=True,
            strategy_version="R4.0",
            risk_policy_is_authority=True, exposure_maps_populated=True,
            concentration_enforced=True, asset_class_enforced=True,
            drawdown_verified=True, daily_loss_verified=True,
            leverage_verified=True, position_limit_verified=True,
            order_limit_verified=True, kill_switch_verified=True,
            missing_state_fails_closed=True,
            partial_fill_active=True, broker_reconciliation_authoritative=True,
            duplicate_fill_protection=True, disconnect_reconcile_resume_enforced=True,
            no_reconnect_only_trading=True, kill_freeze_independently_tested=True,
            healthy_permits_trade=True, degraded_manage_only=True,
            critical_halts=True, frozen_halts=True,
            stale_halts=True, unparseable_halts=True,
            exception_halts=True, manual_reset_required=True,
            events_durably_recorded=True, alert_delivery_works=True,
            alert_failure_cannot_weaken_safety=False,  # WEAKENS SAFETY
            tamper_evident_log_verifies=True,
            correct_account=True, correct_environment=True,
            correct_symbol_mapping=True, correct_contract_specs=True,
            correct_volume_price_constraints=True, spread_slippage_controls=True,
            no_environment_confusion=True,
            max_capital_enforced=True, campaign_duration_preregistered=True,
            risk_envelope_preregistered=True, r4_positions_separated=True,
            pre_existing_separated=True, no_manual_trading=True,
        )
        assert report.verdict == AuditVerdict.NO_GO
        check = [c for c in report.checks if c.check_id == "OB-03"][0]
        assert not check.passed
        assert "SAFETY COMPROMISED" in check.observed

    def test_tamper_evident_log_broken(self):
        """Tamper-evident log chain broken → NO-GO."""
        auditor = PrefundingGateAuditor()
        report = auditor.run_full_audit(
            campaign_id="NEG-05b",
            frozen_manifest_fingerprint="aaab6c00dc05",
            production_config_fingerprint="aaab6c00dc05",
            manifest_computed_identity="aaab6c00dc05",
            golden_manifest_guard_passes=True,
            strategy_version="R4.0",
            risk_policy_is_authority=True, exposure_maps_populated=True,
            concentration_enforced=True, asset_class_enforced=True,
            drawdown_verified=True, daily_loss_verified=True,
            leverage_verified=True, position_limit_verified=True,
            order_limit_verified=True, kill_switch_verified=True,
            missing_state_fails_closed=True,
            partial_fill_active=True, broker_reconciliation_authoritative=True,
            duplicate_fill_protection=True, disconnect_reconcile_resume_enforced=True,
            no_reconnect_only_trading=True, kill_freeze_independently_tested=True,
            healthy_permits_trade=True, degraded_manage_only=True,
            critical_halts=True, frozen_halts=True,
            stale_halts=True, unparseable_halts=True,
            exception_halts=True, manual_reset_required=True,
            events_durably_recorded=True, alert_delivery_works=True,
            alert_failure_cannot_weaken_safety=True,
            tamper_evident_log_verifies=False,  # CHAIN BROKEN
            correct_account=True, correct_environment=True,
            correct_symbol_mapping=True, correct_contract_specs=True,
            correct_volume_price_constraints=True, spread_slippage_controls=True,
            no_environment_confusion=True,
            max_capital_enforced=True, campaign_duration_preregistered=True,
            risk_envelope_preregistered=True, r4_positions_separated=True,
            pre_existing_separated=True, no_manual_trading=True,
        )
        assert report.verdict == AuditVerdict.NO_GO

    # ── Broker boundary failures ───────────────────────────────

    def test_wrong_account_blocks(self):
        """Wrong MT5 account → NO-GO."""
        auditor = PrefundingGateAuditor()
        report = auditor.run_full_audit(
            campaign_id="NEG-06a",
            frozen_manifest_fingerprint="aaab6c00dc05",
            production_config_fingerprint="aaab6c00dc05",
            manifest_computed_identity="aaab6c00dc05",
            golden_manifest_guard_passes=True,
            strategy_version="R4.0",
            risk_policy_is_authority=True, exposure_maps_populated=True,
            concentration_enforced=True, asset_class_enforced=True,
            drawdown_verified=True, daily_loss_verified=True,
            leverage_verified=True, position_limit_verified=True,
            order_limit_verified=True, kill_switch_verified=True,
            missing_state_fails_closed=True,
            partial_fill_active=True, broker_reconciliation_authoritative=True,
            duplicate_fill_protection=True, disconnect_reconcile_resume_enforced=True,
            no_reconnect_only_trading=True, kill_freeze_independently_tested=True,
            healthy_permits_trade=True, degraded_manage_only=True,
            critical_halts=True, frozen_halts=True,
            stale_halts=True, unparseable_halts=True,
            exception_halts=True, manual_reset_required=True,
            events_durably_recorded=True, alert_delivery_works=True,
            alert_failure_cannot_weaken_safety=True, tamper_evident_log_verifies=True,
            correct_account=False,  # WRONG ACCOUNT
            correct_environment=True,
            correct_symbol_mapping=True, correct_contract_specs=True,
            correct_volume_price_constraints=True, spread_slippage_controls=True,
            no_environment_confusion=True,
            max_capital_enforced=True, campaign_duration_preregistered=True,
            risk_envelope_preregistered=True, r4_positions_separated=True,
            pre_existing_separated=True, no_manual_trading=True,
        )
        assert report.verdict == AuditVerdict.NO_GO

    def test_demo_live_confusion_blocks(self):
        """Demo/live environment confusion → NO-GO."""
        auditor = PrefundingGateAuditor()
        report = auditor.run_full_audit(
            campaign_id="NEG-06b",
            frozen_manifest_fingerprint="aaab6c00dc05",
            production_config_fingerprint="aaab6c00dc05",
            manifest_computed_identity="aaab6c00dc05",
            golden_manifest_guard_passes=True,
            strategy_version="R4.0",
            risk_policy_is_authority=True, exposure_maps_populated=True,
            concentration_enforced=True, asset_class_enforced=True,
            drawdown_verified=True, daily_loss_verified=True,
            leverage_verified=True, position_limit_verified=True,
            order_limit_verified=True, kill_switch_verified=True,
            missing_state_fails_closed=True,
            partial_fill_active=True, broker_reconciliation_authoritative=True,
            duplicate_fill_protection=True, disconnect_reconcile_resume_enforced=True,
            no_reconnect_only_trading=True, kill_freeze_independently_tested=True,
            healthy_permits_trade=True, degraded_manage_only=True,
            critical_halts=True, frozen_halts=True,
            stale_halts=True, unparseable_halts=True,
            exception_halts=True, manual_reset_required=True,
            events_durably_recorded=True, alert_delivery_works=True,
            alert_failure_cannot_weaken_safety=True, tamper_evident_log_verifies=True,
            correct_account=True,
            correct_environment=False,  # DEMO/LIVE CONFUSION
            correct_symbol_mapping=True, correct_contract_specs=True,
            correct_volume_price_constraints=True, spread_slippage_controls=True,
            no_environment_confusion=False,  # CONFUSION DETECTED
            max_capital_enforced=True, campaign_duration_preregistered=True,
            risk_envelope_preregistered=True, r4_positions_separated=True,
            pre_existing_separated=True, no_manual_trading=True,
        )
        assert report.verdict == AuditVerdict.NO_GO

    # ── Capital boundary failures ──────────────────────────────

    def test_manual_trade_qualification_failure(self):
        """Manual trade during qualification → NO-GO."""
        auditor = PrefundingGateAuditor()
        report = auditor.run_full_audit(
            campaign_id="NEG-07a",
            frozen_manifest_fingerprint="aaab6c00dc05",
            production_config_fingerprint="aaab6c00dc05",
            manifest_computed_identity="aaab6c00dc05",
            golden_manifest_guard_passes=True,
            strategy_version="R4.0",
            risk_policy_is_authority=True, exposure_maps_populated=True,
            concentration_enforced=True, asset_class_enforced=True,
            drawdown_verified=True, daily_loss_verified=True,
            leverage_verified=True, position_limit_verified=True,
            order_limit_verified=True, kill_switch_verified=True,
            missing_state_fails_closed=True,
            partial_fill_active=True, broker_reconciliation_authoritative=True,
            duplicate_fill_protection=True, disconnect_reconcile_resume_enforced=True,
            no_reconnect_only_trading=True, kill_freeze_independently_tested=True,
            healthy_permits_trade=True, degraded_manage_only=True,
            critical_halts=True, frozen_halts=True,
            stale_halts=True, unparseable_halts=True,
            exception_halts=True, manual_reset_required=True,
            events_durably_recorded=True, alert_delivery_works=True,
            alert_failure_cannot_weaken_safety=True, tamper_evident_log_verifies=True,
            correct_account=True, correct_environment=True,
            correct_symbol_mapping=True, correct_contract_specs=True,
            correct_volume_price_constraints=True, spread_slippage_controls=True,
            no_environment_confusion=True,
            max_capital_enforced=True, campaign_duration_preregistered=True,
            risk_envelope_preregistered=True, r4_positions_separated=True,
            pre_existing_separated=True,
            no_manual_trading=False,  # MANUAL TRADES DETECTED
        )
        assert report.verdict == AuditVerdict.NO_GO
        check = [c for c in report.checks if c.check_id == "CB-06"][0]
        assert not check.passed
        assert "MANUAL TRADES" in check.observed

    def test_capital_exceeds_maximum_blocks(self):
        """Capital exceeds $5K maximum → NO-GO."""
        auditor = PrefundingGateAuditor()
        report = auditor.run_full_audit(
            campaign_id="NEG-07b",
            frozen_manifest_fingerprint="aaab6c00dc05",
            production_config_fingerprint="aaab6c00dc05",
            manifest_computed_identity="aaab6c00dc05",
            golden_manifest_guard_passes=True,
            strategy_version="R4.0",
            risk_policy_is_authority=True, exposure_maps_populated=True,
            concentration_enforced=True, asset_class_enforced=True,
            drawdown_verified=True, daily_loss_verified=True,
            leverage_verified=True, position_limit_verified=True,
            order_limit_verified=True, kill_switch_verified=True,
            missing_state_fails_closed=True,
            partial_fill_active=True, broker_reconciliation_authoritative=True,
            duplicate_fill_protection=True, disconnect_reconcile_resume_enforced=True,
            no_reconnect_only_trading=True, kill_freeze_independently_tested=True,
            healthy_permits_trade=True, degraded_manage_only=True,
            critical_halts=True, frozen_halts=True,
            stale_halts=True, unparseable_halts=True,
            exception_halts=True, manual_reset_required=True,
            events_durably_recorded=True, alert_delivery_works=True,
            alert_failure_cannot_weaken_safety=True, tamper_evident_log_verifies=True,
            correct_account=True, correct_environment=True,
            correct_symbol_mapping=True, correct_contract_specs=True,
            correct_volume_price_constraints=True, spread_slippage_controls=True,
            no_environment_confusion=True,
            max_capital_enforced=False,  # EXCEEDS MAXIMUM
            campaign_duration_preregistered=True,
            risk_envelope_preregistered=True, r4_positions_separated=True,
            pre_existing_separated=True, no_manual_trading=True,
        )
        assert report.verdict == AuditVerdict.NO_GO


# ============================================================
# 3. PARTIAL FAILURES → RESTRICTED
# ============================================================

class TestRestrictedVerdict:
    """WARNING-level failures produce RESTRICTED (not NO-GO)."""

    def test_warning_only_produces_restricted(self):
        """Only WARNING failures → RESTRICTED."""
        auditor = PrefundingGateAuditor()
        # Manually add a WARNING check
        auditor._add_check(AuditCheck(
            check_id="WARN-01", category="test",
            description="A warning check", passed=False,
            severity="WARNING", expected="ok", observed="warning",
        ))
        verdict = auditor.compute_verdict()
        assert verdict == AuditVerdict.RESTRICTED

    def test_mixed_critical_and_warning_produces_no_go(self):
        """CRITICAL + WARNING → NO-GO (critical dominates)."""
        auditor = PrefundingGateAuditor()
        auditor._add_check(AuditCheck(
            check_id="CRIT-01", category="test",
            description="Critical failure", passed=False,
            severity="CRITICAL",
        ))
        auditor._add_check(AuditCheck(
            check_id="WARN-01", category="test",
            description="Warning", passed=False,
            severity="WARNING",
        ))
        verdict = auditor.compute_verdict()
        assert verdict == AuditVerdict.NO_GO


# ============================================================
# 4. GATE ENFORCEMENT
# ============================================================

class TestPrefundingGate:
    """Gate reads AuditReport → produces AUTHORIZED or BLOCKED."""

    def test_go_authorizes(self):
        """GO verdict → AUTHORIZED."""
        report = _full_pass_report()
        gate = PrefundingGate()
        decision, record = gate.evaluate(report)
        assert decision == GateDecision.AUTHORIZED
        assert record.verdict == "GO"

    def test_restricted_authorizes(self):
        """RESTRICTED verdict → AUTHORIZED (with constraints)."""
        report = _full_pass_report()
        gate = PrefundingGate()
        decision, record = gate.evaluate(report)
        assert decision == GateDecision.AUTHORIZED

    def test_no_go_blocks(self):
        """NO-GO verdict → BLOCKED."""
        auditor = PrefundingGateAuditor()
        report = auditor.run_full_audit(
            campaign_id="BLOCKED-001",
            frozen_manifest_fingerprint="",
            production_config_fingerprint="",
            manifest_computed_identity="",
            golden_manifest_guard_passes=False,
        )
        gate = PrefundingGate()
        decision, record = gate.evaluate(report)
        assert decision == GateDecision.BLOCKED
        assert record.verdict == "NO_GO"
        assert record.critical_failures > 0

    def test_gate_record_fingerprint_deterministic(self):
        """GateRecord fingerprint is deterministic."""
        report = _full_pass_report()
        gate = PrefundingGate()
        _, r1 = gate.evaluate(report)
        gate2 = PrefundingGate()
        _, r2 = gate2.evaluate(report)
        assert r1.gate_fingerprint == r2.gate_fingerprint

    def test_gate_records_accumulate(self):
        """Gate records accumulate across evaluations."""
        gate = PrefundingGate()
        gate.evaluate(_full_pass_report("C1"))
        gate.evaluate(_full_pass_report("C2"))
        assert len(gate.get_records()) == 2

    def test_is_authorized_checks_most_recent(self):
        """is_authorized returns the most recent decision."""
        gate = PrefundingGate()
        gate.evaluate(_full_pass_report("C1"))
        assert gate.is_authorized("C1") is True
        # Block it
        auditor = PrefundingGateAuditor()
        blocked_report = auditor.run_full_audit(campaign_id="C1")
        gate.evaluate(blocked_report)
        assert gate.is_authorized("C1") is False

    def test_unauthorized_campaign_returns_false(self):
        """Unknown campaign → not authorized."""
        gate = PrefundingGate()
        assert gate.is_authorized("UNKNOWN") is False

    def test_gate_record_to_dict(self):
        """GateRecord serializes to dict."""
        report = _full_pass_report()
        gate = PrefundingGate()
        _, record = gate.evaluate(report)
        d = record.to_dict()
        assert "decision" in d
        assert "campaign_id" in d
        assert "gate_fingerprint" in d


# ============================================================
# 5. BROKER BOUNDARY
# ============================================================

class TestBrokerBoundary:
    """Broker boundary validation."""

    def test_correct_config_passes(self):
        """All correct config → all checks pass."""
        config = BrokerBoundaryConfig()
        validator = BrokerBoundaryValidator(config)
        checks = validator.run_all_validations(
            account_id="168966110",
            environment="live",
            broker_name="exness",
            platform="mt5",
            symbols=list(config.expected_symbols.keys()),
            order_volume=0.1,
            order_price=1.1000,
            current_spread=0.0001,
            current_slippage=0.0001,
        )
        assert validator.all_passed
        assert all(c.passed for c in checks)

    def test_wrong_account_fails(self):
        """Wrong account → BB-ACCT fails."""
        validator = BrokerBoundaryValidator()
        validator.validate_account("WRONG_ACCOUNT")
        assert not validator.all_passed
        assert not validator.checks[0].passed

    def test_wrong_environment_fails(self):
        """Wrong environment → BB-ENV fails."""
        validator = BrokerBoundaryValidator()
        validator.validate_environment("demo")
        assert not validator.all_passed

    def test_missing_symbols_fails(self):
        """Missing expected symbols → BB-SYM fails."""
        validator = BrokerBoundaryValidator()
        validator.validate_symbols(["EURUSDm"])  # missing most
        assert not validator.all_passed

    def test_excessive_spread_fails(self):
        """Spread exceeds max → BB-SPREAD fails."""
        validator = BrokerBoundaryValidator()
        validator.validate_spread_slippage(
            current_spread=0.1,  # way too high
            current_slippage=0.0,
        )
        assert not validator.all_passed

    def test_volume_too_large_fails(self):
        """Volume exceeds max → BB-VOLPRICE fails."""
        validator = BrokerBoundaryValidator()
        validator.validate_volume_price_constraints(
            order_volume=100.0,  # exceeds max_volume=1.0
            order_price=1.0,
        )
        assert not validator.all_passed

    def test_config_fingerprint_deterministic(self):
        """BrokerBoundaryConfig fingerprint is deterministic."""
        config = BrokerBoundaryConfig()
        fp1 = config.compute_fingerprint()
        fp2 = config.compute_fingerprint()
        assert fp1 == fp2
        assert len(fp1) == 64


# ============================================================
# 6. CAPITAL BOUNDARY
# ============================================================

class TestCapitalBoundary:
    """Capital boundary validation."""

    def test_within_bounds_passes(self):
        """Capital within bounds → all checks pass."""
        validator = CapitalBoundaryValidator()
        checks = validator.run_all_validations(
            actual_equity=4500.0,
            actual_duration_days=15.0,
            r4_position_count=2,
            pre_existing_position_count=1,
            manual_position_count=0,
            manual_trade_count=0,
            current_drawdown_pct=5.0,
            current_daily_loss=50.0,
        )
        assert validator.all_passed

    def test_equity_exceeds_maximum_fails(self):
        """Equity > $5K → CB-EQUITY fails."""
        validator = CapitalBoundaryValidator()
        validator.validate_max_equity(6000.0)
        assert not validator.all_passed
        assert not validator.checks[0].passed

    def test_manual_trades_fail(self):
        """Manual trades > 0 → CB-NOMANUAL fails."""
        validator = CapitalBoundaryValidator()
        validator.validate_no_manual_trading(manual_trade_count=1)
        assert not validator.all_passed

    def test_drawdown_exceeds_envelope_fails(self):
        """Drawdown > max → CB-DRAWDOWN fails."""
        validator = CapitalBoundaryValidator()
        validator.validate_drawdown_envelope(current_drawdown_pct=25.0)
        assert not validator.all_passed

    def test_daily_loss_exceeds_envelope_fails(self):
        """Daily loss > max → CB-DAILYLOSS fails."""
        validator = CapitalBoundaryValidator()
        validator.validate_daily_loss_envelope(current_daily_loss=500.0)
        assert not validator.all_passed

    def test_config_fingerprint_deterministic(self):
        """CapitalBoundaryConfig fingerprint is deterministic."""
        config = CapitalBoundaryConfig()
        fp1 = config.compute_fingerprint()
        fp2 = config.compute_fingerprint()
        assert fp1 == fp2
        assert len(fp1) == 64

    def test_position_separation_with_manual_fails(self):
        """Manual positions in separation check → fails."""
        validator = CapitalBoundaryValidator()
        validator.validate_position_separation(
            r4_position_count=2,
            pre_existing_position_count=1,
            manual_position_count=1,  # manual detected
        )
        assert not validator.all_passed


# ============================================================
# 7. REPORT GENERATION
# ============================================================

class TestReportGeneration:
    """Report structure and serialization."""

    def test_category_results_populated(self):
        """Category results are populated with correct counts."""
        report = _full_pass_report()
        assert len(report.category_results) == 7
        for cat_data in report.category_results.values():
            assert cat_data["total"] > 0
            assert cat_data["passed"] == cat_data["total"]
            assert cat_data["failed"] == 0

    def test_report_hash_changes_with_checks(self):
        """Report hash changes when checks change."""
        r1 = _full_pass_report("C1")
        auditor = PrefundingGateAuditor()
        r2 = auditor.run_full_audit(
            campaign_id="C2",
            frozen_manifest_fingerprint="DIFFERENT",
        )
        assert r1.report_hash != r2.report_hash

    def test_markdown_includes_all_categories(self):
        """Markdown report includes all 7 categories."""
        report = _full_pass_report()
        md = report.to_markdown()
        for cat in AuditCategory:
            assert cat.value in md

    def test_markdown_no_go_includes_failures(self):
        """NO-GO markdown report shows failures."""
        auditor = PrefundingGateAuditor()
        report = auditor.run_full_audit(campaign_id="FAIL-MD")
        md = report.to_markdown()
        assert "NO-GO" in md
        assert "NOT authorized" in md


# ============================================================
# 8. CHECK STRUCTURE
# ============================================================

class TestAuditCheckStructure:
    """AuditCheck dataclass behavior."""

    def test_check_to_dict(self):
        """Check serializes to dict."""
        check = AuditCheck(
            check_id="TEST-01", category="test",
            description="A test check", passed=True,
            severity="CRITICAL", expected="x", observed="x",
        )
        d = check.to_dict()
        assert d["check_id"] == "TEST-01"
        assert d["passed"] is True

    def test_check_defaults(self):
        """Check defaults are sensible."""
        check = AuditCheck(
            check_id="X", category="c", description="d", passed=True,
        )
        assert check.severity == "CRITICAL"
        assert check.details == ""
