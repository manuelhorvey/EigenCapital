"""Tests for PortfolioStateSnapshot contract validation."""
import pytest

from paper_trading.pek.contracts.portfolio_state import (
    AssetGateState,
    ClusterInfo,
    PortfolioStateSnapshot,
    PositionInfo,
)


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

    def test_drawdown_below_minus_one_raises(self):
        with pytest.raises(ValueError):
            _make_minimal_snapshot(drawdown_pct=-1.5)

    def test_drawdown_above_zero_raises(self):
        with pytest.raises(ValueError):
            _make_minimal_snapshot(drawdown_pct=0.5)

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
