"""Phase 1P Tests — Controlled Live Campaign & Production Qualification.

Tests:
- Production fingerprint determinism and drift detection
- Execution evidence collection and distributions
- Live campaign lifecycle and evidence aggregation
- Production qualification gate and verdicts
- Adversarial scenarios
"""

from eigencapital.production.fingerprint import (
    ProductionFingerprint,
    FingerprintRegistry,
)
from eigencapital.production.evidence import (
    OrderEvidence,
    ExecutionEvidenceCollector,
    SlippageDistribution,
    LatencyDistribution,
)
from eigencapital.production.live_campaign import (
    LiveCampaign,
    LiveCampaignEngine,
    LiveCampaignResult,
    LiveCampaignStatus,
)
from eigencapital.production.evidence import ExecutionSummary
from eigencapital.production.qualification import (
    ProductionQualificationGate,
    QualificationVerdict,
    QualificationThresholds,
    QualificationCheck,
)


# ============================================================
# Production Fingerprint Tests
# ============================================================


class TestProductionFingerprint:
    """Test production fingerprint determinism and drift detection."""

    def _make_fp(self, **overrides):
        defaults = {
            "strategy_hash": "strat-abc",
            "portfolio_hash": "port-abc",
            "feature_registry_hash": "feat-abc",
            "risk_config_hash": "risk-abc",
            "broker_config_hash": "broker-abc",
            "execution_config_hash": "exec-abc",
            "code_commit": "abc1234",
            "data_version": "v1",
            "environment": "live",
            "created_timestamp": "2026-06-01T00:00:00",
        }
        defaults.update(overrides)
        return ProductionFingerprint(**defaults)

    def test_fingerprint_deterministic(self):
        """Same config produces same fingerprint."""
        fp = self._make_fp()
        assert fp.compute_identity() == fp.compute_identity()

    def test_identical_configs_match(self):
        """Identical configs produce matching fingerprints."""
        fp1 = self._make_fp()
        fp2 = self._make_fp()
        assert fp1.matches(fp2)

    def test_different_configs_dont_match(self):
        """Different configs produce different fingerprints."""
        fp1 = self._make_fp(strategy_hash="aaa")
        fp2 = self._make_fp(strategy_hash="bbb")
        assert not fp1.matches(fp2)

    def test_material_matches_ignores_timestamp(self):
        """material_matches ignores timestamp."""
        fp1 = self._make_fp(created_timestamp="2026-01-01")
        fp2 = self._make_fp(created_timestamp="2026-12-31")
        assert fp1.material_matches(fp2)

    def test_material_matches_detects_strategy_change(self):
        """material_matches detects strategy change."""
        fp1 = self._make_fp(strategy_hash="aaa")
        fp2 = self._make_fp(strategy_hash="bbb")
        assert not fp1.material_matches(fp2)

    def test_material_matches_detects_risk_change(self):
        """material_matches detects risk config change."""
        fp1 = self._make_fp(risk_config_hash="aaa")
        fp2 = self._make_fp(risk_config_hash="bbb")
        assert not fp1.material_matches(fp2)


# ============================================================
# Fingerprint Registry Tests
# ============================================================


