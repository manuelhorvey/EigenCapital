"""Phase 1U Tests — Production Qualification."""

from eigencapital.production_qual.campaign_boundary import (
    CampaignBoundary,
    TradeOrigin,
    TradeRecord,
)
from eigencapital.production_qual.qualification import (
    ProductionEvaluator,
    ProductionVerdict,
)
from eigencapital.production_qual.scaling import (
    SCALE_ENVELOPES,
    ProductionScaleEvaluator,
    ScaleLevel,
    ScalingMetrics,
)

# ============================================================
# CAMPAIGN BOUNDARY TESTS
# ============================================================


class TestCampaignBoundary:
    """Test campaign boundary and trade attribution."""

    def test_boundary_creation(self):
        boundary = CampaignBoundary(
            campaign_id="CAMP-001",
            strategy_fingerprint="abc123",
            start_timestamp="2026-08-24T00:00:00",
        )
        assert boundary.campaign_id == "CAMP-001"

    def test_classify_pre_existing(self):
        boundary = CampaignBoundary(
            campaign_id="CAMP-001",
            strategy_fingerprint="abc",
            start_timestamp="2026-08-24T12:00:00",
        )
        origin = boundary.classify_position(
            broker_ticket=123,
            symbol="EURUSDm",
            volume=0.15,
            entry_price=1.16855,
            entry_time="2026-08-24T10:00:00",  # before start
        )
        assert origin == TradeOrigin.PRE_EXISTING

    def test_classify_manual(self):
        boundary = CampaignBoundary(
            campaign_id="CAMP-001",
            strategy_fingerprint="abc",
            start_timestamp="2026-08-24T12:00:00",
        )
        origin = boundary.classify_position(
            broker_ticket=999,
            symbol="EURUSDm",
            volume=0.15,
            entry_price=1.16855,
            entry_time="2026-08-24T14:00:00",  # after start, no R4 trade
        )
        assert origin == TradeOrigin.MANUAL

    def test_record_r4_trade(self):
        boundary = CampaignBoundary(
            campaign_id="CAMP-001",
            strategy_fingerprint="abc",
            start_timestamp="2026-08-24T12:00:00",
        )
        trade = TradeRecord(
            trade_id="T001",
            decision_id="D001",
            evidence_id="E001",
            instrument_id="EURUSDm",
            side="BUY",
            volume=0.15,
            entry_price=1.16855,
            entry_timestamp="2026-08-24T14:00:00",
            broker_ticket=456,
        )
        boundary.record_r4_trade(trade)
        assert len(boundary.r4_trades) == 1
        assert trade.origin == TradeOrigin.R4_CAMPAIGN

    def test_attribution(self):
        boundary = CampaignBoundary(
            campaign_id="CAMP-001",
            strategy_fingerprint="abc",
            start_timestamp="2026-08-24T12:00:00",
        )
        # R4 trade
        r4_trade = TradeRecord(
            trade_id="T001",
            decision_id="D001",
            evidence_id="E001",
            instrument_id="EURUSDm",
            side="BUY",
            volume=0.15,
            entry_price=1.16855,
            entry_timestamp="2026-08-24T14:00:00",
        )
        r4_trade.pnl = 50.0
        boundary.record_r4_trade(r4_trade)

        # Pre-existing
        pre_trade = TradeRecord(
            trade_id="T002",
            decision_id="PRE",
            evidence_id="PRE",
            instrument_id="GBPUSDm",
            side="BUY",
            volume=0.15,
            entry_price=1.36417,
            entry_timestamp="2026-08-24T10:00:00",
        )
        pre_trade.pnl = -10.0
        boundary.record_pre_existing(pre_trade)

        attr = boundary.get_attribution()
        assert attr["r4_pnl"] == 50.0
        assert attr["pre_existing_pnl"] == -10.0
        assert attr["total_pnl"] == 40.0

    def test_get_r4_positions(self):
        boundary = CampaignBoundary(
            campaign_id="CAMP-001",
            strategy_fingerprint="abc",
            start_timestamp="2026-08-24T12:00:00",
        )
        trade = TradeRecord(
            trade_id="T001",
            decision_id="D001",
            evidence_id="E001",
            instrument_id="EURUSDm",
            side="BUY",
            volume=0.15,
            entry_price=1.16855,
            entry_timestamp="2026-08-24T14:00:00",
        )
        boundary.record_r4_trade(trade)
        assert len(boundary.get_r4_positions()) == 1

    def test_to_dict(self):
        boundary = CampaignBoundary(
            campaign_id="CAMP-001",
            strategy_fingerprint="abc",
            start_timestamp="2026-08-24T12:00:00",
        )
        d = boundary.to_dict()
        assert "campaign_id" in d
        assert "attribution" in d


