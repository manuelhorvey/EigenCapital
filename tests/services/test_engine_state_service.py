"""Tests for ``paper_trading/services/engine_state_service.py``."""

from datetime import datetime
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest
import pytz

from paper_trading.services.engine_state_service import EngineStateService

# Re-export so ruff F811 doesn't flag class-local re-definitions.
MagicMock  # noqa: B018

ET = pytz.timezone("US/Eastern")


_MOCK_ENGINE_CFG = SimpleNamespace(
    capital=200_000,
    halt={},
    defaults={},
    mt5=SimpleNamespace(enabled=False),
)


def _make_mock_asset(**overrides):
    """Build a mock AssetEngine-like object with minimal attrs."""
    asset = SimpleNamespace(
        mtm_value=overrides.get("mtm_value", 100_000),
        current_value=overrides.get("current_value", 100_000),
        initial_capital=overrides.get("initial_capital", 100_000),
        sl_mult=overrides.get("sl_mult", 1.0),
        tp_mult=overrides.get("tp_mult", 2.5),
        allocation=overrides.get("allocation", 0.0625),
        halt_config=overrides.get("halt_config", {}),
        _last_final_signal=overrides.get("_last_final_signal"),
        _last_stop_out_side=overrides.get("_last_stop_out_side"),
        _last_stop_out_cycle=overrides.get("_last_stop_out_cycle"),
        _total_exits=overrides.get("_total_exits", 0),
        _sl_exits=overrides.get("_sl_exits", 0),
        _last_regime_long_prob=overrides.get("_last_regime_long_prob"),
        _last_regime_row=overrides.get("_last_regime_row"),
        _last_sizing_chain=overrides.get("_last_sizing_chain"),
        _risk_signal=overrides.get("_risk_signal"),
        _shadow_action=overrides.get("_shadow_action"),
        prob_history=overrides.get("prob_history", []),
        trade_log=overrides.get("trade_log", []),
        regime_geometry=overrides.get("regime_geometry", {}),
        refresh_price=lambda: None,
        update_validity=lambda **kw: {"state": "GREEN", "exposure": 1.0},
        get_metrics=lambda: SimpleNamespace(
            to_dict=lambda: {"current_value": 100_000},
            get=lambda key, default=None: {"meta_inference": None, "feature_stability": None}.get(key, default),
        ),
        check_halt_conditions=lambda **kw: {"halted": False, "reasons": [], "soft_warnings": []},
        governance=SimpleNamespace(
            _liquidity_regime="normal",
            _liquidity_sl_mult=1.0,
            _liquidity_size_scalar=1.0,
            _narrative_sl_mult=1.0,
            _narrative_size_scalar=1.0,
            _narrative_active=None,
            _narrative_stale=False,
        ),
        pos_mgr=SimpleNamespace(
            has_position=lambda: False,
            position=None,
            current_value=100_000,
            peak_value=100_000,
            trade_log=[],
        ),
        flush_attribution=lambda: None,
    )
    return asset


def _make_mock_engine(**overrides):
    """Build a mock engine with mock assets."""
    assets = overrides.get("assets", {"EURUSD": _make_mock_asset(), "GBPUSD": _make_mock_asset()})
    engine = SimpleNamespace(
        _engine_cfg=_MOCK_ENGINE_CFG,
        assets=assets,
        _cycle_count=overrides.get("_cycle_count", 0),
        _mtm_cache_value=None,
        _mtm_cache_cycle=-1,
        _rebalance_weights=overrides.get("_rebalance_weights", {}),
        start_date=overrides.get(
            "start_date",
            datetime(2026, 1, 1, tzinfo=ET),
        ),
        last_update=overrides.get(
            "last_update",
            datetime(2026, 1, 1, 0, 0, 1, tzinfo=ET),
        ),
        portfolio_peak_value=overrides.get("portfolio_peak_value"),
        _orchestrator=overrides.get("_orchestrator"),
        state_store=overrides.get(
            "state_store",
            SimpleNamespace(
                save_snapshot=lambda snap: None,
                append_equity_history=lambda rec: None,
            ),
        ),
        broker=overrides.get("broker"),
        _sim_store=overrides.get("_sim_store", SimpleNamespace(capture=lambda **kw: None)),
    )
    return engine


@pytest.fixture
def service():
    engine = _make_mock_engine()
    return EngineStateService(engine)


# ═══════════════════════════════════════════════════════════════════
# compute_mtm_total
# ═══════════════════════════════════════════════════════════════════


class TestComputeMtmTotal:
    def test_sums_asset_mtm_values(self, service):
        total = service.compute_mtm_total()
        assert total == 200_000  # 2 assets × 100_000

    def test_caches_result(self, service):
        first = service.compute_mtm_total()
        second = service.compute_mtm_total()
        assert first == second
        assert service.engine._mtm_cache_value == 200_000


# ═══════════════════════════════════════════════════════════════════
# get_state
# ═══════════════════════════════════════════════════════════════════


