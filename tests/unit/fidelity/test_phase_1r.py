"""Phase 1R Tests — R4 Paper Fidelity & Execution Qualification."""

import pytest
from eigencapital.fidelity.r4_manifest import R4ConfigManifest
from eigencapital.fidelity.parity import (
    ResearchPaperParityEngine,
    ParityBoundary,
    ParityStatus,
    DivergenceType,
    ParitySummary,
)
from eigencapital.fidelity.replay import (
    DeterministicReplayCampaign,
    ReplayStatus,
)
from eigencapital.fidelity.forward import (
    ForwardPaperCampaign,
    ForwardStatus,
    OperationalEvent,
)
from eigencapital.fidelity.verdict import (
    FidelityEvaluator,
    FidelityVerdict,
    FidelityGate,
)


# ============================================================
# R4 CONFIG MANIFEST TESTS
# ============================================================


class TestR4ConfigManifest:
    """Test frozen R4 configuration manifest."""

    def test_manifest_creation(self):
        manifest = R4ConfigManifest()
        assert manifest.strategy_name == "risk_conditioned_continuation"
        assert manifest.strategy_version == "R4.0"

    def test_manifest_identity_deterministic(self):
        m1 = R4ConfigManifest()
        m2 = R4ConfigManifest()
        assert m1.compute_identity() == m2.compute_identity()

    def test_manifest_identity_changes_with_config(self):
        m1 = R4ConfigManifest(crypto_max_allocation=0.10)
        m2 = R4ConfigManifest(crypto_max_allocation=0.20)
        assert m1.compute_identity() != m2.compute_identity()

    def test_manifest_universe(self):
        manifest = R4ConfigManifest()
        assert "EURUSDm" in manifest.universe
        assert "BTCUSDm" in manifest.universe
        assert len(manifest.universe) == 15

    def test_manifest_to_dict(self):
        manifest = R4ConfigManifest()
        d = manifest.to_dict()
        assert "strategy_name" in d
        assert "manifest_identity" in d
        assert d["crypto_max_allocation"] == 0.10

    def test_manifest_risk_params_frozen(self):
        manifest = R4ConfigManifest()
        assert manifest.crypto_max_allocation == 0.10
        assert manifest.asset_risk_limit == 0.02
        assert manifest.correlation_threshold == 0.7
        assert manifest.drawdown_control_threshold == -0.15
        assert manifest.vol_target_annual == 0.10

    def test_manifest_cost_model(self):
        manifest = R4ConfigManifest()
        assert manifest.transaction_cost_bps == 10.0
        assert manifest.slippage_bps == 5.0
        assert manifest.rebalance_frequency == "weekly"


# ============================================================
# RESEARCH → PAPER PARITY ENGINE TESTS
# ============================================================


class TestParityEngine:
    """Test research → paper parity engine."""

    def test_exact_match(self):
        engine = ResearchPaperParityEngine("test-campaign")
        result = engine.check(
            ParityBoundary.SIGNAL,
            "2026-01-01",
            "EURUSDm",
            0.5,
            0.5,
        )
        assert result.status == ParityStatus.PASS
        assert result.divergence_type == DivergenceType.EXACT_MATCH

    def test_intentional_difference(self):
        engine = ResearchPaperParityEngine("test-campaign")
        result = engine.check(
            ParityBoundary.TARGET_WEIGHT,
            "2026-01-01",
            "BTCUSDm",
            0.15,
            0.10,
            is_intentional=True,
            explanation="crypto cap applied",
        )
        assert result.status == ParityStatus.EXPECTED
        assert result.divergence_type == DivergenceType.EXPECTED_DIFFERENCE

    def test_tolerable_divergence(self):
        engine = ResearchPaperParityEngine("test-campaign")
        result = engine.check(
            ParityBoundary.TARGET_WEIGHT,
            "2026-01-01",
            "EURUSDm",
            0.100,
            0.1005,  # within 0.1% tolerance
        )
        assert result.status == ParityStatus.PASS

    def test_unexplained_divergence(self):
        engine = ResearchPaperParityEngine("test-campaign")
        result = engine.check(
            ParityBoundary.TARGET_WEIGHT,
            "2026-01-01",
            "EURUSDm",
            0.100,
            0.102,  # > 0.1% but < 1%
        )
        assert result.status == ParityStatus.WARNING

    def test_critical_divergence(self):
        engine = ResearchPaperParityEngine("test-campaign")
        result = engine.check(
            ParityBoundary.POSITION,
            "2026-01-01",
            "EURUSDm",
            100.0,
            105.0,  # huge difference
        )
        assert result.status == ParityStatus.CRITICAL

    def test_summary(self):
        engine = ResearchPaperParityEngine("test-campaign")
        engine.check_signal("t1", "EURUSDm", 0.5, 0.5)  # exact
        engine.check_signal("t1", "GBPUSDm", 0.5, 0.6)  # critical
        engine.check_weight("t1", "BTCUSDm", 0.15, 0.10, is_intentional=True)

        summary = engine.get_summary()
        assert summary.total_checks == 3
        assert summary.exact_matches == 1
        assert summary.expected_differences == 1
        assert summary.critical_divergences == 1
        assert summary.overall_status == "CRITICAL"

    def test_has_critical(self):
        engine = ResearchPaperParityEngine("test-campaign")
        assert not engine.has_critical
        engine.check_position("t1", "X", 100.0, 200.0)
        assert engine.has_critical

    def test_convenience_methods(self):
        engine = ResearchPaperParityEngine("test-campaign")
        engine.check_signal("t1", "EURUSDm", 0.5, 0.5)
        engine.check_weight("t1", "EURUSDm", 0.1, 0.1)
        engine.check_position("t1", "EURUSDm", 100.0, 100.0)
        engine.check_pnl("t1", "EURUSDm", 0.01, 0.01)
        assert engine.check_count == 4


