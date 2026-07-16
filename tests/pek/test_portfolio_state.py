"""Tests for PortfolioStateSnapshot contract validation."""
import pytest

from paper_trading.pek.contracts.portfolio_state import (
    AssetGateState,
    ClusterInfo,
    PortfolioStateSnapshot,
    PositionInfo,
)
from paper_trading.pek.contracts.risk_budget import RiskBudget
from paper_trading.pek.contracts.performance_state import PerformanceState, RegimeVelocity


def _make_minimal_snapshot(**overrides) -> PortfolioStateSnapshot:
    """Helper to build a minimal valid snapshot with overridable fields."""
    kwargs = dict(
        version=1,
        generated_at=__import__("eigencapital").domain.time.utc_now(),
        mode="production",
        total_equity=100_000.0,
        peak_value=100_000.0,
        drawdown_pct=0.0,
        positions=(),
        total_long_notional=0.0,
        total_short_notional=0.0,
        gross_exposure=0.0,
        net_exposure=0.0,
        open_position_count=0,
        daily_pnl=0.0,
        daily_loss_remaining=1000.0,
        max_daily_loss=2000.0,
        drawdown_remaining=15_000.0,
        leverage_remaining=200_000.0,
        max_leverage=2.0,
        concurrent_remaining=21,
        max_concurrent=21,
        factor_exposures=(),
        factor_limits=(),
        factor_headroom=(),
        clusters=(),
        asset_gates=(),
        max_risk_per_trade_pct=1.0,
        min_risk_per_trade_pct=0.10,
        position_ranking_enabled=False,
    )
    kwargs.update(overrides)
    return PortfolioStateSnapshot(**kwargs)


class TestPortfolioStateSnapshotValidation:
    def test_negative_equity_raises(self):
        with pytest.raises(ValueError, match="total_equity"):
            _make_minimal_snapshot(total_equity=-1.0)

    def test_negative_position_count_raises(self):
        with pytest.raises(ValueError, match="open_position_count"):
            _make_minimal_snapshot(open_position_count=-1)

    def test_drawdown_below_minus_one_clamps(self):
        """drawdown_pct < -1.0 is clamped to -1.0, no longer raises ValueError."""
        snap = _make_minimal_snapshot(drawdown_pct=-1.5)
        assert snap.drawdown_pct == -1.0

    def test_drawdown_above_zero_clamps(self):
        """drawdown_pct > 0.0 is clamped to 0.0, no longer raises ValueError."""
        snap = _make_minimal_snapshot(drawdown_pct=0.5)
        assert snap.drawdown_pct == 0.0

    def test_valid_snapshot_creates_ok(self):
        snap = _make_minimal_snapshot()
        assert snap.total_equity == 100_000.0
        assert snap.open_position_count == 0

    def test_zero_equity_accepted(self):
        snap = _make_minimal_snapshot(total_equity=0.0)
        assert snap.total_equity == 0.0

    def test_remaining_budgets_with_zero_equity(self):
        snap = _make_minimal_snapshot(total_equity=0.0)
        assert snap.daily_loss_remaining == 1000.0
        assert snap.leverage_remaining == 200_000.0


class TestAssetGateState:
    def test_all_ok_true(self):
        g = AssetGateState(
            asset="EURUSD", spread_ok=True, session_ok=True,
            sell_only_ok=True, confidence_ok=True, risk_off_ok=True,
            hysteresis_ok=True, conviction_ok=True,
        )
        assert g.all_ok

    def test_one_false_all_ok_false(self):
        g = AssetGateState(
            asset="EURUSD", spread_ok=True, session_ok=True,
            sell_only_ok=True, confidence_ok=True, risk_off_ok=True,
            hysteresis_ok=False, conviction_ok=True,
        )
        assert not g.all_ok

    def test_to_dict_roundtrip(self):
        g = AssetGateState(
            asset="USDJPY", spread_ok=True, session_ok=False,
            sell_only_ok=True, confidence_ok=True, risk_off_ok=True,
            hysteresis_ok=True, conviction_ok=True,
        )
        d = g.to_dict()
        assert d["asset"] == "USDJPY"
        assert d["session_ok"] is False
        restored = AssetGateState.from_dict(d)
        assert restored == g

    def test_to_dict_roundtrip_all_false(self):
        g = AssetGateState(
            asset="GBPUSD", spread_ok=False, session_ok=False,
            sell_only_ok=False, confidence_ok=False, risk_off_ok=False,
            hysteresis_ok=False, conviction_ok=False,
        )
        restored = AssetGateState.from_dict(g.to_dict())
        assert restored == g
        assert not restored.all_ok


class TestPositionInfoSerialization:
    def test_to_dict_roundtrip(self):
        p = PositionInfo(
            asset="EURUSD", side="long", notional=50000.0,
            entry_price=1.10, current_price=1.12, sl_distance_pct=0.5,
            current_pnl_pct=1.8, mtm_value=50900.0,
        )
        d = p.to_dict()
        assert d["asset"] == "EURUSD"
        assert d["side"] == "long"
        restored = PositionInfo.from_dict(d)
        assert restored == p


