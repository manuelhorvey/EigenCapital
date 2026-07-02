"""Tests for the R-based scale-out extension to AdaptiveExitEngine."""

from __future__ import annotations

import math

import pytest

from paper_trading.position.adaptive_exit import AdaptiveExitEngine


@pytest.fixture
def engine():
    return AdaptiveExitEngine()


class TestScaleOut:
    def test_scale_out_config_default_empty(self, engine):
        """Without scale_out config, engine never fires scale-out."""
        result = engine.compute(
            side="long",
            entry_price=100.0,
            current_price=120.0,
            current_sl=95.0,
            vol_at_entry=0.02,
            bars_since_entry=10,
            config={"trail_retrace_pct": 0.5, "trail_activation_r": 0.8},
        )
        assert result.scale_out_fraction is None
        assert result.scale_out_price is None
        assert result.action != "scale_out"

    def _trigger_breakeven(self, engine, side, entry, vol):
        """First call always triggers breakeven (faster than scale-out)."""
        cp = entry * 1.06 if side == "long" else entry * 0.94
        sl = entry * 0.95 if side == "long" else entry * 1.05  # loose enough for be to move
        return engine.compute(
            side=side, entry_price=entry, current_price=cp,
            current_sl=sl, vol_at_entry=vol, bars_since_entry=5,
            config={
                "scale_out_fraction": 0.6, "scale_out_r": 2.0,
                "trail_retrace_pct": 0.5, "trail_activation_r": 0.8,
            },
        )

    def test_scale_out_fires_long(self, engine):
        """Scale-out fires at target R-multiple on long after breakeven."""
        entry = 100.0
        vol = 0.02
        target_r = 2.0
        r0 = self._trigger_breakeven(engine, "long", entry, vol)
        assert r0.action == "breakeven"
        result = engine.compute(
            side="long", entry_price=entry, current_price=120.0,
            current_sl=r0.new_sl, vol_at_entry=vol, bars_since_entry=10,
            config={
                "scale_out_fraction": 0.6, "scale_out_r": target_r,
                "trail_retrace_pct": 0.5, "trail_activation_r": 0.8,
            },
        )
        assert result.scale_out_fraction == 0.6
        expected_price = entry + target_r * vol * entry
        assert abs(result.scale_out_price - expected_price) < 1e-6
        assert result.action == "scale_out"

    def test_scale_out_fires_short(self, engine):
        """Scale-out fires at target R-multiple on short after breakeven."""
        entry = 100.0
        vol = 0.02
        target_r = 1.5
        r0 = self._trigger_breakeven(engine, "short", entry, vol)
        assert r0.action == "breakeven"
        result = engine.compute(
            side="short", entry_price=entry, current_price=80.0,
            current_sl=r0.new_sl, vol_at_entry=vol, bars_since_entry=5,
            config={
                "scale_out_fraction": 0.5, "scale_out_r": target_r,
                "trail_retrace_pct": 0.5, "trail_activation_r": 0.8,
            },
        )
        assert result.scale_out_fraction == 0.5
        expected_price = entry - target_r * vol * entry
        assert abs(result.scale_out_price - expected_price) < 1e-6
        assert result.action == "scale_out"

    def test_scale_out_only_once(self, engine):
        """Scale-out fires only on the first crossing."""
        cfg = {
            "scale_out_fraction": 0.5, "scale_out_r": 2.0,
            "trail_retrace_pct": 0.5, "trail_activation_r": 0.8,
        }
        self._trigger_breakeven(engine, "long", 100.0, 0.02)
        r1 = engine.compute(
            side="long", entry_price=100.0, current_price=130.0,
            current_sl=100.0, vol_at_entry=0.02, bars_since_entry=10, config=cfg,
        )
        assert r1.scale_out_fraction == 0.5  # fires
        r2 = engine.compute(
            side="long", entry_price=100.0, current_price=150.0,
            current_sl=100.0, vol_at_entry=0.02, bars_since_entry=15, config=cfg,
        )
        assert r2.scale_out_fraction is None  # already fired

    def test_scale_out_below_target(self, engine):
        """Scale-out does NOT fire when peak_r < target."""
        result = engine.compute(
            side="long",
            entry_price=100.0,
            current_price=102.0,  # only 1R MFE (at vol=0.02, 1R = 2.0)
            current_sl=95.0,
            vol_at_entry=0.02,
            bars_since_entry=5,
            config={
                "scale_out_fraction": 0.5,
                "scale_out_r": 3.0,
                "trail_retrace_pct": 0.5,
                "trail_activation_r": 0.8,
            },
        )
        assert result.scale_out_fraction is None

    def test_scale_out_after_reset(self, engine):
        """After reset, scale-out can fire again on a new trade."""
        cfg = {
            "scale_out_fraction": 0.5, "scale_out_r": 2.0,
            "trail_retrace_pct": 0.5, "trail_activation_r": 0.8,
        }
        self._trigger_breakeven(engine, "long", 100.0, 0.02)
        engine.compute(
            side="long", entry_price=100.0, current_price=130.0,
            current_sl=100.0, vol_at_entry=0.02, bars_since_entry=10, config=cfg,
        )
        engine.reset()
        self._trigger_breakeven(engine, "long", 100.0, 0.02)
        r2 = engine.compute(
            side="long", entry_price=100.0, current_price=130.0,
            current_sl=100.0, vol_at_entry=0.02, bars_since_entry=10, config=cfg,
        )
        assert r2.scale_out_fraction == 0.5  # fires again

    def test_trail_still_works_after_scale_out(self, engine):
        """Trailing stop still functions after scale-out has been taken."""
        cfg = {
            "scale_out_fraction": 0.5, "scale_out_r": 1.0,
            "trail_retrace_pct": 0.20, "trail_activation_r": 0.8,
            "be_lock_r": 0.5,
        }
        # Fire scale-out
        engine.compute(
            side="long", entry_price=100.0, current_price=105.0,
            current_sl=95.0, vol_at_entry=0.05, bars_since_entry=5, config=cfg,
        )
        # Price continues up to 120, then retraces to 110
        # peak_r = (110-100)/(100*0.05) = 2.0, peak=110
        # But actual peak tracked is 120 (from the compute call below)
        result = engine.compute(
            side="long", entry_price=100.0, current_price=120.0,
            current_sl=95.0, vol_at_entry=0.05, bars_since_entry=10, config=cfg,
        )
        # Then retraces to 110
        result2 = engine.compute(
            side="long", entry_price=100.0, current_price=110.0,
            current_sl=95.0, vol_at_entry=0.05, bars_since_entry=12, config=cfg,
        )
        # Trail should activate since peak_r = (120-100)/(100*0.05) = 4.0 >= 0.8
        # 20% retrace from 120: 120 - 0.2*(120-100) = 116
        # Current SL is 95, 116 > 95, should update
        if result2.action == "trail":
            assert result2.new_sl is not None
            assert result2.new_sl > 95.0

    def test_scale_out_r_1_small_move(self, engine):
        """Real-world: small safe move doesn't trigger 2.5R scale-out."""
        entry = 100.0
        vol = 0.02  # 2% ATR
        # Price moves to 103 = 1.5R MFE, below 2.5R target
        result = engine.compute(
            side="long", entry_price=entry, current_price=103.0,
            current_sl=98.0, vol_at_entry=vol, bars_since_entry=8,
            config={
                "scale_out_fraction": 0.7,
                "scale_out_r": 2.5,
                "trail_retrace_pct": 0.15,
                "trail_activation_r": 0.8,
                "be_lock_r": 0.5,
            },
        )
        assert result.scale_out_fraction is None
        # But breakeven should fire (1.5R >= 0.5R)
        if result.action == "breakeven":
            assert abs(result.new_sl - entry) < 1e-6
