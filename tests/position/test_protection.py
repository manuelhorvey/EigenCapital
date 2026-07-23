"""Tests for paper_trading.position.protection — PositionProtection, ProtectionAction, check_profit_floor_exit."""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from eigencapital.domain.entities.position import ProfitLockState
from paper_trading.position.protection import (
    PositionProtection,
    ProtectionAction,
    check_profit_floor_exit,
)


@pytest.fixture
def pl_config():
    return {
        "breakeven_threshold_r": 0.5,
        "profit_lock_enabled": True,
        "profit_lock_trigger_r": 2.5,
        "profit_lock_floor_r": 2.0,
        "trail_activate_r": 1.0,
        "trail_distance_r": 0.5,
    }


class TestProtectionAction:
    def test_default_action_is_none(self):
        action = ProtectionAction()
        assert action.action == "none"
        assert action.new_sl is None

    def test_breakeven_action(self):
        action = ProtectionAction(action="breakeven", new_sl=1.05)
        assert action.action == "breakeven"
        assert action.new_sl == 1.05


class TestPositionProtection:
    @pytest.fixture
    def long_pos(self):
        pos = MagicMock()
        pos.is_long = True
        pos.avg_price = 1.0
        pos.peak_price = 0.0
        pos.risk_floor = 0.0
        pos.breakeven_set = False
        pos.profit_lock_state = None
        pos.vol = 0.01
        return pos

    @pytest.fixture
    def short_pos(self):
        pos = MagicMock()
        pos.is_long = False
        pos.avg_price = 1.0
        pos.peak_price = 0.0
        pos.risk_floor = 0.0
        pos.breakeven_set = False
        pos.profit_lock_state = None
        pos.vol = 0.01
        return pos

    @pytest.fixture
    def config(self):
        return {"breakeven_threshold_r": 0.5, "trail_activate_r": 1.0, "trail_distance_r": 0.5}

    def test_returns_none_action_when_position_is_none(self, config):
        action = PositionProtection.update(None, 1.0, config)
        assert action.action == "none"

    def test_returns_none_action_when_price_is_none(self, long_pos, config):
        action = PositionProtection.update(long_pos, None, config)
        assert action.action == "none"

    def test_returns_none_action_when_price_is_zero(self, long_pos, config):
        action = PositionProtection.update(long_pos, 0.0, config)
        assert action.action == "none"

    def test_peak_price_updates_for_long(self, long_pos, config):
        PositionProtection.update(long_pos, 1.05, config)
        assert long_pos.peak_price == 1.05

        PositionProtection.update(long_pos, 1.03, config)
        assert long_pos.peak_price == 1.05

        PositionProtection.update(long_pos, 1.08, config)
        assert long_pos.peak_price == 1.08

    def test_peak_price_updates_for_short(self, short_pos, config):
        PositionProtection.update(short_pos, 0.97, config)
        assert short_pos.peak_price == 0.97

        PositionProtection.update(short_pos, 0.99, config)
        assert short_pos.peak_price == 0.97

        PositionProtection.update(short_pos, 0.94, config)
        assert short_pos.peak_price == 0.94

    def test_breakeven_activates_at_threshold_long(self, long_pos, config):
        # current_price=1.006 => unrealized_r = (1.006 - 1.0) / (1.0 * 0.01) = 0.6 >= 0.5
        action = PositionProtection.update(long_pos, 1.006, config)
        assert action.action == "breakeven"
        assert long_pos.breakeven_set
        assert long_pos.risk_floor == 1.0

    def test_breakeven_does_not_activate_below_threshold_long(self, long_pos, config):
        # unrealized_r = (1.003 - 1.0) / 0.01 = 0.3 < 0.5
        action = PositionProtection.update(long_pos, 1.003, config)
        assert action.action != "breakeven"
        assert not long_pos.breakeven_set

    def test_short_breakeven_risk_floor_sentinel_first_time(self, short_pos, config):
        # unrealized_r = (1.0 - 0.994) / 0.01 = 0.6 >= 0.5
        action = PositionProtection.update(short_pos, 0.994, config)
        assert action.action == "breakeven"
        assert short_pos.breakeven_set
        assert short_pos.risk_floor == 1.0  # avg_price, because sentinel was 0

    def test_trail_from_avg_price_not_current_price(self, long_pos, config):
        long_pos.avg_price = 1.0
        long_pos.peak_price = 1.02  # peak established
        long_pos.vol = 0.01
        long_pos.breakeven_set = True
        long_pos.risk_floor = 1.0
        # current_price=1.02, unrealized_r=2.0 >= trail_activate=1.0
        # trail_price = 0.5 * 1.0 * 0.01 = 0.005 (uses avg_price, NOT current_price)
        action = PositionProtection.update(long_pos, 1.02, config)
        assert action.action == "trail"
        # expected: new_floor = 1.02 - 0.005 = 1.015
        assert action.new_sl == pytest.approx(1.015)
        assert long_pos.risk_floor == pytest.approx(1.015)

    def test_trail_uses_avg_price_not_current_price_short(self, short_pos, config):
        short_pos.avg_price = 1.0
        short_pos.peak_price = 0.98  # peak (lowest) established
        short_pos.vol = 0.01
        short_pos.breakeven_set = True
        short_pos.risk_floor = 1.0
        # current_price=0.98, unrealized_r=2.0 >= trail_activate=1.0
        action = PositionProtection.update(short_pos, 0.98, config)
        assert action.action == "trail"
        # trail_price = 0.5 * 1.0 * 0.01 = 0.005
        # new_floor = 0.98 + 0.005 = 0.985
        assert action.new_sl == pytest.approx(0.985)
        assert short_pos.risk_floor == pytest.approx(0.985)


