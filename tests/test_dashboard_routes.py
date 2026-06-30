from __future__ import annotations

import contextlib
import json
import os
import tempfile
from unittest.mock import MagicMock, patch

import pytest

from paper_trading.api import common
from paper_trading.api.routes import (
    GET_ROUTES,
    GET_ROUTES_PREFIX,
    handle_analytics_snapshot,
    handle_attribution_trades,
    handle_equity_history,
    handle_execution_slippage,
    handle_governance,
    handle_health,
    handle_health_asset,
    handle_liquidity,
    handle_logs,
    handle_narrative,
    handle_narrative_confirm,
    handle_ping,
    handle_psi,
    handle_risk,
    handle_risk_asset,
    handle_risk_parity,
    handle_shadow_actions,
    handle_shadow_actions_asset,
    handle_shadow_summary,
    handle_shadow_trades_route,
    handle_state,
    handle_trade_outcomes,
    handle_trades,
    handle_volatility,
    handle_weekly_review,
    handle_weekly_review_acknowledge,
)
from paper_trading.state_store import EngineSnapshot, StateStore

_STORE_MODULES = [
    "paper_trading.api.state_routes",
    "paper_trading.api.analytics_routes",
    "paper_trading.api.shadow_routes",
    "paper_trading.api.governance_routes",
    "paper_trading.api.asset_routes",
]


@pytest.fixture(autouse=True)
def _clear_cache():
    common._CACHE.clear()


@pytest.fixture
def tmp_store(tmp_path):
    store = StateStore(str(tmp_path))
    with contextlib.ExitStack() as stack:
        for mod in _STORE_MODULES:
            stack.enter_context(patch(f"{mod}._STORE", store))
        yield store


@pytest.fixture
def sample_snapshot():
    return EngineSnapshot(
        timestamp="2026-06-11T12:00:00",
        portfolio={
            "total_value": 100000.0,
            "capital": 100000.0,
            "allocations": {"EURUSD": 0.1},
            "open_positions": 0,
            "closed_trades": 10,
            "execution_state": "ACTIVE",
        },
        assets={
            "EURUSD": {
                "metrics": {
                    "position": {"current_vol": 0.005},
                    "psi_drift": {
                        "per_feature": {"feature_a": 0.05},
                        "worst_classification": "NO_DRIFT",
                        "moderate_count": 0,
                        "severe_count": 0,
                        "psi_ok": True,
                        "penalty": 0.0,
                    },
                },
                "last_signal": {"signal": "LONG", "confidence": 75},
                "liquidity_regime": "NORMAL",
                "liquidity_sl_mult": 1.0,
                "liquidity_size_scalar": 1.0,
                "narrative_sl_mult": 1.0,
                "narrative_size_scalar": 1.0,
                "narrative_regime": "NEUTRAL",
                "narrative_stale": False,
                "regime_geometry": {"geometry_type": "normal"},
                "halt": {"halted": False},
                "soft_warnings": [],
            }
        },
        engine_status={
            "initialized": True,
            "last_update": "2026-06-11T12:00:00",
            "start_time": "2026-06-11T00:00:00",
        },
        halt_conditions={"max_drawdown_pct": 0.15},
        shadow_actions={"EURUSD": {"action_type": "NONE", "exposure_adjustment": 1.0}},
        risk_parity={"EURUSD": {"weight": 0.5}},
    )


class TestPing:
    def test_ping_returns_ok(self):
        result = handle_ping("/ping", {})
        assert json.loads(result) == {"status": "ok"}


class TestState:
    def test_state_with_snapshot(self, tmp_store, sample_snapshot):
        tmp_store.save_snapshot(sample_snapshot)
        result = handle_state("/state.json", {})
        data = json.loads(result)
        assert data["portfolio"]["total_value"] == 100000.0
        assert "EURUSD" in data["assets"]
        assert data["engine_status"]["market_closed"] is not None

    def test_state_without_snapshot(self, tmp_store):
        result = handle_state("/state.json", {})
        data = json.loads(result)
        assert data["engine_status"]["initialized"] is True
        assert "allocations" in data["portfolio"]


