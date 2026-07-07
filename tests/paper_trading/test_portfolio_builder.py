"""Tests for paper_trading/portfolio_builder.py."""

from __future__ import annotations

import pytest

from paper_trading.portfolio_builder import (
    JPY_CARRY_CLUSTER,
    JPY_CARRY_MAX_ALLOC,
    cluster_risk_report,
)


class TestClusterRiskReport:
    def test_empty_portfolio_no_warnings(self):
        warnings = cluster_risk_report({})
        assert warnings == []

    def test_jpy_cluster_under_limit(self):
        portfolio = {
            "NZDJPY": {"alloc": 0.10},
            "USDJPY": {"alloc": 0.10},
        }
        warnings = cluster_risk_report(portfolio)
        assert warnings == []

    def test_jpy_cluster_exceeds_limit(self):
        portfolio = {
            "NZDJPY": {"alloc": 0.20},
            "USDJPY": {"alloc": 0.15},
            "AUDJPY": {"alloc": 0.10},
        }
        warnings = cluster_risk_report(portfolio)
        assert len(warnings) == 1
        assert "JPY-carry" in warnings[0]
        assert "45%" in warnings[0]

    def test_all_jpy_assets_detected(self):
        portfolio = {name: {"alloc": 0.10} for name in JPY_CARRY_CLUSTER}
        warnings = cluster_risk_report(portfolio)
        assert len(warnings) == 1
        assert "JPY-carry" in warnings[0]

    def test_mixed_portfolio_no_warning(self):
        portfolio = {
            "EURUSD": {"alloc": 0.30},
            "GBPUSD": {"alloc": 0.30},
            "NZDJPY": {"alloc": 0.30},
        }
        warnings = cluster_risk_report(portfolio)
        assert warnings == []  # single JPY asset at 30% < 40


class TestConstants:
    def test_jpy_carry_cluster_has_expected_assets(self):
        assert "NZDJPY" in JPY_CARRY_CLUSTER
        assert "USDJPY" in JPY_CARRY_CLUSTER
        assert "EURUSD" not in JPY_CARRY_CLUSTER


class TestBuildPaperPortfolioSmoke:
    def test_returns_dict_with_assets(self):
        from paper_trading.portfolio_builder import build_paper_portfolio

        result = build_paper_portfolio({})
        assert isinstance(result, dict)
        if result:
            entry = next(iter(result.values()))
            assert "ticker" in entry
            assert "alloc" in entry