class TestGetState:
    def test_returns_portfolio_and_assets(self, service):
        state = service.get_state()
        assert "portfolio" in state
        assert "assets" in state
        assert "EURUSD" in state["assets"]

    def test_each_asset_has_required_keys(self, service):
        state = service.get_state()
        asset = state["assets"]["EURUSD"]
        for key in ("metrics", "halt", "validity_state", "last_signal", "sl_mult", "tp_mult", "sell_only"):
            assert key in asset

    def test_portfolio_has_summary(self, service):
        state = service.get_state()
        p = state["portfolio"]
        assert "total_value" in p
        assert "capital" in p
        assert "open_positions" in p


# ═══════════════════════════════════════════════════════════════════
# _compute_portfolio_summary
# ═══════════════════════════════════════════════════════════════════


class TestComputePortfolioSummary:
    def test_returns_valid_summary(self, service):
        # Need overall_validity >= n to pass (0.5 * n) threshold — 2 assets so >= 1.0
        summary = service._compute_portfolio_summary(overall_validity=1.2, any_halted=False)
        assert summary["total_value"] > 0
        assert summary["execution_state"] == "ACTIVE"

    def test_halted_when_any_asset_halted(self, service):
        summary = service._compute_portfolio_summary(overall_validity=1.2, any_halted=True)
        assert summary["execution_state"] == "HALTED"

    def test_paused_when_validity_low(self, service):
        summary = service._compute_portfolio_summary(overall_validity=0.3, any_halted=False)
        assert summary["execution_state"] == "PAUSED"

    def test_uses_initial_capital_as_denominator(self, service):
        summary = service._compute_portfolio_summary(overall_validity=1.0, any_halted=False)
        assert abs(summary["capital"] - 200_000) < 1
        assert "total_value" in summary


# ═══════════════════════════════════════════════════════════════════
# _extract_pek
# ═══════════════════════════════════════════════════════════════════


class TestExtractPek:
    def test_returns_empty_without_orchestrator(self, service):
        result = EngineStateService._extract_pek(object())
        assert result == {}

    def test_extracts_performance_state(self):
        mock_orch = SimpleNamespace(
            _performance_state=SimpleNamespace(
                outcome_scalar=0.8,
                degradation_scalar=0.2,
                market_scalar=0.5,
                execution_scalar=0.9,
                velocity_scalar=0.3,
                composite_scalar=0.6,
                win_rate_20=0.55,
                consecutive_losses=2,
                r_cumulative_20=5.0,
                calibration_ece=0.02,
                atr_ratio=1.0,
                regime_label="trending",
                slippage_p90=0.001,
                velocity=None,
            ),
            _risk_budget=None,
            _portfolio_snapshot=None,
        )
        result = EngineStateService._extract_pek(mock_orch)
        assert "performance_state" in result
        assert result["performance_state"]["outcome_scalar"] == 0.8
        assert result["performance_state"]["consecutive_losses"] == 2

    def test_extracts_risk_budget(self):
        mock_orch = SimpleNamespace(
            _performance_state=None,
            _risk_budget=SimpleNamespace(
                max_risk_per_trade_pct=0.02,
                max_portfolio_heat=0.15,
                max_concurrent_positions=5,
                volatility_scalar=0.8,
                drawdown_scalar=1.0,
                performance_scalar=0.9,
                velocity_scalar=0.7,
            ),
            _portfolio_snapshot=None,
        )
        result = EngineStateService._extract_pek(mock_orch)
        assert "risk_budget" in result
        assert result["risk_budget"]["max_concurrent_positions"] == 5


# ═══════════════════════════════════════════════════════════════════
# _compute_factor_exposures
# ═══════════════════════════════════════════════════════════════════


class TestComputeFactorExposures:
    def test_returns_empty_without_rebalance_weights(self, service):
        result = service._compute_factor_exposures()
        assert result["exposures"] == {}
        assert result["n_violations"] == 0

    def test_calls_factor_summary_with_weights(self):
        engine = _make_mock_engine(_rebalance_weights={"EURUSD": 0.6, "GBPUSD": 0.4})
        svc = EngineStateService(engine)
        # factor_summary is a local import inside _compute_factor_exposures,
        # so patch at the source module
        with patch("shared.factor_model.summary") as mock_fn:
            mock_fn.return_value = {
                "exposures": {"USD": 0.5},
                "violations": {},
                "n_violations": 0,
                "within_limits": True,
            }
            svc._compute_factor_exposures()
            mock_fn.assert_called_once_with({"EURUSD": 0.6, "GBPUSD": 0.4})


# ═══════════════════════════════════════════════════════════════════
# save_state (integration-level smoke tests)
# ═══════════════════════════════════════════════════════════════════


class TestSaveState:
    def test_saves_snapshot(self, service):
        from paper_trading.state_store import EngineSnapshot

        saved = []

        def capture(snap):
            saved.append(snap)

        service.engine.state_store.save_snapshot = capture

        with (
            patch("paper_trading.services.engine_state_service.LiveSharpeTracker") as mock_sharpe,
            patch("paper_trading.performance.edge_health.get_monitor") as mock_monitor,
            patch("paper_trading.services.engine_state_service.update_engine_metrics"),
        ):
            mock_sharpe.return_value.compute.return_value = {"available": True, "n_cycles": 100}
            mock_monitor.return_value.summary = {"available": True}

            service.save_state()

        assert len(saved) == 1
        assert isinstance(saved[0], EngineSnapshot)
        assert saved[0].portfolio["total_value"] > 0
