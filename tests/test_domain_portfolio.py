from __future__ import annotations

from datetime import datetime, timezone

import pytest

from eigencapital.domain.entities.portfolio import Portfolio, PortfolioSummary


class TestPortfolio:
    @pytest.fixture
    def portfolio(self):
        return Portfolio(
            total_capital=100000.0,
            cash_buffer=10000.0,
            peak_value=110000.0,
            start_date=datetime(2026, 1, 1, tzinfo=timezone.utc),
            last_update=datetime(2026, 6, 30, tzinfo=timezone.utc),
            asset_allocations={"EURUSD": 20000.0, "GBPUSD": 15000.0},
            risk_parity_weights={"EURUSD": 0.5, "GBPUSD": 0.5},
        )

    def test_allocated_capital(self, portfolio):
        assert portfolio.allocated_capital == 35000.0

    def test_allocation_ratio(self, portfolio):
        expected = 35000.0 / 100000.0
        assert portfolio.allocation_ratio == expected

    def test_drawdown_below_peak(self, portfolio):
        dd = portfolio.drawdown(100000.0)
        assert dd < 0.0
        assert abs(dd - (-0.0909090909)) < 1e-6

    def test_drawdown_at_peak(self, portfolio):
        dd = portfolio.drawdown(110000.0)
        assert dd == 0.0

    def test_drawdown_above_peak(self, portfolio):
        dd = portfolio.drawdown(120000.0)
        assert dd > 0.0

    def test_update_peak_higher(self, portfolio):
        portfolio.update_peak(120000.0)
        assert portfolio.peak_value == 120000.0

    def test_update_peak_lower_no_change(self, portfolio):
        portfolio.update_peak(100000.0)
        assert portfolio.peak_value == 110000.0

    def test_total_return_positive(self, portfolio):
        tr = portfolio.total_return(120000.0)
        assert tr == 0.2

    def test_total_return_negative(self, portfolio):
        tr = portfolio.total_return(80000.0)
        assert tr == -0.2

    def test_no_allocations(self):
        p = Portfolio(100000.0, 10000.0, 110000.0, datetime(2026, 1, 1, tzinfo=timezone.utc), datetime(2026, 6, 30, tzinfo=timezone.utc))
        assert p.allocated_capital == 0.0
        assert p.allocation_ratio == 0.0


class TestPortfolioSummary:
    def test_default_execution_state(self):
        ps = PortfolioSummary(
            total_value=100000.0,
            mtm_value=100000.0,
            total_return_pct=0.0,
            realized_return_pct=0.0,
            unrealized_pnl=0.0,
            days_running=180,
            open_positions=5,
            closed_trades=20,
        )
        assert ps.execution_state == "ACTIVE"

    def test_full_construction(self):
        ps = PortfolioSummary(
            total_value=110000.0,
            mtm_value=110000.0,
            total_return_pct=10.0,
            realized_return_pct=8.0,
            unrealized_pnl=2000.0,
            days_running=180,
            open_positions=5,
            closed_trades=20,
            execution_state="HALTED",
            average_validity_exposure=0.75,
            portfolio_drawdown_pct=5.0,
            capital=100000.0,
            allocations={"EURUSD": 0.5, "GBPUSD": 0.5},
        )
        assert ps.execution_state == "HALTED"
        assert ps.average_validity_exposure == 0.75
        assert ps.portfolio_drawdown_pct == 5.0