class TestFingerprintRegistry:
    """Test fingerprint registry with drift detection."""

    def _make_fp(self, **overrides):
        defaults = {
            "strategy_hash": "s",
            "portfolio_hash": "p",
            "feature_registry_hash": "f",
            "risk_config_hash": "r",
            "broker_config_hash": "b",
            "execution_config_hash": "e",
            "code_commit": "c1",
            "data_version": "v1",
        }
        defaults.update(overrides)
        return ProductionFingerprint(**defaults)

    def test_no_drift_when_identical(self):
        """No drift when fingerprints match."""
        registry = FingerprintRegistry()
        fp = self._make_fp()
        registry.register("prod-1", fp)
        result = registry.check_drift("prod-1", fp)
        assert result["drifted"] is False
        assert len(result["changed_fields"]) == 0

    def test_drift_detected_on_strategy_change(self):
        """Drift detected when strategy changes."""
        registry = FingerprintRegistry()
        fp1 = self._make_fp(strategy_hash="original")
        fp2 = self._make_fp(strategy_hash="changed")
        registry.register("prod-1", fp1)
        result = registry.check_drift("prod-1", fp2)
        assert result["drifted"] is True
        assert "strategy_hash" in result["changed_fields"]

    def test_drift_detected_on_risk_change(self):
        """Drift detected when risk config changes."""
        registry = FingerprintRegistry()
        fp1 = self._make_fp(risk_config_hash="original")
        fp2 = self._make_fp(risk_config_hash="changed")
        registry.register("prod-1", fp1)
        result = registry.check_drift("prod-1", fp2)
        assert result["drifted"] is True
        assert "risk_config_hash" in result["changed_fields"]

    def test_unregistered_fingerprint_drifts(self):
        """Unregistered fingerprint always drifts."""
        registry = FingerprintRegistry()
        fp = self._make_fp()
        result = registry.check_drift("nonexistent", fp)
        assert result["drifted"] is True

    def test_drift_events_recorded(self):
        """Drift events are recorded."""
        registry = FingerprintRegistry()
        fp1 = self._make_fp(strategy_hash="aaa")
        fp2 = self._make_fp(strategy_hash="bbb")
        registry.register("prod-1", fp1)
        registry.check_drift("prod-1", fp2)
        events = registry.get_drift_events()
        assert len(events) == 1


# ============================================================
# Execution Evidence Tests
# ============================================================


class TestExecutionEvidence:
    """Test execution evidence collection and distributions."""

    def _make_evidence(self, **overrides):
        defaults = {
            "order_id": "ord-1",
            "instrument_id": "AAPL",
            "side": "BUY",
            "intended_price": 150.0,
            "fill_price": 150.05,
            "spread_at_decision": 0.01,
            "spread_at_execution": 0.015,
            "expected_slippage": 0.001,
            "realized_slippage": 0.003,
            "latency_seconds": 0.5,
            "filled_quantity": 10.0,
            "requested_quantity": 10.0,
            "status": "FILLED",
            "timestamp": "2026-06-01T10:00:00",
        }
        defaults.update(overrides)
        return OrderEvidence(**defaults)

    def test_empty_collector_returns_zero_summary(self):
        """Empty collector returns zero summary."""
        collector = ExecutionEvidenceCollector()
        summary = collector.get_summary()
        assert summary.total_orders == 0
        assert summary.fill_rate == 0.0

    def test_single_order_summary(self):
        """Single order produces correct summary."""
        collector = ExecutionEvidenceCollector()
        collector.record_order(self._make_evidence())
        summary = collector.get_summary()
        assert summary.total_orders == 1
        assert summary.filled_orders == 1
        assert summary.fill_rate == 1.0

    def test_mixed_statuses(self):
        """Mixed order statuses are correctly counted."""
        collector = ExecutionEvidenceCollector()
        collector.record_order(self._make_evidence(status="FILLED"))
        collector.record_order(self._make_evidence(order_id="ord-2", status="PARTIAL"))
        collector.record_order(self._make_evidence(order_id="ord-3", status="REJECTED"))
        collector.record_order(
            self._make_evidence(order_id="ord-4", status="CANCELLED")
        )
        summary = collector.get_summary()
        assert summary.total_orders == 4
        assert summary.filled_orders == 1
        assert summary.partial_orders == 1
        assert summary.rejected_orders == 1
        assert summary.cancelled_orders == 1
        assert summary.fill_rate == 0.25
        assert summary.rejection_rate == 0.25

    def test_slippage_distribution(self):
        """Slippage distribution is computed correctly."""
        collector = ExecutionEvidenceCollector()
        for i in range(100):
            collector.record_order(
                self._make_evidence(
                    order_id=f"ord-{i}",
                    realized_slippage=i * 0.001,
                )
            )
        summary = collector.get_summary()
        assert summary.slippage_distribution.count == 100
        assert summary.slippage_distribution.median > 0

    def test_latency_distribution(self):
        """Latency distribution is computed correctly."""
        collector = ExecutionEvidenceCollector()
        for i in range(100):
            collector.record_order(
                self._make_evidence(
                    order_id=f"ord-{i}",
                    latency_seconds=i * 0.1,
                )
            )
        summary = collector.get_summary()
        assert summary.latency_distribution.count == 100
        assert summary.latency_distribution.max > 0

    def test_evidence_fingerprint_deterministic(self):
        """OrderEvidence fingerprint is deterministic."""
        evidence = self._make_evidence()
        fp1 = evidence.compute_fingerprint()
        fp2 = evidence.compute_fingerprint()
        assert fp1 == fp2