class TestTrades:
    def test_trades_empty(self, tmp_store):
        result = handle_trades("/trades.json", {"limit": "10", "offset": "0"})
        assert json.loads(result) == []

    def test_trades_with_data(self, tmp_store):
        trade = {
            "asset": "EURUSD",
            "side": "buy",
            "entry": 1.0500,
            "exit": 1.0600,
            "entry_date": "2026-06-01",
            "exit_date": "2026-06-10",
            "reason": "tp",
        }
        tmp_store.append_trade(trade)
        result = handle_trades("/trades.json", {"limit": "10", "offset": "0"})
        data = json.loads(result)
        assert len(data) == 1
        assert data[0]["asset"] == "EURUSD"


class TestEquityHistory:
    def test_empty(self, tmp_store):
        result = handle_equity_history("/equity_history.json", {})
        assert json.loads(result) == []

    def test_with_data(self, tmp_store):
        record = {
            "timestamp": "2026-06-01T00:00:00",
            "portfolio_value": 100000.0,
            "portfolio_return": 0.05,
            "drawdown": 0.0,
            "gross_exposure": 0.5,
            "net_exposure": 0.3,
        }
        tmp_store.append_equity_history(record)
        result = handle_equity_history("/equity_history.json", {})
        data = json.loads(result)
        assert len(data) == 1
        assert data[0]["portfolio_value"] == 100000.0


class TestLogs:
    def test_no_log_file(self):
        with patch("paper_trading.api.state_routes.LOG_PATH", "/nonexistent/engine.log"):
            result = handle_logs("/logs", {})
            assert result == "[no log file yet]"

    def test_reads_log_file(self, tmp_path):
        log_file = tmp_path / "engine.log"
        log_file.write_text("line1\nline2\nline3\nServer stopped.\nline4\n", encoding="utf-8")
        with patch("paper_trading.api.state_routes.LOG_PATH", str(log_file)):
            result = handle_logs("/logs", {})
            assert "line4" in result


class TestVolatility:
    def test_no_snapshot(self, tmp_store):
        result = handle_volatility("/volatility.json", {})
        assert json.loads(result) == []

    def test_with_snapshot_single_asset(self, tmp_store, sample_snapshot):
        tmp_store.save_snapshot(sample_snapshot)
        with patch("paper_trading.api.state_routes.get_vol_baselines", return_value={"EURUSD": 0.0048}):
            result = handle_volatility("/volatility.json", {})
            data = json.loads(result)
            assert len(data) == 1
            assert data[0]["asset"] == "EURUSD"


class TestShadowActions:
    def test_no_snapshot(self, tmp_store):
        result = handle_shadow_actions("/shadow-actions", {})
        assert json.loads(result) == {}

    def test_with_snapshot(self, tmp_store, sample_snapshot):
        tmp_store.save_snapshot(sample_snapshot)
        result = handle_shadow_actions("/shadow-actions", {})
        data = json.loads(result)
        assert "EURUSD" in data
        assert data["EURUSD"]["action_type"] == "NONE"

    def test_single_asset_found(self, tmp_store, sample_snapshot):
        tmp_store.save_snapshot(sample_snapshot)
        data, status = handle_shadow_actions_asset("/shadow-actions/EURUSD.json", {})
        assert status == 200
        assert json.loads(data)["action_type"] == "NONE"

    def test_single_asset_not_found(self, tmp_store, sample_snapshot):
        tmp_store.save_snapshot(sample_snapshot)
        data, status = handle_shadow_actions_asset("/shadow-actions/UNKNOWN.json", {})
        assert status == 404
        assert "Not found" in json.loads(data)["error"]


class TestRiskParity:
    def test_no_snapshot(self, tmp_store):
        result = handle_risk_parity("/risk-parity.json", {})
        assert json.loads(result) == {}

    def test_with_snapshot(self, tmp_store, sample_snapshot):
        tmp_store.save_snapshot(sample_snapshot)
        result = handle_risk_parity("/risk-parity.json", {})
        assert json.loads(result)["EURUSD"]["weight"] == 0.5


class TestLiquidity:
    def test_no_snapshot(self, tmp_store):
        result = handle_liquidity("/liquidity.json", {})
        assert json.loads(result) == {}

    def test_with_snapshot(self, tmp_store, sample_snapshot):
        tmp_store.save_snapshot(sample_snapshot)
        result = handle_liquidity("/liquidity.json", {})
        data = json.loads(result)
        assert data["EURUSD"]["regime"] == "NORMAL"
        assert data["EURUSD"]["sl_mult"] == 1.0


