"""Phase 2 Economic Validation Tests — verify R4 evidence collection works correctly.

Tests the R4 Live Qualification Dataset and Phase 2 report generator
to ensure evidence collection is working correctly.
"""

from __future__ import annotations

from eigencapital.production_qual.live_qualification import (
    EntryQuality,
    ExecutionFidelity,
    ExitReason,
    OperationalEvent,
    PortfolioRiskSnapshot,
    R4LiveQualificationDataset,
)
from eigencapital.production_qual.phase2_report import Phase2ReportGenerator


class TestQualificationDataset:
    """Test R4 Live Qualification Dataset."""

    def test_dataset_creation(self):
        """Dataset must be created with campaign ID."""
        dataset = R4LiveQualificationDataset(campaign_id="TEST-001")
        assert dataset._campaign_id == "TEST-001"
        assert dataset._stats["total_entries"] == 0

    def test_record_entry(self):
        """Must record trade entries correctly."""
        dataset = R4LiveQualificationDataset(campaign_id="TEST-001")

        execution = ExecutionFidelity(
            signal_timestamp="2026-08-26T10:00:00Z",
            intended_symbol="EURUSD",
            intended_direction=1.0,
            intended_weight=0.15,
            requested_price=1.0800,
            fill_price=1.0801,
            spread=0.0001,
            slippage=0.0001,
            execution_latency_ms=50.0,
            rejection_status="FILLED",
            partial_fill_qty=0.01,
            swap_daily=-0.50,
            commission=-1.00,
        )

        trade = dataset.record_entry(
            symbol="EURUSD",
            side="BUY",
            volume=0.01,
            execution=execution,
        )

        assert trade.trade_id.startswith("TR-")
        assert trade.symbol == "EURUSD"
        assert trade.side == "BUY"
        assert trade.execution is not None
        assert dataset._stats["total_entries"] == 1
        assert dataset._stats["open_positions"] == 1

    def test_record_exit(self):
        """Must record trade exits correctly."""
        dataset = R4LiveQualificationDataset(campaign_id="TEST-001")

        # Record entry
        execution = ExecutionFidelity(
            signal_timestamp="2026-08-26T10:00:00Z",
            intended_symbol="EURUSD",
            intended_direction=1.0,
            intended_weight=0.15,
            requested_price=1.0800,
            fill_price=1.0801,
            spread=0.0001,
            slippage=0.0001,
            execution_latency_ms=50.0,
            rejection_status="FILLED",
            partial_fill_qty=0.01,
            swap_daily=-0.50,
            commission=-1.00,
        )

        trade = dataset.record_entry(
            symbol="EURUSD",
            side="BUY",
            volume=0.01,
            execution=execution,
        )

        # Record exit
        updated = dataset.record_exit(
            trade_id=trade.trade_id,
            exit_price=1.0850,
            exit_reason=ExitReason.ROTATION.value,
            realized_pnl=50.0,
            net_pnl=45.0,
            total_costs=5.0,
        )

        assert updated is not None
        assert updated.exit_price == 1.0850
        assert updated.exit_reason == "ROTATION"
        assert updated.net_pnl == 45.0
        assert dataset._stats["total_exits"] == 1
        assert dataset._stats["open_positions"] == 0
        assert dataset._stats["winning_trades"] == 1

    def test_losing_trade(self):
        """Must track losing trades correctly."""
        dataset = R4LiveQualificationDataset(campaign_id="TEST-001")

        execution = ExecutionFidelity(
            signal_timestamp="2026-08-26T10:00:00Z",
            intended_symbol="EURUSD",
            intended_direction=1.0,
            intended_weight=0.15,
            requested_price=1.0800,
            fill_price=1.0801,
            spread=0.0001,
            slippage=0.0001,
            execution_latency_ms=50.0,
            rejection_status="FILLED",
            partial_fill_qty=0.01,
            swap_daily=-0.50,
            commission=-1.00,
        )

        trade = dataset.record_entry(
            symbol="EURUSD",
            side="BUY",
            volume=0.01,
            execution=execution,
        )

        updated = dataset.record_exit(
            trade_id=trade.trade_id,
            exit_price=1.0750,
            exit_reason=ExitReason.CATASTROPHIC_SL.value,
            realized_pnl=-50.0,
            net_pnl=-55.0,
            total_costs=5.0,
        )

        assert updated.net_pnl == -55.0
        assert dataset._stats["losing_trades"] == 1
        assert dataset._stats["winning_trades"] == 0

    def test_update_entry_quality(self):
        """Must update entry quality metrics."""
        dataset = R4LiveQualificationDataset(campaign_id="TEST-001")

        execution = ExecutionFidelity(
            signal_timestamp="2026-08-26T10:00:00Z",
            intended_symbol="EURUSD",
            intended_direction=1.0,
            intended_weight=0.15,
            requested_price=1.0800,
            fill_price=1.0801,
            spread=0.0001,
            slippage=0.0001,
            execution_latency_ms=50.0,
            rejection_status="FILLED",
            partial_fill_qty=0.01,
            swap_daily=-0.50,
            commission=-1.00,
        )

        trade = dataset.record_entry(
            symbol="EURUSD",
            side="BUY",
            volume=0.01,
            execution=execution,
        )

        entry_quality = EntryQuality(
            forward_return_1d=0.001,
            forward_return_5d=0.005,
            mae=-0.002,
            mfe=0.008,
            signal_strength_percentile=75.0,
            regime_at_entry="LOW_VOL",
        )

        dataset.update_entry_quality(trade.trade_id, entry_quality)

        updated_trade = dataset.get_trade(trade.trade_id)
        assert updated_trade.entry_quality is not None
        assert updated_trade.entry_quality.mae == -0.002
        assert updated_trade.entry_quality.signal_strength_percentile == 75.0

    def test_compute_economics(self):
        """Must compute economics correctly."""
        dataset = R4LiveQualificationDataset(campaign_id="TEST-001")

        # Add multiple trades (need >= 10 for sufficient_data)
        for i in range(15):
            execution = ExecutionFidelity(
                signal_timestamp=f"2026-08-26T{10 + i}:00:00Z",
                intended_symbol="EURUSD",
                intended_direction=1.0,
                intended_weight=0.15,
                requested_price=1.0800,
                fill_price=1.0801,
                spread=0.0001,
                slippage=0.0001,
                execution_latency_ms=50.0,
                rejection_status="FILLED",
                partial_fill_qty=0.01,
                swap_daily=-0.50,
                commission=-1.00,
            )

            trade = dataset.record_entry(
                symbol="EURUSD",
                side="BUY",
                volume=0.01,
                execution=execution,
            )

            # 10 winners, 5 losers
            pnl = 50.0 if i < 10 else -30.0
            dataset.record_exit(
                trade_id=trade.trade_id,
                exit_price=1.0850 if pnl > 0 else 1.0750,
                exit_reason=ExitReason.ROTATION.value,
                realized_pnl=pnl,
                net_pnl=pnl - 5.0,
                total_costs=5.0,
            )

        economics = dataset.compute_economics()

        assert economics["sufficient_data"] is True
        assert economics["total_trades"] == 15
        assert economics["winning_trades"] == 10
        assert economics["losing_trades"] == 5
        assert economics["win_rate"] == 10 / 15
        assert economics["expectancy_per_trade"] > 0

    def test_record_risk_snapshot(self):
        """Must record portfolio risk snapshots."""
        dataset = R4LiveQualificationDataset(campaign_id="TEST-001")

        snapshot = PortfolioRiskSnapshot(
            timestamp="2026-08-26T12:00:00Z",
            gross_exposure=1.5,
            net_exposure=0.3,
            long_exposure=0.9,
            short_exposure=0.6,
            fx_exposure=1.2,
            commodity_exposure=0.2,
            index_exposure=0.1,
            position_count=15,
            drawdown_pct=0.02,
            daily_loss=0.0,
            margin_utilization=0.45,
        )

        dataset.record_risk_snapshot(snapshot)
        assert len(dataset._risk_snapshots) == 1

    def test_record_operational_event(self):
        """Must record operational events."""
        dataset = R4LiveQualificationDataset(campaign_id="TEST-001")

        event = OperationalEvent(
            event_type="disconnect",
            timestamp="2026-08-26T12:00:00Z",
            detection_time_ms=100.0,
            containment_time_ms=500.0,
            recovery_time_ms=2000.0,
            success=True,
        )

        dataset.record_operational_event(event)
        assert len(dataset._operational_events) == 1

    def test_qualification_report(self):
        """Must generate qualification report."""
        dataset = R4LiveQualificationDataset(campaign_id="TEST-001")

        # Add some trades
        for i in range(3):
            execution = ExecutionFidelity(
                signal_timestamp=f"2026-08-26T{10 + i}:00:00Z",
                intended_symbol="EURUSD",
                intended_direction=1.0,
                intended_weight=0.15,
                requested_price=1.0800,
                fill_price=1.0801,
                spread=0.0001,
                slippage=0.0001,
                execution_latency_ms=50.0,
                rejection_status="FILLED",
                partial_fill_qty=0.01,
                swap_daily=-0.50,
                commission=-1.00,
            )

            trade = dataset.record_entry(
                symbol="EURUSD",
                side="BUY",
                volume=0.01,
                execution=execution,
            )

            dataset.record_exit(
                trade_id=trade.trade_id,
                exit_price=1.0850,
                exit_reason=ExitReason.ROTATION.value,
                realized_pnl=50.0,
                net_pnl=45.0,
                total_costs=5.0,
            )

        report = dataset.compute_qualification_report()

        assert report["campaign_id"] == "TEST-001"
        assert "economics" in report
        assert "gates" in report
        assert report["stats"]["total_entries"] == 3