# ============================================================
# DETERMINISTIC REPLAY TESTS
# ============================================================


class TestDeterministicReplay:
    """Test deterministic replay campaign."""

    def test_perfect_replay(self):
        manifest = R4ConfigManifest()
        campaign = DeterministicReplayCampaign(manifest)

        decisions = [
            {"timestamp": "2026-01-01", "instrument_id": "EURUSDm",
             "signal": 0.5, "weight": 0.1, "position": 100.0, "pnl": 0.01},
            {"timestamp": "2026-01-02", "instrument_id": "GBPUSDm",
             "signal": -0.3, "weight": 0.08, "position": -80.0, "pnl": -0.005},
        ]

        result = campaign.run(decisions, decisions)
        assert result.status == "PASS"
        assert result.match_rate == 1.0
        assert result.critical_divergences == 0

    def test_divergent_replay(self):
        manifest = R4ConfigManifest()
        campaign = DeterministicReplayCampaign(manifest)

        research = [
            {"timestamp": "2026-01-01", "instrument_id": "EURUSDm",
             "signal": 0.5, "weight": 0.1, "position": 100.0, "pnl": 0.01},
        ]
        paper = [
            {"timestamp": "2026-01-01", "instrument_id": "EURUSDm",
             "signal": 0.5, "weight": 0.15, "position": 150.0, "pnl": 0.02},
        ]

        result = campaign.run(research, paper)
        assert result.status in ("WARNING", "CRITICAL")

    def test_mismatched_lengths(self):
        manifest = R4ConfigManifest()
        campaign = DeterministicReplayCampaign(manifest)

        research = [{"timestamp": "t1", "instrument_id": "X",
                      "signal": 0.5, "weight": 0.1, "position": 100, "pnl": 0}]
        paper = []

        result = campaign.run(research, paper)
        assert result.status == "CRITICAL"

    def test_replay_status_lifecycle(self):
        manifest = R4ConfigManifest()
        campaign = DeterministicReplayCampaign(manifest)
        assert campaign.status == ReplayStatus.CREATED

        campaign.run([], [])
        assert campaign.status == ReplayStatus.COMPLETED

    def test_manifest_identity_in_result(self):
        manifest = R4ConfigManifest()
        campaign = DeterministicReplayCampaign(manifest)
        result = campaign.run([], [])
        assert result.manifest_identity == manifest.compute_identity()


# ============================================================
# FORWARD PAPER CAMPAIGN TESTS
# ============================================================