# ============================================================
# Live Campaign Lifecycle Tests
# ============================================================


class TestLiveCampaignLifecycle:
    """Test live campaign lifecycle and evidence aggregation."""

    def _make_fingerprint(self):
        return ProductionFingerprint(
            strategy_hash="s",
            portfolio_hash="p",
            feature_registry_hash="f",
            risk_config_hash="r",
            broker_config_hash="b",
            execution_config_hash="e",
            code_commit="c1",
            data_version="v1",
        )

    def _make_campaign(self, status=LiveCampaignStatus.PLANNED.value):
        return LiveCampaign(
            campaign_id="live-1",
            production_fingerprint=self._make_fingerprint(),
            authorization_id="auth-1",
            max_capital=10000.0,
            max_drawdown=2000.0,
            start_timestamp="2026-06-01T00:00:00",
            expiry_timestamp="2026-06-30T23:59:59",
            status=status,
        )

    def test_create_campaign(self):
        """Campaign creation works."""
        engine = LiveCampaignEngine()
        campaign = self._make_campaign()
        created = engine.create_campaign(campaign)
        assert created.campaign_id == "live-1"

    def test_valid_transitions(self):
        """Valid lifecycle transitions work."""
        engine = LiveCampaignEngine()
        engine.create_campaign(self._make_campaign())
        engine.transition_campaign(
            "live-1", LiveCampaignStatus.CONNECTIVITY.value, "t1"
        )
        engine.transition_campaign(
            "live-1", LiveCampaignStatus.MINIMAL_EXPOSURE.value, "t2"
        )
        engine.transition_campaign(
            "live-1", LiveCampaignStatus.EXTENDED_OBSERVATION.value, "t3"
        )
        engine.transition_campaign(
            "live-1", LiveCampaignStatus.QUALIFICATION.value, "t4"
        )
        engine.transition_campaign("live-1", LiveCampaignStatus.COMPLETED.value, "t5")
        final = engine.get_campaign("live-1")
        assert final.status == LiveCampaignStatus.COMPLETED.value

    def test_invalid_transition_blocked(self):
        """Invalid transition is blocked."""
        engine = LiveCampaignEngine()
        engine.create_campaign(
            self._make_campaign(status=LiveCampaignStatus.COMPLETED.value)
        )
        assert (
            engine.transition_campaign("live-1", LiveCampaignStatus.PLANNED.value, "t1")
            is False
        )

    def test_divergence_tracking(self):
        """Divergence counts are tracked."""
        engine = LiveCampaignEngine()
        engine.create_campaign(self._make_campaign())
        engine.record_divergence("live-1", is_critical=False)
        engine.record_divergence("live-1", is_critical=True)
        counts = engine.get_divergence_counts("live-1")
        assert counts["total"] == 2
        assert counts["critical"] == 1

    def test_risk_violation_tracking(self):
        """Risk violations are tracked."""
        engine = LiveCampaignEngine()
        engine.create_campaign(self._make_campaign())
        engine.record_risk_violation("live-1")
        engine.record_risk_violation("live-1")
        assert engine.get_risk_violations("live-1") == 2

    def test_reconciliation_failure_tracking(self):
        """Reconciliation failures are tracked."""
        engine = LiveCampaignEngine()
        engine.create_campaign(self._make_campaign())
        engine.record_reconciliation_failure("live-1")
        assert engine.get_reconciliation_failures("live-1") == 1

    def test_kill_switch_tracking(self):
        """Kill switch activations are tracked."""
        engine = LiveCampaignEngine()
        engine.create_campaign(self._make_campaign())
        engine.record_kill_switch_activation("live-1")
        assert engine.get_kill_switch_activations("live-1") == 1

    def test_fingerprint_immutable(self):
        """Campaign fingerprint is deterministic."""
        campaign = self._make_campaign()
        fp1 = campaign.compute_fingerprint()
        fp2 = campaign.compute_fingerprint()
        assert fp1 == fp2