class TestPhase2Report:
    """Test Phase 2 report generation."""

    def test_report_generation(self):
        """Must generate complete Phase 2 report."""
        dataset = R4LiveQualificationDataset(campaign_id="TEST-001")

        # Add trades
        for i in range(5):
            execution = ExecutionFidelity(
                signal_timestamp=f"2026-08-26T{10 + i}:00:00Z",
                intended_symbol="EURUSD",
                intended_direction=1.0,
                intended_weight=0.15,
                requested_price=1.0800,
                fill_price=1.0801,
                spread=0.0001,
                slippage=0.0001,
                execution_latency_ms=50.0,
                rejection_status="FILLED",
                partial_fill_qty=0.01,
                swap_daily=-0.50,
                commission=-1.00,
            )

            trade = dataset.record_entry(
                symbol="EURUSD",
                side="BUY",
                volume=0.01,
                execution=execution,
            )

            pnl = 50.0 if i < 3 else -30.0
            dataset.record_exit(
                trade_id=trade.trade_id,
                exit_price=1.0850 if pnl > 0 else 1.0750,
                exit_reason=ExitReason.ROTATION.value,
                realized_pnl=pnl,
                net_pnl=pnl - 5.0,
                total_costs=5.0,
            )

        generator = Phase2ReportGenerator(dataset)
        report = generator.generate()

        assert report.campaign_id == "TEST-001"
        assert report.total_trades == 5
        assert report.verdict in ("PASS", "PENDING", "BLOCKED")

    def test_report_markdown(self):
        """Must generate valid markdown report."""
        dataset = R4LiveQualificationDataset(campaign_id="TEST-001")

        execution = ExecutionFidelity(
            signal_timestamp="2026-08-26T10:00:00Z",
            intended_symbol="EURUSD",
            intended_direction=1.0,
            intended_weight=0.15,
            requested_price=1.0800,
            fill_price=1.0801,
            spread=0.0001,
            slippage=0.0001,
            execution_latency_ms=50.0,
            rejection_status="FILLED",
            partial_fill_qty=0.01,
            swap_daily=-0.50,
            commission=-1.00,
        )

        trade = dataset.record_entry(
            symbol="EURUSD",
            side="BUY",
            volume=0.01,
            execution=execution,
        )

        dataset.record_exit(
            trade_id=trade.trade_id,
            exit_price=1.0850,
            exit_reason=ExitReason.ROTATION.value,
            realized_pnl=50.0,
            net_pnl=45.0,
            total_costs=5.0,
        )

        generator = Phase2ReportGenerator(dataset)
        report = generator.generate()
        markdown = report.to_markdown()

        assert "# R4 Live Economic Qualification Report" in markdown
        assert "ENTRY" in markdown or "Entry" in markdown
        assert "EXECUTION" in markdown or "Execution" in markdown
        assert "P&L" in markdown or "Pnl" in markdown