class TestProfitFloorLifecycle:
    """Tests for the profit floor lifecycle state machine.

    State machine: ACTIVE → PROFIT_LOCKED → LOCK_EXIT
    - Trigger: highest_r_seen >= trigger_r (default 2.5)
    - Floor: risk_floor set at floor_r (default 2.0)
    - Exit: price crosses effective_sl after trigger
    """

    @pytest.fixture
    def long_pos(self):
        pos = MagicMock()
        pos.is_long = True
        pos.avg_price = 1.0
        pos.peak_price = 0.0
        pos.risk_floor = 0.0
        pos.breakeven_set = False
        pos.profit_lock_state = None
        pos.vol = 0.01
        pos.effective_sl = None
        return pos

    def test_initial_state_is_none(self, long_pos, pl_config):
        """Before any update, profit_lock_state should be None."""
        assert long_pos.profit_lock_state is None

    def test_state_initialized_on_first_update(self, long_pos, pl_config):
        """ProfitLockState is lazily initialized on first update with enabled config."""
        PositionProtection.update(long_pos, 1.01, pl_config)
        assert long_pos.profit_lock_state is not None
        assert long_pos.profit_lock_state.enabled is True
        assert long_pos.profit_lock_state.triggered is False
        assert long_pos.profit_lock_state.highest_r_seen == pytest.approx(1.0)  # (1.01-1.0)/0.01

    def test_trigger_not_fired_below_threshold(self, long_pos, pl_config):
        """Profit lock should not trigger below trigger_r."""
        # unrealized_r = (1.02 - 1.0) / 0.01 = 2.0 < 2.5
        PositionProtection.update(long_pos, 1.02, pl_config)
        assert long_pos.profit_lock_state.triggered is False
        # risk_floor > 0 due to breakeven + trailing at 2.0R, NOT profit lock
        assert long_pos.profit_lock_state is not None

    def test_trigger_fires_at_threshold_long(self, long_pos, pl_config):
        """Profit lock triggers when unrealized_r >= trigger_r."""
        # unrealized_r = (1.0251 - 1.0) / 0.01 = 2.51 >= 2.5
        PositionProtection.update(long_pos, 1.0251, pl_config)
        assert long_pos.profit_lock_state.triggered is True
        assert long_pos.profit_lock_state.trigger_r == 2.5
        assert long_pos.profit_lock_state.trigger_price is not None
        assert long_pos.profit_lock_state.highest_r_seen >= 2.5
        # floor = 1.0 + 2.0 * 1.0 * 0.01 = 1.02
        assert long_pos.risk_floor == pytest.approx(1.02, abs=0.005)

    def test_highest_r_seen_persistent_across_dips(self, long_pos, pl_config):
        """highest_r_seen should persist even when price dips."""
        # Peak at 1.025 (2.5R)
        PositionProtection.update(long_pos, 1.025, pl_config)
        assert long_pos.profit_lock_state.highest_r_seen == pytest.approx(2.5)
        # Dip to 1.01 (1.0R) — highest_r_seen should still be 2.5
        PositionProtection.update(long_pos, 1.01, pl_config)
        assert long_pos.profit_lock_state.highest_r_seen == pytest.approx(2.5)

    def test_floor_persists_after_trigger(self, long_pos, pl_config):
        """Once triggered, risk_floor should stay even if price recovers."""
        PositionProtection.update(long_pos, 1.0251, pl_config)
        assert long_pos.risk_floor >= 1.0
        pl_floor = long_pos.risk_floor
        # Recover to 1.03 (3.0R) — trailing may tighten further, but floor never drops below pl_floor
        PositionProtection.update(long_pos, 1.03, pl_config)
        assert long_pos.risk_floor >= pl_floor

    def test_check_profit_floor_exit_before_trigger(self, long_pos, pl_config):
        """check_profit_floor_exit should return False before trigger."""
        PositionProtection.update(long_pos, 1.01, pl_config)
        should_exit, exit_price, exit_reason = check_profit_floor_exit(long_pos, 1.01)
        assert should_exit is False
        assert exit_price is None

    def test_check_profit_floor_exit_after_trigger_no_cross(self, long_pos, pl_config):
        """After trigger but price above floor, should not exit."""
        PositionProtection.update(long_pos, 1.025, pl_config)
        long_pos.effective_sl = 1.02  # should be set by trigger but mock needs explicit
        should_exit, exit_price, exit_reason = check_profit_floor_exit(long_pos, 1.021)
        assert should_exit is False

    def test_check_profit_floor_exit_on_cross(self, long_pos, pl_config):
        """After trigger, when price crosses floor, should exit with PROFIT_LOCK reason."""
        PositionProtection.update(long_pos, 1.0251, pl_config)
        long_pos.effective_sl = long_pos.risk_floor
        should_exit, exit_price, exit_reason = check_profit_floor_exit(long_pos, 1.01)
        assert should_exit is True
        assert exit_price is not None
        assert exit_reason == "PROFIT_LOCK"

    def test_check_profit_floor_exit_returns_none_when_no_state(self, long_pos):
        """Without profit lock config, state stays None and exit check returns False."""
        cfg = {"breakeven_threshold_r": 0.5, "trail_activate_r": 1.0, "trail_distance_r": 0.5}
        PositionProtection.update(long_pos, 1.025, cfg)
        should_exit, exit_price, exit_reason = check_profit_floor_exit(long_pos, 1.01)
        assert should_exit is False
        assert exit_price is None

    def test_floor_tighter_than_breakeven(self, long_pos, pl_config):
        """Profit floor (2.0R) should be tighter than breakeven (0.5R)."""
        # Breakeven activates at 0.5R → risk_floor = 1.0
        PositionProtection.update(long_pos, 1.006, pl_config)
        assert long_pos.breakeven_set
        assert long_pos.risk_floor == 1.0

        # Profit floor triggers at 2.5R → risk_floor > 1.0
        PositionProtection.update(long_pos, 1.0251, pl_config)
        assert long_pos.profit_lock_state.triggered
        assert long_pos.risk_floor > 1.0

    def test_short_trigger_and_floor(self, pl_config):
        """Profit floor should work for short positions (floor below entry)."""
        pos = MagicMock()
        pos.is_long = False
        pos.avg_price = 1.0
        pos.peak_price = 0.0
        pos.risk_floor = 0.0
        pos.breakeven_set = False
        pos.profit_lock_state = None
        pos.vol = 0.01
        pos.effective_sl = None

        # Push to 0.975 (2.5R)
        PositionProtection.update(pos, 0.975, pl_config)
        assert pos.profit_lock_state.triggered
        # floor = 1.0 - 2.0 * 1.0 * 0.01 = 0.98
        assert pos.risk_floor == pytest.approx(0.98)

        pos.effective_sl = pos.risk_floor
        # Price rises above floor → should exit
        should_exit, exit_price, exit_reason = check_profit_floor_exit(pos, 0.99)
        assert should_exit is True
        assert exit_reason == "PROFIT_LOCK"

    def test_disabled_via_config(self, long_pos):
        """When profit_lock_enabled is False or absent, no state is initialized."""
        cfg = {"breakeven_threshold_r": 0.5, "trail_activate_r": 1.0, "trail_distance_r": 0.5}
        PositionProtection.update(long_pos, 1.025, cfg)
        assert long_pos.profit_lock_state is None

    def test_disabled_explicitly(self, long_pos):
        """When profit_lock_enabled is False, no state is initialized."""
        cfg = {"breakeven_threshold_r": 0.5, "profit_lock_enabled": False}
        PositionProtection.update(long_pos, 1.025, cfg)
        assert long_pos.profit_lock_state is None

    def test_tail_preserved_in_highest_r_seen(self, long_pos, pl_config):
        """highest_r_seen should capture the true peak, enabling attribution."""
        values = [1.01, 1.02, 1.03, 1.04, 1.02, 1.01]
        for v in values:
            PositionProtection.update(long_pos, v, pl_config)
        assert long_pos.profit_lock_state.highest_r_seen == pytest.approx(4.0)  # (1.04-1.0)/0.01