class TestClusterInfoSerialization:
    def test_to_dict_roundtrip(self):
        c = ClusterInfo(
            factor_group="CHF", assets=("EURCHF", "USDCHF"),
            dominant_side="short", total_notional=80000.0,
            position_count=2, average_correlation=0.78,
        )
        d = c.to_dict()
        assert d["factor_group"] == "CHF"
        assert d["assets"] == ["EURCHF", "USDCHF"]
        restored = ClusterInfo.from_dict(d)
        assert restored == c

    def test_to_dict_no_dominant_side(self):
        c = ClusterInfo(
            factor_group="COMMODITY", assets=("GC", "CL"),
            dominant_side=None, total_notional=0.0,
            position_count=0, average_correlation=0.0,
        )
        restored = ClusterInfo.from_dict(c.to_dict())
        assert restored == c
        assert restored.dominant_side is None


class TestPortfolioStateSnapshotSerialization:
    def test_roundtrip_minimal(self):
        snap = _make_minimal_snapshot()
        d = snap.to_dict()
        assert d["version"] == 1
        assert d["open_position_count"] == 0
        restored = PortfolioStateSnapshot.from_dict(d)
        assert restored == snap

    def test_roundtrip_with_nested_objects(self):
        from eigencapital.domain.time import utc_now

        snap = PortfolioStateSnapshot(
            version=2,
            generated_at=utc_now(),
            mode="production",
            total_equity=95000.0,
            peak_value=100000.0,
            drawdown_pct=-0.05,
            positions=(
                PositionInfo("EURUSD", "long", 50000.0, 1.10, 1.12, 0.5, 1.8, 50900.0),
                PositionInfo("GBPUSD", "short", 30000.0, 1.25, 1.24, 0.6, -0.8, 29700.0),
            ),
            total_long_notional=50000.0,
            total_short_notional=30000.0,
            gross_exposure=80000.0,
            net_exposure=20000.0,
            open_position_count=2,
            daily_pnl=1500.0,
            daily_loss_remaining=500.0,
            max_daily_loss=2000.0,
            drawdown_remaining=5000.0,
            leverage_remaining=120000.0,
            max_leverage=2.0,
            concurrent_remaining=19,
            max_concurrent=21,
            factor_exposures=(("CHF", -30000.0), ("COMMODITY", 5000.0)),
            factor_limits=(("CHF", -50000.0, 0.0),),
            factor_headroom=(("CHF", 20000.0),),
            clusters=(
                ClusterInfo("CHF", ("EURCHF", "USDCHF"), "short", 80000.0, 2, 0.78),
            ),
            asset_gates=(
                AssetGateState("EURUSD", True, True, True, True, True, True, True),
                AssetGateState("GBPUSD", True, True, True, True, True, True, True),
            ),
            max_risk_per_trade_pct=1.0,
            min_risk_per_trade_pct=0.10,
            position_ranking_enabled=True,
            max_positions_per_cluster=3,
        )
        d = snap.to_dict()
        assert len(d["positions"]) == 2
        assert len(d["clusters"]) == 1
        assert len(d["asset_gates"]) == 2
        assert d["factor_exposures"] == [["CHF", -30000.0], ["COMMODITY", 5000.0]]
        restored = PortfolioStateSnapshot.from_dict(d)
        assert restored == snap

    def test_roundtrip_preserves_datetime(self):
        from datetime import datetime, timezone

        ts = datetime(2026, 7, 16, 10, 30, 0, tzinfo=timezone.utc)
        snap = _make_minimal_snapshot(generated_at=ts)
        d = snap.to_dict()
        assert d["generated_at"] == "2026-07-16T10:30:00+00:00"
        restored = PortfolioStateSnapshot.from_dict(d)
        assert restored.generated_at == ts


class TestRiskBudgetSerialization:
    def test_to_dict_roundtrip(self):
        rb = RiskBudget(
            max_risk_per_trade_pct=0.5,
            max_portfolio_heat=2.0,
            max_concurrent_positions=10,
            volatility_scalar=0.8,
            drawdown_scalar=0.6,
            performance_scalar=1.0,
            velocity_scalar=0.9,
        )
        d = rb.to_dict()
        assert d["max_risk_per_trade_pct"] == 0.5
        assert d["max_concurrent_positions"] == 10
        restored = RiskBudget.from_dict(d)
        assert restored == rb

    def test_to_dict_roundtrip_minimal(self):
        rb = RiskBudget(
            max_risk_per_trade_pct=1.0,
            max_portfolio_heat=3.0,
            max_concurrent_positions=21,
            volatility_scalar=1.0,
            drawdown_scalar=1.0,
            performance_scalar=1.0,
            velocity_scalar=1.0,
        )
        restored = RiskBudget.from_dict(rb.to_dict())
        assert restored == rb
        from datetime import datetime, timezone

        ts = datetime(2026, 7, 16, 10, 30, 0, tzinfo=timezone.utc)
        snap = _make_minimal_snapshot(generated_at=ts)
        d = snap.to_dict()
        assert d["generated_at"] == "2026-07-16T10:30:00+00:00"
        restored = PortfolioStateSnapshot.from_dict(d)
        assert restored.generated_at == ts