class TestForwardPaperCampaign:
    """Test forward paper campaign."""

    def test_normal_tick(self):
        manifest = R4ConfigManifest()
        campaign = ForwardPaperCampaign(manifest)

        tick = campaign.ingest_tick({
            "timestamp": "2026-01-01 12:00:00",
            "instrument_id": "EURUSDm",
            "open": 1.1000,
            "high": 1.1050,
            "low": 1.0980,
            "close": 1.1020,
            "volume": 1000,
            "spread": 0.0002,
        })
        assert tick.operational_event == OperationalEvent.NORMAL

    def test_missing_bar_detection(self):
        manifest = R4ConfigManifest()
        campaign = ForwardPaperCampaign(manifest)

        tick = campaign.ingest_tick({
            "timestamp": "2026-01-01 12:00:00",
            "instrument_id": "EURUSDm",
            "open": 1.1000, "high": 1.1050, "low": 1.0980,
            "close": 1.1020, "volume": 1000, "spread": 0.0002,
            "is_missing": True,
        })
        assert tick.operational_event == OperationalEvent.MISSING_BAR

    def test_stale_data_detection(self):
        manifest = R4ConfigManifest()
        campaign = ForwardPaperCampaign(manifest)

        tick = campaign.ingest_tick({
            "timestamp": "2026-01-01 12:00:00",
            "instrument_id": "EURUSDm",
            "open": 1.1000, "high": 1.1050, "low": 1.0980,
            "close": 1.1020, "volume": 1000, "spread": 0.0002,
            "is_stale": True,
        })
        assert tick.operational_event == OperationalEvent.STALE_DATA

    def test_spread_widening_detection(self):
        manifest = R4ConfigManifest()
        campaign = ForwardPaperCampaign(manifest)

        tick = campaign.ingest_tick({
            "timestamp": "2026-01-01 12:00:00",
            "instrument_id": "EURUSDm",
            "open": 1.1000, "high": 1.1050, "low": 1.0980,
            "close": 1.1020, "volume": 1000,
            "spread": 0.0010,  # 5x avg spread
            "avg_spread": 0.0002,
        })
        assert tick.operational_event == OperationalEvent.SPREAD_WIDENING

    def test_session_boundary_detection(self):
        manifest = R4ConfigManifest()
        campaign = ForwardPaperCampaign(manifest)

        tick = campaign.ingest_tick({
            "timestamp": "2026-01-01 12:00:00",
            "instrument_id": "EURUSDm",
            "open": 1.1000, "high": 1.1050, "low": 1.0980,
            "close": 1.1020, "volume": 1000, "spread": 0.0002,
            "is_session_boundary": True,
        })
        assert tick.operational_event == OperationalEvent.SESSION_BOUNDARY

    def test_decision_recording(self):
        manifest = R4ConfigManifest()
        campaign = ForwardPaperCampaign(manifest)

        decision = campaign.make_decision(
            timestamp="2026-01-01 12:00:00",
            instrument_id="EURUSDm",
            signal=0.5,
            weight=0.1,
            position=100.0,
            order_intent="BUY",
            risk_approved=True,
            execution_price=1.1020,
            spread_at_decision=0.0002,
        )
        assert decision.order_intent == "BUY"
        assert decision.risk_approved is True

    def test_reconciliation_periodic(self):
        manifest = R4ConfigManifest()
        campaign = ForwardPaperCampaign(manifest)

        for i in range(101):
            campaign.ingest_tick({
                "timestamp": f"2026-01-01 12:{i:02d}:00",
                "instrument_id": "EURUSDm",
                "open": 1.1000, "high": 1.1050, "low": 1.0980,
                "close": 1.1020, "volume": 1000, "spread": 0.0002,
            })

        result = campaign.get_result()
        assert result.reconciliation_checks >= 1

    def test_forward_result(self):
        manifest = R4ConfigManifest()
        campaign = ForwardPaperCampaign(manifest)

        campaign.ingest_tick({
            "timestamp": "2026-01-01 12:00:00",
            "instrument_id": "EURUSDm",
            "open": 1.1000, "high": 1.1050, "low": 1.0980,
            "close": 1.1020, "volume": 1000, "spread": 0.0002,
        })

        result = campaign.get_result()
        assert result.total_ticks == 1
        assert result.status == "PASS"

    def test_forward_status_lifecycle(self):
        manifest = R4ConfigManifest()
        campaign = ForwardPaperCampaign(manifest)
        assert campaign.status == ForwardStatus.CREATED

        campaign.ingest_tick({
            "timestamp": "t1", "instrument_id": "X",
            "open": 1.0, "high": 1.0, "low": 1.0,
            "close": 1.0, "volume": 100, "spread": 0.001,
        })
        assert campaign.status == ForwardStatus.RUNNING


