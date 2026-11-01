"""F-14 — Dashboard truth regression tests.

Covers:
- MT5 call ordering: positions fetched before shutdown so unrealized_pnl is real
- daily_loss_remaining decrements from baseline (never resets to full limit)
- Health staleness TTL: stale "alive" flag → HALTED, not HEALTHY
- Missing reconciliation engine record → UNKNOWN (not CLEAN from SL presence)
- Unavailable MT5 → empty account state with UNKNOWN freshness
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path
from unittest.mock import MagicMock, PropertyMock, patch

import pytest

from eigencapital.dashboard.services.dashboard_state import (
    DashboardStateService,
    HEALTH_STALENESS_TTL_SECONDS,
    _compute_daily_loss_remaining,
)
from eigencapital.dashboard.schemas.common import DataFreshness


# ════════════════════════════════════════════════════════════════════
# daily_loss_remaining derivation
# ════════════════════════════════════════════════════════════════════


def test_compute_daily_loss_remaining_decrements_from_limit():
    remaining = _compute_daily_loss_remaining(50.0, 250.0)
    assert remaining == 200.0


def test_compute_daily_loss_remaining_cannot_be_negative():
    remaining = _compute_daily_loss_remaining(300.0, 250.0)
    assert remaining == 0.0


def test_compute_daily_loss_remaining_zero_when_no_pnl():
    remaining = _compute_daily_loss_remaining(0.0, 250.0)
    assert remaining == 250.0


# ════════════════════════════════════════════════════════════════════
# Health staleness TTL
# ════════════════════════════════════════════════════════════════════


def _fresh_health(tmp_path: Path) -> Path:
    p = tmp_path / "reports" / "r4_loop" / "loop_health.json"
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(
        '{"alive": true, "pid": 1, "timestamp": "%s", "instance_id": "inst-1"}'
        % datetime.now(UTC).isoformat()
    )
    return p


def _stale_health(tmp_path: Path) -> Path:
    p = tmp_path / "reports" / "r4_loop" / "loop_health.json"
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(
        '{"alive": true, "pid": 1, "timestamp": "%s", "instance_id": "inst-1"}'
        % (datetime.now(UTC) - timedelta(seconds=HEALTH_STALENESS_TTL_SECONDS + 60)
        ).isoformat()
    )
    return p


def _old_last_health(tmp_path: Path) -> Path:
    p = tmp_path / "reports" / "r4_loop" / "last_health.json"
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(
        '{"alive": true, "pid": 1, "timestamp": "%s"}'
        % (datetime.now(UTC) - timedelta(days=2)).isoformat()
    )
    return p


def _make_service(tmp_path: Path) -> DashboardStateService:
    loop_dir = tmp_path / "reports" / "r4_loop"
    loop_dir.mkdir(parents=True, exist_ok=True)
    service = DashboardStateService()
    service._data_dir = tmp_path / "reports"
    service._loop_dir = loop_dir
    service.get_positions = lambda: []  # type: ignore[method-assign]
    return service


def test_health_stale_alive_flag_is_not_trusted(tmp_path: Path):
    """Stale last_health.json with alive=true must not report HEALTHY (F-14)."""
    _old_last_health(tmp_path)
    service = _make_service(tmp_path)
    health = service.get_system_health()

    assert health["overall_state"] == "HALTED"
    supervisor_dim = next(d for d in health["dimensions"] if d["dimension"] == "supervisor")
    assert supervisor_dim["state"] == "HALTED"
    assert supervisor_dim["details"].get("health_stale") is True


def test_health_fresh_alive_flag_is_trusted(tmp_path: Path):
    """Fresh loop_health.json with alive=true reports HEALTHY."""
    _fresh_health(tmp_path)
    service = _make_service(tmp_path)
    health = service.get_system_health()

    supervisor_dim = next(d for d in health["dimensions"] if d["dimension"] == "supervisor")
    assert supervisor_dim["state"] == "HEALTHY"
    assert supervisor_dim["details"].get("health_stale") is False


def test_health_missing_file_is_halted(tmp_path: Path):
    """No health file at all → HALTED, not HEALTHY."""
    service = _make_service(tmp_path)
    health = service.get_system_health()

    supervisor_dim = next(d for d in health["dimensions"] if d["dimension"] == "supervisor")
    assert supervisor_dim["state"] == "HALTED"
    assert health["overall_state"] == "HALTED"


def test_health_within_ttl_is_not_stale(tmp_path: Path):
    """Data within TTL (just under the boundary) is still considered fresh."""
    p = tmp_path / "reports" / "r4_loop" / "loop_health.json"
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(
        '{"alive": true, "pid": 1, "timestamp": "%s", "instance_id": "inst-1"}'
        % (datetime.now(UTC) - timedelta(seconds=HEALTH_STALENESS_TTL_SECONDS - 1)
        ).isoformat()
    )
    service = _make_service(tmp_path)
    health = service.get_system_health()

    supervisor_dim = next(d for d in health["dimensions"] if d["dimension"] == "supervisor")
    assert supervisor_dim["state"] == "HEALTHY"
    assert supervisor_dim["details"].get("health_stale") is False


# ════════════════════════════════════════════════════════════════════
# Reconciliation missing engine record → UNKNOWN
# ════════════════════════════════════════════════════════════════════


def test_reconciliation_missing_engine_record_is_unknown(tmp_path: Path):
    """No reconciliation_state.json → UNKNOWN, never CLEAN from SL presence (F-14)."""
    loop_dir = tmp_path / "reports" / "r4_loop"
    loop_dir.mkdir(parents=True)
    service = DashboardStateService()
    service._data_dir = tmp_path / "reports"
    service._loop_dir = loop_dir
    service.get_positions = lambda: []  # type: ignore[method-assign]

    status = service.get_reconciliation_status()

    assert status["overall_status"] == "UNKNOWN"
    assert status.get("engine_record") is False
    assert status["freshness"] == DataFreshness.UNKNOWN.value
    assert not (loop_dir / "reconciliation_state.json").exists()


# ════════════════════════════════════════════════════════════════════
# MT5 unavailable → empty account state with UNKNOWN freshness
# ════════════════════════════════════════════════════════════════════


class _FakePosition:
    def __init__(self, profit: float | None):
        self.profit = profit


class _FakeMT5:
    def __init__(self, initialize_ok: bool = True, account=None, positions=None):
        self._initialize_ok = initialize_ok
        self._account = account
        self._positions = positions or []
        self.shut_down = False

    def initialize(self):
        return self._initialize_ok

    def account_info(self):
        return self._account

    def positions_get(self):
        return self._positions

    def shutdown(self):
        self.shut_down = True


def test_mt5_unavailable_returns_empty_unknown_state(tmp_path: Path):
    """MT5 initialize fails → empty account state, UNKNOWN freshness."""
    loop_dir = tmp_path / "reports" / "r4_loop"
    loop_dir.mkdir(parents=True)
    service = DashboardStateService()
    service._data_dir = tmp_path / "reports"
    service._loop_dir = loop_dir

    with patch(
        "mt5linux.MetaTrader5", _FakeMT5(initialize_ok=False)
    ):
        state = service.get_account_state()

    assert state["equity"] == 0
    assert state["freshness"] == DataFreshness.UNKNOWN.value
    assert state["source"] == "unavailable"


def test_positions_fetched_before_shutdown(tmp_path: Path):
    """positions_get is called before mt5.shutdown (F-14 ordering)."""
    loop_dir = tmp_path / "reports" / "r4_loop"
    loop_dir.mkdir(parents=True)
    service = DashboardStateService()
    service._data_dir = tmp_path / "reports"
    service._loop_dir = loop_dir

    fake_account = MagicMock()
    fake_account.equity = 1000.0
    fake_account.balance = 1000.0
    fake_account.margin_free = 900.0
    fake_account.margin = 100.0
    fake_account.currency = "USD"

    fake_positions = [_FakePosition(profit=12.50), _FakePosition(profit=-3.20)]
    fake_mt5 = _FakeMT5(
        initialize_ok=True, account=fake_account, positions=fake_positions
    )

    call_order = []

    real_init = fake_mt5.initialize
    real_account = fake_mt5.account_info
    real_positions = fake_mt5.positions_get
    real_shutdown = fake_mt5.shutdown

    def wrapped_init():
        call_order.append("initialize")
        return real_init()

    def wrapped_account():
        call_order.append("account_info")
        return real_account()

    def wrapped_positions():
        call_order.append("positions_get")
        return real_positions()

    def wrapped_shutdown():
        call_order.append("shutdown")
        return real_shutdown()

    fake_mt5.initialize = wrapped_init
    fake_mt5.account_info = wrapped_account
    fake_mt5.positions_get = wrapped_positions
    fake_mt5.shutdown = wrapped_shutdown

    with patch(
        "mt5linux.MetaTrader5", lambda *a, **k: fake_mt5
    ):
        state = service.get_account_state()

    assert call_order.index("positions_get") < call_order.index("shutdown"), call_order
    assert state["unrealized_pnl"] == pytest.approx(9.30)
    assert fake_mt5.shut_down is True


def test_daily_loss_remaining_decrements_in_account_state(tmp_path: Path):
    """daily_loss_remaining reflects daily_pnl against baseline (F-14)."""
    loop_dir = tmp_path / "reports" / "r4_loop"
    loop_dir.mkdir(parents=True)
    (loop_dir / "daily_baseline.json").write_text('{"equity": 1000.0}')

    service = DashboardStateService()
    service._data_dir = tmp_path / "reports"
    service._loop_dir = loop_dir

    fake_account = MagicMock()
    fake_account.equity = 850.0
    fake_account.balance = 850.0
    fake_account.margin_free = 800.0
    fake_account.margin = 50.0
    fake_account.currency = "USD"

    fake_mt5 = _FakeMT5(initialize_ok=True, account=fake_account, positions=[])

    with patch(
        "mt5linux.MetaTrader5", lambda *a, **k: fake_mt5
    ):
        state = service.get_account_state()

    # daily_pnl = 850 - 1000 = -150 → remaining = 250 - 150 = 100
    assert state["daily_pnl"] == pytest.approx(-150.0)
    assert state["daily_loss_remaining"] == pytest.approx(100.0)