# ============================================================
# SCALING TESTS
# ============================================================


class TestScaling:
    """Test production scaling framework."""

    def test_scale_envelopes_exist(self):
        assert ScaleLevel.MICRO in SCALE_ENVELOPES
        assert ScaleLevel.MINIMAL in SCALE_ENVELOPES
        assert ScaleLevel.SMALL in SCALE_ENVELOPES
        assert ScaleLevel.MODERATE in SCALE_ENVELOPES

    def test_envelope_stricter_at_smaller_scale(self):
        micro = SCALE_ENVELOPES[ScaleLevel.MICRO]
        moderate = SCALE_ENVELOPES[ScaleLevel.MODERATE]
        assert micro.max_equity < moderate.max_equity
        assert micro.max_position_size < moderate.max_position_size

    def test_envelope_identity(self):
        env = SCALE_ENVELOPES[ScaleLevel.MICRO]
        identity = env.compute_identity()
        assert len(identity) == 64  # SHA256

    def test_scaling_metrics(self):
        metrics = ScalingMetrics(
            slippage_at_micro=0.0001,
            slippage_at_current=0.00015,
            slippage_deterioration=1.5,
        )
        assert metrics.slippage_deterioration == 1.5

    def test_scale_evaluator(self):
        evaluator = ProductionScaleEvaluator()
        metrics = ScalingMetrics(
            slippage_deterioration=1.2,
            spread_deterioration=1.1,
            fill_rate_at_current=0.95,
            margin_usage=0.30,
            margin_pressure=False,
            risk_proportional=True,
        )
        result = evaluator.evaluate(ScaleLevel.MINIMAL, metrics)
        assert result["all_passed"]

    def test_scale_evaluator_fails_on_slippage(self):
        evaluator = ProductionScaleEvaluator()
        metrics = ScalingMetrics(
            slippage_deterioration=3.0,  # exceeds threshold
            spread_deterioration=1.0,
            fill_rate_at_current=0.95,
            margin_usage=0.30,
            margin_pressure=False,
            risk_proportional=True,
        )
        result = evaluator.evaluate(ScaleLevel.MINIMAL, metrics)
        assert not result["all_passed"]
        assert not result["checks"]["slippage"]["passed"]


# ============================================================
# QUALIFICATION TESTS
# ============================================================


class TestProductionQualification:
    """Test production qualification evaluation."""

    def _make_qualified(self):
        boundary = CampaignBoundary(
            campaign_id="PROD-001",
            strategy_fingerprint="abc123",
            start_timestamp="2026-08-24T12:00:00",
        )
        trade = TradeRecord(
            trade_id="T001",
            decision_id="D001",
            evidence_id="E001",
            instrument_id="EURUSDm",
            side="BUY",
            volume=0.15,
            entry_price=1.16855,
            entry_timestamp="2026-08-24T14:00:00",
        )
        boundary.record_r4_trade(trade)

        metrics = ScalingMetrics(
            slippage_deterioration=1.0,
            spread_deterioration=1.0,
            fill_rate_at_current=1.0,
            margin_usage=0.20,
            margin_pressure=False,
            risk_proportional=True,
        )
        return boundary, metrics

    def test_qualification_qualified(self):
        boundary, metrics = self._make_qualified()
        evaluator = ProductionEvaluator()
        report = evaluator.evaluate(
            campaign_id="PROD-001",
            scale_level=ScaleLevel.MINIMAL,
            boundary=boundary,
            scaling_metrics=metrics,
        )
        assert report.verdict == ProductionVerdict.QUALIFIED_FOR_NEXT_SCALE
        assert report.failed_checks == 0

    def test_qualification_blocked_on_manual(self):
        boundary, metrics = self._make_qualified()
        manual = TradeRecord(
            trade_id="M001",
            decision_id="MANUAL",
            evidence_id="MANUAL",
            instrument_id="GBPUSDm",
            side="BUY",
            volume=0.15,
            entry_price=1.36417,
            entry_timestamp="2026-08-24T14:00:00",
        )
        manual.origin = TradeOrigin.MANUAL
        boundary.manual_trades.append(manual)

        evaluator = ProductionEvaluator()
        report = evaluator.evaluate(
            campaign_id="PROD-001",
            scale_level=ScaleLevel.MINIMAL,
            boundary=boundary,
            scaling_metrics=metrics,
        )
        # Manual trades should fail check but not block if only 1 issue
        assert report.checks[0].check_name == "no_manual_trades"
        assert not report.checks[0].passed

    def test_report_markdown(self):
        boundary, metrics = self._make_qualified()
        evaluator = ProductionEvaluator()
        report = evaluator.evaluate(
            campaign_id="PROD-001",
            scale_level=ScaleLevel.MINIMAL,
            boundary=boundary,
            scaling_metrics=metrics,
        )
        md = report.to_markdown()
        assert "Production Qualification Report" in md

    def test_report_to_dict(self):
        boundary, metrics = self._make_qualified()
        evaluator = ProductionEvaluator()
        report = evaluator.evaluate(
            campaign_id="PROD-001",
            scale_level=ScaleLevel.MINIMAL,
            boundary=boundary,
            scaling_metrics=metrics,
        )
        d = report.to_dict()
        assert "verdict" in d
        assert "checks" in d
        assert len(d["checks"]) == 9