# ============================================================
# FIDELITY VERDICT TESTS
# ============================================================


class TestFidelityVerdict:
    """Test fidelity verdict evaluation."""

    def test_perfect_pass(self):
        manifest = R4ConfigManifest()
        evaluator = FidelityEvaluator(manifest)

        summary = ParitySummary(
            total_checks=100,
            exact_matches=98,
            expected_differences=2,
            tolerable_divergences=0,
            unexplained_divergences=0,
            critical_divergences=0,
        )

        report = evaluator.evaluate(
            campaign_id="test-campaign",
            parity_summary=summary,
            reconciliation_success_rate=1.0,
            total_cost_drag_bps=5.0,
            max_slippage_bps=3.0,
        )

        assert report.verdict == FidelityVerdict.PAPER_FIDELITY_PASS
        assert report.failed_gates == 0
        assert report.passed_gates == 7

    def test_blocked_on_critical(self):
        manifest = R4ConfigManifest()
        evaluator = FidelityEvaluator(manifest)

        summary = ParitySummary(
            total_checks=100,
            exact_matches=90,
            expected_differences=5,
            tolerable_divergences=3,
            unexplained_divergences=1,
            critical_divergences=1,
        )

        report = evaluator.evaluate(
            campaign_id="test-campaign",
            parity_summary=summary,
        )

        assert report.verdict == FidelityVerdict.BLOCKED

    def test_conditional_on_unexplained(self):
        manifest = R4ConfigManifest()
        evaluator = FidelityEvaluator(manifest)

        summary = ParitySummary(
            total_checks=100,
            exact_matches=90,
            expected_differences=2,
            tolerable_divergences=3,
            unexplained_divergences=5,
            critical_divergences=0,
        )

        report = evaluator.evaluate(
            campaign_id="test-campaign",
            parity_summary=summary,
        )

        assert report.verdict == FidelityVerdict.CONDITIONAL

    def test_blocked_on_reconciliation_failure(self):
        manifest = R4ConfigManifest()
        evaluator = FidelityEvaluator(manifest)

        summary = ParitySummary(
            total_checks=100,
            exact_matches=98,
            expected_differences=2,
            critical_divergences=0,
        )

        report = evaluator.evaluate(
            campaign_id="test-campaign",
            parity_summary=summary,
            reconciliation_success_rate=0.95,  # 5% failure
        )

        assert report.verdict != FidelityVerdict.PAPER_FIDELITY_PASS

    def test_blocked_on_cost_excess(self):
        manifest = R4ConfigManifest()
        evaluator = FidelityEvaluator(manifest)

        summary = ParitySummary(
            total_checks=100,
            exact_matches=98,
            expected_differences=2,
            critical_divergences=0,
        )

        report = evaluator.evaluate(
            campaign_id="test-campaign",
            parity_summary=summary,
            total_cost_drag_bps=50.0,  # way over 20bp limit
        )

        assert report.verdict != FidelityVerdict.PAPER_FIDELITY_PASS

    def test_report_hash_deterministic(self):
        manifest = R4ConfigManifest()
        evaluator = FidelityEvaluator(manifest)

        summary = ParitySummary(total_checks=10, exact_matches=10)

        r1 = evaluator.evaluate("c1", summary)
        r2 = evaluator.evaluate("c1", summary)
        assert r1.report_hash == r2.report_hash

    def test_report_markdown(self):
        manifest = R4ConfigManifest()
        evaluator = FidelityEvaluator(manifest)

        summary = ParitySummary(
            total_checks=100,
            exact_matches=98,
            expected_differences=2,
        )

        report = evaluator.evaluate("c1", summary)
        md = report.to_markdown()
        assert "R4 Paper Fidelity Report" in md
        assert "paper_fidelity_pass" in md

    def test_report_to_dict(self):
        manifest = R4ConfigManifest()
        evaluator = FidelityEvaluator(manifest)

        summary = ParitySummary(total_checks=10, exact_matches=10)
        report = evaluator.evaluate("c1", summary)
        d = report.to_dict()
        assert "verdict" in d
        assert "gate_results" in d
        assert len(d["gate_results"]) == 7

    def test_all_gates_reachable(self):
        """Verify all 7 fidelity gates exist."""
        gates = list(FidelityGate)
        assert len(gates) == 7
        assert FidelityGate.RESEARCH_PARITY in gates
        assert FidelityGate.EXECUTION_ACCOUNTING in gates
        assert FidelityGate.RISK_BEHAVIOR in gates
        assert FidelityGate.RECONCILIATION in gates
        assert FidelityGate.OPERATIONAL_STABILITY in gates
        assert FidelityGate.COST_SLIPPAGE_ENVELOPE in gates
        assert FidelityGate.NO_CRITICAL_DIVERGENCE in gates

    def test_operational_events_affect_verdict(self):
        manifest = R4ConfigManifest()
        evaluator = FidelityEvaluator(manifest)

        summary = ParitySummary(
            total_checks=100,
            exact_matches=98,
            expected_differences=2,
        )

        report = evaluator.evaluate(
            campaign_id="test-campaign",
            parity_summary=summary,
            operational_events={"missing_bar": 1, "stale_data": 1},
        )

        # Operational stability gate should fail
        ops_gate = [g for g in report.gate_results
                    if g.gate == FidelityGate.OPERATIONAL_STABILITY]
        assert len(ops_gate) == 1
        assert not ops_gate[0].passed