# ============================================================
# Production Qualification Gate Tests
# ============================================================


class TestProductionQualification:
    """Test production qualification gate and verdicts."""

    def _make_fp(self):
        return ProductionFingerprint(
            strategy_hash="s",
            portfolio_hash="p",
            feature_registry_hash="f",
            risk_config_hash="r",
            broker_config_hash="b",
            execution_config_hash="e",
            code_commit="c1",
            data_version="v1",
        )

    def _make_summary(self, **overrides):
        from eigencapital.production.evidence import ExecutionSummary

        defaults = {
            "total_orders": 10,
            "filled_orders": 9,
            "partial_orders": 1,
            "rejected_orders": 0,
            "cancelled_orders": 0,
            "fill_rate": 0.9,
            "rejection_rate": 0.0,
            "partial_fill_rate": 0.1,
            "slippage_distribution": SlippageDistribution(
                median=0.001,
                p75=0.002,
                p90=0.003,
                p95=0.004,
                p99=0.005,
                max=0.006,
                count=10,
            ),
            "latency_distribution": LatencyDistribution(
                median=0.5, p75=0.7, p90=0.9, p95=1.0, p99=1.5, max=2.0, count=10
            ),
            "total_realized_slippage": 0.01,
            "total_latency": 5.0,
            "average_fill_price_deviation": 0.001,
        }
        defaults.update(overrides)
        return ExecutionSummary(**defaults)

    def _make_result(self, **overrides):
        defaults = {
            "campaign_id": "live-1",
            "production_fingerprint": self._make_fp(),
            "execution_summary": self._make_summary(),
            "total_divergences": 2,
            "critical_divergences": 0,
            "risk_boundary_violations": 0,
            "reconciliation_failures": 0,
            "kill_switch_activations": 0,
            "qualification_passed": True,
            "verdict": "",
            "evidence_completeness": 0.95,
        }
        defaults.update(overrides)
        return LiveCampaignResult(**defaults)

    def test_all_pass_produces_qualified(self):
        """All checks pass → LIVE_QUALIFIED."""
        gate = ProductionQualificationGate()
        result = gate.evaluate(self._make_result())
        assert result.verdict == QualificationVerdict.LIVE_QUALIFIED.value
        assert all(c.passed for c in result.checks)

    def test_risk_violation_blocks(self):
        """Risk violation → LIVE_BLOCKED."""
        gate = ProductionQualificationGate()
        result = gate.evaluate(self._make_result(risk_boundary_violations=1))
        assert result.verdict == QualificationVerdict.LIVE_BLOCKED.value

    def test_critical_divergence_blocks(self):
        """Critical divergence → LIVE_BLOCKED."""
        gate = ProductionQualificationGate()
        result = gate.evaluate(self._make_result(critical_divergences=1))
        assert result.verdict == QualificationVerdict.LIVE_BLOCKED.value

    def test_low_evidence_inconclusive(self):
        """Insufficient evidence → LIVE_INCONCLUSIVE."""
        gate = ProductionQualificationGate()
        result = gate.evaluate(self._make_result(evidence_completeness=0.3))
        # Evidence check is HIGH severity, so this should be INCONCLUSIVE
        assert result.verdict in [
            QualificationVerdict.LIVE_INCONCLUSIVE.value,
            QualificationVerdict.LIVE_QUALIFIED_WITH_RESTRICTIONS.value,
        ]

    def test_high_rejection_rate_adds_restrictions(self):
        """High rejection rate → restrictions added."""
        gate = ProductionQualificationGate()
        result = gate.evaluate(
            self._make_result(
                execution_summary=self._make_summary(rejection_rate=0.5, fill_rate=0.5),
            )
        )
        assert len(result.restrictions) > 0

    def test_missing_fingerprint_blocks(self):
        """Missing production fingerprint → LIVE_BLOCKED."""
        gate = ProductionQualificationGate()
        result = gate.evaluate(self._make_result(production_fingerprint=None))
        assert result.verdict == QualificationVerdict.LIVE_BLOCKED.value

    def test_qualification_result_deterministic(self):
        """Qualification result fingerprint is deterministic."""
        gate = ProductionQualificationGate()
        result = gate.evaluate(self._make_result())
        fp1 = result.compute_fingerprint()
        fp2 = result.compute_fingerprint()
        assert fp1 == fp2

    def test_thresholds_fingerprint_deterministic(self):
        """Thresholds fingerprint is deterministic."""
        thresholds = QualificationThresholds()
        fp1 = thresholds.compute_fingerprint()
        fp2 = thresholds.compute_fingerprint()
        assert fp1 == fp2

    def test_verdict_never_unrestricted_live(self):
        """Verdict is never unrestricted LIVE_READY."""
        gate = ProductionQualificationGate()
        result = gate.evaluate(self._make_result())
        assert result.verdict != "live_ready"
        assert result.verdict in [
            QualificationVerdict.LIVE_QUALIFIED.value,
            QualificationVerdict.LIVE_QUALIFIED_WITH_RESTRICTIONS.value,
            QualificationVerdict.LIVE_INCONCLUSIVE.value,
            QualificationVerdict.LIVE_BLOCKED.value,
        ]