class TestPsi:
    def test_no_snapshot(self, tmp_store):
        result = handle_psi("/psi.json", {})
        assert json.loads(result) == {}

    def test_with_snapshot(self, tmp_store, sample_snapshot):
        tmp_store.save_snapshot(sample_snapshot)
        result = handle_psi("/psi.json", {})
        data = json.loads(result)
        assert "EURUSD" in data
        assert data["EURUSD"]["psi_ok"] is True
        assert data["EURUSD"]["per_feature"]["feature_a"] == 0.05


class TestGovernance:
    def test_no_snapshot(self, tmp_store):
        result = handle_governance("/governance.json", {})
        assert json.loads(result) == {}

    def test_with_snapshot(self, tmp_store, sample_snapshot):
        tmp_store.save_snapshot(sample_snapshot)
        result = handle_governance("/governance.json", {})
        data = json.loads(result)
        assert "EURUSD" in data
        assert data["EURUSD"]["validity_state"] == "YELLOW"


class TestRisk:
    def test_calls_get_latest(self):
        with patch("paper_trading.api.governance_routes._get_risk_latest", return_value={"EURUSD": {"level": "LOW"}}):
            result = handle_risk("/risk.json", {})
            assert json.loads(result)["EURUSD"]["level"] == "LOW"

    def test_single_asset_found(self):
        with patch("paper_trading.api.governance_routes._get_risk_latest", return_value={"level": "LOW"}):
            data, status = handle_risk_asset("/risk/EURUSD.json", {})
            assert status == 200
            assert json.loads(data)["level"] == "LOW"

    def test_single_asset_not_found(self):
        with patch("paper_trading.api.governance_routes._get_risk_latest", return_value=None):
            data, status = handle_risk_asset("/risk/UNKNOWN.json", {})
            assert status == 404


class TestHealth:
    def test_calls_compute_all(self):
        with patch("paper_trading.api.governance_routes._compute_health_all", return_value={"EURUSD": {"score": 0.8}}):
            result = handle_health("/health.json", {})
            assert json.loads(result)["EURUSD"]["score"] == 0.8

    def test_single_asset_found(self):
        with patch("paper_trading.api.governance_routes._get_health_latest", return_value={"score": 0.8}):
            data, status = handle_health_asset("/health/EURUSD.json", {})
            assert status == 200
            assert json.loads(data)["score"] == 0.8

    def test_single_asset_not_found(self):
        with patch("paper_trading.api.governance_routes._get_health_latest", return_value=None):
            data, status = handle_health_asset("/health/UNKNOWN.json", {})
            assert status == 404


class TestNarrative:
    def test_calls_get_narrative_status(self):
        with patch("paper_trading.api.governance_routes.get_narrative_status", return_value={"status": "NEUTRAL"}):
            result = handle_narrative("/narrative.json", {})
            assert json.loads(result)["status"] == "NEUTRAL"


class TestTradeOutcomes:
    def test_no_outcomes(self, tmp_store):
        result = handle_trade_outcomes("/trade-outcomes.json", {})
        data = json.loads(result)
        assert data["overall"] == {}

    def test_with_outcomes(self, tmp_store):
        tmp_store.append_trade({
            "asset": "EURUSD", "entry": 1.05, "exit": 1.06,
            "entry_date": "2026-06-01", "exit_date": "2026-06-10",
            "reason": "tp", "return": 100.0, "realized_r": 2.0,
        })
        tmp_store.append_trade({
            "asset": "EURUSD", "entry": 1.06, "exit": 1.05,
            "entry_date": "2026-06-02", "exit_date": "2026-06-11",
            "reason": "sl", "return": -50.0, "realized_r": -1.0,
        })
        result = handle_trade_outcomes("/trade-outcomes.json", {})
        data = json.loads(result)
        assert data["overall"]["win_rate"] == 0.5
        assert data["overall"]["tp_rate"] == 0.5
        assert data["overall"]["sl_rate"] == 0.5


class TestWeeklyReview:
    def test_calls_compute_weekly_review(self, tmp_store):
        with patch("paper_trading.api.governance_routes.compute_weekly_review", return_value={"summary": "ok"}):
            result = handle_weekly_review("/weekly-review.json", {})
            assert json.loads(result)["summary"] == "ok"