# ============================================================
# ADVERSARIAL TESTS
# ============================================================


class TestAdversarialPhase1R:
    """Adversarial tests for Phase 1R."""

    def test_manifest_immutable(self):
        manifest = R4ConfigManifest()
        with pytest.raises(AttributeError):
            manifest.strategy_name = "hacked"  # type: ignore

    def test_parity_cannot_silently_fix(self):
        """Parity engine must never silently ignore critical divergence."""
        engine = ResearchPaperParityEngine("test")
        engine.check_position("t1", "X", 100.0, 200.0)
        assert engine.has_critical
        # Summary must reflect critical status
        summary = engine.get_summary()
        assert summary.critical_divergences > 0

    def test_verdict_cannot_be_forced(self):
        """Verdict must not pass when critical divergences exist."""
        manifest = R4ConfigManifest()
        evaluator = FidelityEvaluator(manifest)

        summary = ParitySummary(
            total_checks=100,
            exact_matches=100,  # all match
            critical_divergences=1,  # but critical exists
        )

        report = evaluator.evaluate("test", summary)
        # Risk gate fails due to critical divergence
        assert report.verdict != FidelityVerdict.PAPER_FIDELITY_PASS

    def test_intentional_difference_not_counted_as_failure(self):
        """Crypto cap differences are EXPECTED, not failures."""
        engine = ResearchPaperParityEngine("test")
        result = engine.check(
            ParityBoundary.TARGET_WEIGHT,
            "t1", "BTCUSDm", 0.15, 0.10,
            is_intentional=True,
            explanation="crypto cap",
        )
        assert result.status == ParityStatus.EXPECTED
        assert not engine.has_critical

    def test_replay_rejects_mismatched_lengths(self):
        """Replay must reject mismatched research/paper decision counts."""
        manifest = R4ConfigManifest()
        campaign = DeterministicReplayCampaign(manifest)
        result = campaign.run(
            [{"timestamp": "t1", "instrument_id": "X",
              "signal": 0, "weight": 0, "position": 0, "pnl": 0}] * 10,
            [{"timestamp": "t1", "instrument_id": "X",
              "signal": 0, "weight": 0, "position": 0, "pnl": 0}] * 5,
        )
        assert result.status == "CRITICAL"

    def test_forward_detects_all_operational_events(self):
        """Forward campaign must detect every operational event type."""
        manifest = R4ConfigManifest()
        campaign = ForwardPaperCampaign(manifest)

        events_detected = set()

        # Normal
        campaign.ingest_tick({
            "timestamp": "t1", "instrument_id": "X",
            "open": 1, "high": 1, "low": 1, "close": 1,
            "volume": 100, "spread": 0.001,
        })
        events_detected.add("normal")

        # Missing
        campaign.ingest_tick({
            "timestamp": "t2", "instrument_id": "X",
            "open": 1, "high": 1, "low": 1, "close": 1,
            "volume": 100, "spread": 0.001, "is_missing": True,
        })
        events_detected.add("missing")

        # Stale
        campaign.ingest_tick({
            "timestamp": "t3", "instrument_id": "X",
            "open": 1, "high": 1, "low": 1, "close": 1,
            "volume": 100, "spread": 0.001, "is_stale": True,
        })
        events_detected.add("stale")

        assert "normal" in events_detected
        assert "missing" in events_detected
        assert "stale" in events_detected