class TestPhase2Gates:
    """Test Phase 2 qualification gates."""

    def test_insufficient_data_gate(self):
        """Gate must fail with insufficient data."""
        dataset = R4LiveQualificationDataset(campaign_id="TEST-001")

        economics = dataset.compute_economics()
        assert economics["sufficient_data"] is False

    def test_sufficient_data_gate(self):
        """Gate must pass with sufficient data."""
        dataset = R4LiveQualificationDataset(campaign_id="TEST-001")

        # Add 20 winning trades
        for i in range(20):
            execution = ExecutionFidelity(
                signal_timestamp=f"2026-08-26T{10 + i}:00:00Z",
                intended_symbol="EURUSD",
                intended_direction=1.0,
                intended_weight=0.15,
                requested_price=1.0800,
                fill_price=1.0801,
                spread=0.0001,
                slippage=0.0001,
                execution_latency_ms=50.0,
                rejection_status="FILLED",
                partial_fill_qty=0.01,
                swap_daily=-0.50,
                commission=-1.00,
            )

            trade = dataset.record_entry(
                symbol="EURUSD",
                side="BUY",
                volume=0.01,
                execution=execution,
            )

            dataset.record_exit(
                trade_id=trade.trade_id,
                exit_price=1.0850,
                exit_reason=ExitReason.ROTATION.value,
                realized_pnl=50.0,
                net_pnl=45.0,
                total_costs=5.0,
            )

        economics = dataset.compute_economics()
        assert economics["sufficient_data"] is True
        assert economics["expectancy_per_trade"] > 0
        assert economics["win_rate"] == 1.0