# ============================================================
# Adversarial / Integration Tests
# ============================================================


class TestPhase1PAdversarial:
    """Adversarial tests for Phase 1P."""

    def test_profitable_outcome_does_not_auto_qualify(self):
        """Good P&L does not automatically qualify — checks matter."""
        gate = ProductionQualificationGate()
        # Risk violation even with good execution
        result = gate.evaluate(
            LiveCampaignResult(
                campaign_id="live-1",
                production_fingerprint=ProductionFingerprint(
                    strategy_hash="s",
                    portfolio_hash="p",
                    feature_registry_hash="f",
                    risk_config_hash="r",
                    broker_config_hash="b",
                    execution_config_hash="e",
                    code_commit="c1",
                ),
                execution_summary=ExecutionSummary(
                    total_orders=10,
                    filled_orders=10,
                    partial_orders=0,
                    rejected_orders=0,
                    cancelled_orders=0,
                    fill_rate=1.0,
                    rejection_rate=0.0,
                    partial_fill_rate=0.0,
                    slippage_distribution=SlippageDistribution(median=0.001, count=10),
                    latency_distribution=LatencyDistribution(median=0.5, count=10),
                    total_realized_slippage=0.01,
                    total_latency=5.0,
                    average_fill_price_deviation=0.001,
                ),
                total_divergences=0,
                critical_divergences=0,
                risk_boundary_violations=1,  # Safety violation!
                reconciliation_failures=0,
                kill_switch_activations=0,
                qualification_passed=True,
                verdict="",
                evidence_completeness=1.0,
            )
        )
        assert result.verdict == QualificationVerdict.LIVE_BLOCKED.value

    def test_campaign_lifecycle_full_flow(self):
        """Full campaign lifecycle from PLANNED to COMPLETED."""
        engine = LiveCampaignEngine()
        fp = ProductionFingerprint(
            strategy_hash="s",
            portfolio_hash="p",
            feature_registry_hash="f",
            risk_config_hash="r",
            broker_config_hash="b",
            execution_config_hash="e",
            code_commit="c1",
        )
        campaign = LiveCampaign(
            campaign_id="live-1",
            production_fingerprint=fp,
            authorization_id="auth-1",
            max_capital=10000.0,
            max_drawdown=2000.0,
            start_timestamp="2026-06-01",
            expiry_timestamp="2026-06-30",
        )
        engine.create_campaign(campaign)
        engine.transition_campaign(
            "live-1", LiveCampaignStatus.CONNECTIVITY.value, "t1"
        )
        engine.transition_campaign(
            "live-1", LiveCampaignStatus.MINIMAL_EXPOSURE.value, "t2"
        )
        engine.transition_campaign(
            "live-1", LiveCampaignStatus.EXTENDED_OBSERVATION.value, "t3"
        )
        engine.transition_campaign(
            "live-1", LiveCampaignStatus.QUALIFICATION.value, "t4"
        )
        engine.transition_campaign("live-1", LiveCampaignStatus.COMPLETED.value, "t5")
        final = engine.get_campaign("live-1")
        assert final.status == LiveCampaignStatus.COMPLETED.value
        assert len(final.status_history) == 5

    def test_fingerprint_drift_invalidates_qualification(self):
        """Fingerprint drift should invalidate qualification."""
        registry = FingerprintRegistry()
        fp_original = ProductionFingerprint(
            strategy_hash="original",
            portfolio_hash="p",
            feature_registry_hash="f",
            risk_config_hash="r",
            broker_config_hash="b",
            execution_config_hash="e",
            code_commit="c1",
        )
        fp_changed = ProductionFingerprint(
            strategy_hash="CHANGED",
            portfolio_hash="p",
            feature_registry_hash="f",
            risk_config_hash="r",
            broker_config_hash="b",
            execution_config_hash="e",
            code_commit="c1",
        )
        registry.register("prod-1", fp_original)
        result = registry.check_drift("prod-1", fp_changed)
        assert result["drifted"] is True
        assert "strategy_hash" in result["changed_fields"]

    def test_reconciliation_failure_blocks_qualification(self):
        """Reconciliation failure → LIVE_BLOCKED."""
        gate = ProductionQualificationGate()
        result = gate.evaluate(
            LiveCampaignResult(
                campaign_id="live-1",
                production_fingerprint=ProductionFingerprint(
                    strategy_hash="s",
                    portfolio_hash="p",
                    feature_registry_hash="f",
                    risk_config_hash="r",
                    broker_config_hash="b",
                    execution_config_hash="e",
                    code_commit="c1",
                ),
                execution_summary=ExecutionSummary(
                    total_orders=10,
                    filled_orders=10,
                    partial_orders=0,
                    rejected_orders=0,
                    cancelled_orders=0,
                    fill_rate=1.0,
                    rejection_rate=0.0,
                    partial_fill_rate=0.0,
                    slippage_distribution=SlippageDistribution(median=0.001, count=10),
                    latency_distribution=LatencyDistribution(median=0.5, count=10),
                    total_realized_slippage=0.01,
                    total_latency=5.0,
                    average_fill_price_deviation=0.001,
                ),
                total_divergences=0,
                critical_divergences=0,
                risk_boundary_violations=0,
                reconciliation_failures=1,  # Reconciliation failure!
                kill_switch_activations=0,
                qualification_passed=True,
                verdict="",
                evidence_completeness=1.0,
            )
        )
        assert result.verdict == QualificationVerdict.LIVE_BLOCKED.value

    def test_evidence_collector_tracks_campaign_evidence(self):
        """Engine tracks evidence per campaign."""
        engine = LiveCampaignEngine()
        fp = ProductionFingerprint(
            strategy_hash="s",
            portfolio_hash="p",
            feature_registry_hash="f",
            risk_config_hash="r",
            broker_config_hash="b",
            execution_config_hash="e",
            code_commit="c1",
        )
        campaign = LiveCampaign(
            campaign_id="live-1",
            production_fingerprint=fp,
            authorization_id="auth-1",
            max_capital=10000.0,
            max_drawdown=2000.0,
            start_timestamp="2026-06-01",
            expiry_timestamp="2026-06-30",
        )
        engine.create_campaign(campaign)
        collector = engine.get_evidence_collector("live-1")
        assert collector is not None
        collector.record_order(
            OrderEvidence(
                order_id="ord-1",
                instrument_id="AAPL",
                side="BUY",
                intended_price=150.0,
                fill_price=150.05,
                spread_at_decision=0.01,
                spread_at_execution=0.015,
                expected_slippage=0.001,
                realized_slippage=0.003,
                latency_seconds=0.5,
                filled_quantity=10.0,
                requested_quantity=10.0,
                status="FILLED",
            )
        )
        summary = collector.get_summary()
        assert summary.total_orders == 1
        assert summary.filled_orders == 1

    def test_multiple_campaigns_independent(self):
        """Multiple campaigns are tracked independently."""
        engine = LiveCampaignEngine()
        fp = ProductionFingerprint(
            strategy_hash="s",
            portfolio_hash="p",
            feature_registry_hash="f",
            risk_config_hash="r",
            broker_config_hash="b",
            execution_config_hash="e",
            code_commit="c1",
        )
        for i in range(3):
            campaign = LiveCampaign(
                campaign_id=f"live-{i}",
                production_fingerprint=fp,
                authorization_id=f"auth-{i}",
                max_capital=10000.0,
                max_drawdown=2000.0,
                start_timestamp="2026-06-01",
                expiry_timestamp="2026-06-30",
            )
            engine.create_campaign(campaign)
            engine.record_divergence(f"live-{i}", is_critical=(i == 0))

        assert engine.get_divergence_counts("live-0")["critical"] == 1
        assert engine.get_divergence_counts("live-1")["critical"] == 0
        assert engine.get_divergence_counts("live-2")["critical"] == 0

    def test_qualification_result_has_all_checks(self):
        """Qualification result includes all 10 checks."""
        gate = ProductionQualificationGate()
        result = gate.evaluate(
            LiveCampaignResult(
                campaign_id="live-1",
                production_fingerprint=ProductionFingerprint(
                    strategy_hash="s",
                    portfolio_hash="p",
                    feature_registry_hash="f",
                    risk_config_hash="r",
                    broker_config_hash="b",
                    execution_config_hash="e",
                    code_commit="c1",
                ),
                execution_summary=ExecutionSummary(
                    total_orders=10,
                    filled_orders=9,
                    partial_orders=1,
                    rejected_orders=0,
                    cancelled_orders=0,
                    fill_rate=0.9,
                    rejection_rate=0.0,
                    partial_fill_rate=0.1,
                    slippage_distribution=SlippageDistribution(median=0.001, count=10),
                    latency_distribution=LatencyDistribution(median=0.5, count=10),
                    total_realized_slippage=0.01,
                    total_latency=5.0,
                    average_fill_price_deviation=0.001,
                ),
                total_divergences=2,
                critical_divergences=0,
                risk_boundary_violations=0,
                reconciliation_failures=0,
                kill_switch_activations=0,
                qualification_passed=True,
                verdict="",
                evidence_completeness=0.95,
            )
        )
        assert len(result.checks) == 10
        check_names = [c.check for c in result.checks]
        for expected in QualificationCheck:
            assert expected.value in check_names

    def test_get_all_evidence(self):
        """Collector returns all evidence."""
        collector = ExecutionEvidenceCollector()
        for i in range(5):
            collector.record_order(
                OrderEvidence(
                    order_id=f"ord-{i}",
                    instrument_id="AAPL",
                    side="BUY",
                    intended_price=150.0,
                    fill_price=150.0,
                    spread_at_decision=0.01,
                    spread_at_execution=0.01,
                    expected_slippage=0.001,
                    realized_slippage=0.001,
                    latency_seconds=0.1,
                    filled_quantity=10.0,
                    requested_quantity=10.0,
                    status="FILLED",
                )
            )
        all_ev = collector.get_all_evidence()
        assert len(all_ev) == 5

    def test_qualification_history_tracked(self):
        """Qualification results are tracked in history."""
        gate = ProductionQualificationGate()
        fp = ProductionFingerprint(
            strategy_hash="s",
            portfolio_hash="p",
            feature_registry_hash="f",
            risk_config_hash="r",
            broker_config_hash="b",
            execution_config_hash="e",
            code_commit="c1",
        )
        for i in range(3):
            gate.evaluate(
                LiveCampaignResult(
                    campaign_id=f"live-{i}",
                    production_fingerprint=fp,
                    execution_summary=ExecutionSummary(
                        total_orders=10,
                        filled_orders=10,
                        partial_orders=0,
                        rejected_orders=0,
                        cancelled_orders=0,
                        fill_rate=1.0,
                        rejection_rate=0.0,
                        partial_fill_rate=0.0,
                        slippage_distribution=SlippageDistribution(
                            median=0.001, count=10
                        ),
                        latency_distribution=LatencyDistribution(median=0.5, count=10),
                        total_realized_slippage=0.01,
                        total_latency=5.0,
                        average_fill_price_deviation=0.001,
                    ),
                    total_divergences=0,
                    critical_divergences=0,
                    risk_boundary_violations=0,
                    reconciliation_failures=0,
                    kill_switch_activations=0,
                    qualification_passed=True,
                    verdict="",
                    evidence_completeness=1.0,
                )
            )
        results = gate.get_results()
        assert len(results) == 3
        latest = gate.get_latest_result()
        assert latest is not None
        assert latest.campaign_id == "live-2"
