"""Tests for paper_trading.position.protection — PositionProtection, ProtectionAction."""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from paper_trading.position.protection import PositionProtection, ProtectionAction


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