class TestNarrativeConfirm:
    def test_confirm_ok(self):
        with patch("paper_trading.api.governance_routes.confirm_pending_narrative", return_value=True):
            data, status = handle_narrative_confirm(b"")
            assert status == 200
            assert json.loads(data)["status"] == "confirmed"

    def test_confirm_fail(self):
        with patch("paper_trading.api.governance_routes.confirm_pending_narrative", return_value=False):
            data, status = handle_narrative_confirm(b"")
            assert status == 400


class TestWeeklyReviewAcknowledge:
    def test_acknowledge_new(self, tmp_store):
        data, status = handle_weekly_review_acknowledge(b"")
        assert status == 200
        parsed = json.loads(data)
        assert parsed["status"] == "ok"

    def test_acknowledge_appends(self, tmp_store, tmp_path):
        rlp = os.path.join(str(tmp_path), "data", "live", "review_log.json")
        os.makedirs(os.path.dirname(rlp), exist_ok=True)
        with open(rlp, "w") as f:
            json.dump([], f)
        tmp_store.review_log_path = rlp
        handle_weekly_review_acknowledge(b"")
        handle_weekly_review_acknowledge(b"")
        with open(rlp) as f:
            entries = json.load(f)
            assert len(entries) == 2


class TestAnalyticsSnapshot:
    def test_no_snapshot(self, tmp_store):
        result = handle_analytics_snapshot("/analytics/snapshot.json", {})
        assert json.loads(result)["overall"] == {}

    def test_with_snapshot(self, tmp_store, tmp_path):
        snap = {"overall": {"win_rate": 0.6}, "by_archetype": {}, "by_regime": {}, "shadow": {}}
        snap_path = os.path.join(str(tmp_path), "data", "live", "analytics_snapshot.json")
        os.makedirs(os.path.dirname(snap_path), exist_ok=True)
        with open(snap_path, "w") as f:
            json.dump(snap, f)
        result = handle_analytics_snapshot("/analytics/snapshot.json", {})
        assert json.loads(result)["overall"]["win_rate"] == 0.6


class TestAttributionTrades:
    def test_empty(self, tmp_store):
        result = handle_attribution_trades("/attribution/trades.json", {})
        assert json.loads(result) == []


class TestExecutionSlippage:
    def test_empty(self, tmp_store):
        result = handle_execution_slippage("/execution/slippage.json", {})
        data = json.loads(result)
        assert data == {"entry_slippage": [], "exit_slippage": []}


class TestShadowTrades:
    def test_empty(self, tmp_store):
        result = handle_shadow_trades_route("/shadow/trades.json", {})
        assert json.loads(result) == []


class TestShadowSummary:
    def test_empty(self, tmp_store):
        result = handle_shadow_summary("/shadow/summary.json", {})
        assert json.loads(result)["overall"]["n"] == 0


class TestRouteRegistration:
    def test_all_get_routes_registered(self):
        expected_keys = [
            "/state.json",
            "/trades.json",
            "/equity_history.json",
            "/confidence.json",
            "/volatility.json",
            "/logs",
            "/risk.json",
            "/shadow-actions",
            "/health.json",
            "/governance.json",
            "/risk-parity.json",
            "/narrative.json",
            "/liquidity.json",
            "/psi.json",
            "/trade-outcomes.json",
            "/weekly-review.json",
            "/attribution/trades.json",
            "/attribution/summary.json",
            "/execution/quality.json",
            "/execution/slippage.json",
            "/shadow/trades.json",
            "/shadow/summary.json",
            "/archetype/stats.json",
            "/attribution/waterfall.json",
            "/analytics/snapshot.json",
            "/ping",
        ]
        for key in expected_keys:
            assert key in GET_ROUTES, f"Missing GET route: {key}"

    def test_prefix_routes_registered(self):
        prefixes = {p for p, _, _ in GET_ROUTES_PREFIX}
        assert "/risk/" in prefixes
        assert "/shadow-actions/" in prefixes
        assert "/health/" in prefixes

    def test_all_handlers_callable(self):
        for path, (fn, _) in GET_ROUTES.items():
            assert callable(fn), f"Handler for {path} is not callable"