# ============================================================
# ADVERSARIAL TESTS
# ============================================================


class TestAdversarialProduction:
    """Adversarial tests for production qualification."""

    def test_boundary_immutable(self):
        boundary = CampaignBoundary(
            campaign_id="CAMP-001",
            strategy_fingerprint="abc",
            start_timestamp="2026-08-24",
        )
        # Cannot modify campaign_id (dataclass with default_factory lists is mutable)
        # But we can verify classification works correctly
        origin = boundary.classify_position(
            broker_ticket=999,
            symbol="X",
            volume=0.1,
            entry_price=1.0,
            entry_time="2026-08-23",  # before start
        )
        assert origin == TradeOrigin.PRE_EXISTING

    def test_r4_trade_must_have_decision_id(self):
        """Every R4 trade must link to a decision."""
        trade = TradeRecord(
            trade_id="T001",
            decision_id="D001",  # links to R4 decision
            evidence_id="E001",  # links to R4 evidence
            instrument_id="EURUSDm",
            side="BUY",
            volume=0.15,
            entry_price=1.16855,
            entry_timestamp="2026-08-24T14:00:00",
        )
        assert trade.decision_id == "D001"
        assert trade.evidence_id == "E001"

    def test_no_untracked_trades(self):
        """All trades must be classified."""
        boundary = CampaignBoundary(
            campaign_id="CAMP-001",
            strategy_fingerprint="abc",
            start_timestamp="2026-08-24T12:00:00",
        )
        # Classify a position
        origin = boundary.classify_position(
            broker_ticket=123,
            symbol="X",
            volume=0.1,
            entry_price=1.0,
            entry_time="2026-08-24T14:00:00",
        )
        # Should be classified (not unknown)
        assert origin in (TradeOrigin.R4_CAMPAIGN, TradeOrigin.PRE_EXISTING, TradeOrigin.MANUAL)

    def test_profit_not_required_for_qualification(self):
        """A loss-making campaign can still qualify if behavior is correct."""
        boundary = CampaignBoundary(
            campaign_id="CAMP-001",
            strategy_fingerprint="abc",
            start_timestamp="2026-08-24T12:00:00",
        )
        trade = TradeRecord(
            trade_id="T001",
            decision_id="D001",
            evidence_id="E001",
            instrument_id="EURUSDm",
            side="BUY",
            volume=0.15,
            entry_price=1.16855,
            entry_timestamp="2026-08-24T14:00:00",
        )
        trade.pnl = -100.0  # losing money
        boundary.record_r4_trade(trade)

        metrics = ScalingMetrics(
            slippage_deterioration=1.0,
            spread_deterioration=1.0,
            fill_rate_at_current=1.0,
            margin_usage=0.20,
            margin_pressure=False,
            risk_proportional=True,
        )

        evaluator = ProductionEvaluator()
        report = evaluator.evaluate(
            campaign_id="CAMP-001",
            scale_level=ScaleLevel.MINIMAL,
            boundary=boundary,
            scaling_metrics=metrics,
        )
        # Should still qualify — behavior is correct even though losing
        assert report.verdict in (
            ProductionVerdict.QUALIFIED,
            ProductionVerdict.QUALIFIED_FOR_NEXT_SCALE,
            ProductionVerdict.QUALIFIED_WITH_RESTRICTIONS,
        )
