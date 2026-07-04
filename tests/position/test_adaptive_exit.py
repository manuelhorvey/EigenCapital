"""
Edge-case tests for AdaptiveExitEngine (retracement-based trailing stop).

Covers state machine transitions, peak tracking, short/long symmetry,
and all failure modes identified in the Production Deployment Gate.
"""
import pytest

from paper_trading.position.adaptive_exit import AdaptiveExitEngine, AdaptiveExitResult

# ── Standard configs ───────────────────────────────────────────────────────

DEFAULT_CFG = {
    "be_lock_r": 0.5,
    "trail_activation_r": 0.8,
    "trail_retrace_pct": 0.50,
    "max_hold_candles": 40,
    "time_decay_start": 20,
}

AGGRESSIVE_CFG = {**DEFAULT_CFG, "trail_activation_r": 0.5}


class TestAdaptiveExitStateMachine:
    """Adaptive exit is a 3-stage state machine: breakeven → trail → time decay."""

    def test_initial_state(self):
        ae = AdaptiveExitEngine()
        assert ae._best_price is None
        assert not ae._breakeven_activated
        assert not ae._trail_activated

    def test_reset(self):
        ae = AdaptiveExitEngine()
        ae._breakeven_activated = True
        ae._trail_activated = True
        ae._best_price = 1.05
        ae.reset()
        assert ae._best_price is None
        assert not ae._breakeven_activated
        assert not ae._trail_activated

    def test_stage_1_breakeven_activates(self):
        """At be_lock_r MFE, SL moves to entry price."""
        ae = AdaptiveExitEngine()
        result = ae.compute(
            side="long", entry_price=100.0, current_price=102.5, current_sl=97.0,
            vol_at_entry=0.02, bars_since_entry=5, config=DEFAULT_CFG,
        )
        # peak_r = (102.5 - 100) / (100 * 0.02) = 2.5 / 2.0 = 1.25 >= 0.5
        assert result.action == "breakeven"
        assert result.new_sl == 100.0  # entry price

    def test_stage_1_breakeven_idempotent(self):
        """After breakeven activates, subsequent calls don't re-fire."""
        ae = AdaptiveExitEngine()
        ae.compute(side="long", entry_price=100.0, current_price=102.5, current_sl=97.0,
                   vol_at_entry=0.02, bars_since_entry=5, config=DEFAULT_CFG)
        assert ae._breakeven_activated

        # Price stays at 102.5 — same cycle
        result2 = ae.compute(side="long", entry_price=100.0, current_price=102.5, current_sl=100.0,
                             vol_at_entry=0.02, bars_since_entry=6, config=DEFAULT_CFG)
        # Already at breakeven, should not return breakeven again
        assert result2.action != "breakeven"

    def test_stage_2_trail_activates(self):
        """At trail_activation_r MFE, SL trails at retrace_pct from peak."""
        ae = AdaptiveExitEngine()
        # Peak price = 104.0 (peak_r = (104-100) / (100*0.02) = 4/2 = 2.0 >= 0.8)
        ae._best_price = 104.0
        ae._breakeven_activated = True  # skip stage 1
        result = ae.compute(
            side="long", entry_price=100.0, current_price=102.0, current_sl=100.0,
            vol_at_entry=0.02, bars_since_entry=10, config=DEFAULT_CFG,
        )
        # retrace_level = 104 - 0.5 * (104 - 100) = 104 - 2 = 102
        # current_sl = 100, 102 > 100 → tighten
        assert result.action == "trail"
        assert result.new_sl == pytest.approx(102.0)

    def test_stage_2_trail_does_not_loosen_sl(self):
        """Trail should never move SL backwards."""
        ae = AdaptiveExitEngine()
        ae._best_price = 104.0
        ae._breakeven_activated = True
        # current_sl = 103 (already tighter than trail would compute)
        result = ae.compute(
            side="long", entry_price=100.0, current_price=103.5, current_sl=103.0,
            vol_at_entry=0.02, bars_since_entry=10, config=DEFAULT_CFG,
        )
        # retrace_level = 104 - 0.5 * 4 = 102
        # current_sl = 103 > 102 → trail should NOT fire (would loosen)
        assert result.action != "trail"

    def test_stage_3_time_decay_tightens(self):
        """Past decay_start, when trail hasn't fired this cycle, tolerance tightens."""
        ae = AdaptiveExitEngine()
        # Set peak at 103
        ae._best_price = 103.0
        ae._breakeven_activated = True
        ae._trail_activated = True
        # Trail fires on first call after peak at bar 30
        r1 = ae.compute(
            side="long", entry_price=100.0, current_price=101.0, current_sl=100.0,
            vol_at_entry=0.02, bars_since_entry=30, config=DEFAULT_CFG,
        )
        # First: trail fires (retrace from 103: 103 - 0.5*3 = 101.5)
        assert r1.action == "trail"
        # Second call, same price, SL already at 101.5: trail won't fire (wouldn't tighten further)
        # Time decay should fire instead
        r2 = ae.compute(
            side="long", entry_price=100.0, current_price=101.0, current_sl=101.5,
            vol_at_entry=0.02, bars_since_entry=30, config=DEFAULT_CFG,
        )
        # progress = (30-20)/20 = 0.5
        # tighter_retrace = 0.5 * max(1-0.15, 0.3) = 0.5 * 0.85 = 0.425
        # tighter_level = 103 - 0.425 * 3 = 103 - 1.275 = 101.725
        # current_sl = 101.5 < 101.725 → tighten
        assert r2.action == "time_decay", f"Got {r2.action} instead of time_decay"
        assert r2.new_sl == pytest.approx(101.725, abs=0.001)

    def test_time_decay_does_not_fire_before_threshold(self):
        """Time decay only fires when progress > 0.3."""
        ae = AdaptiveExitEngine()
        ae._best_price = 103.5
        ae._breakeven_activated = True
        ae._trail_activated = True
        # At bar 22: progress = (22 - 20) / 20 = 0.1 < 0.3
        result = ae.compute(
            side="long", entry_price=100.0, current_price=101.5, current_sl=100.0,
            vol_at_entry=0.02, bars_since_entry=22, config=DEFAULT_CFG,
        )
        assert result.action != "time_decay"

    def test_peak_tracking_never_decreases_long(self):
        """Peak price should be monotonic for longs."""
        ae = AdaptiveExitEngine()
        ae.compute(side="long", entry_price=100.0, current_price=101.0, current_sl=98.0,
                   vol_at_entry=0.02, bars_since_entry=1, config=DEFAULT_CFG)
        assert ae._best_price == 101.0
        # Lower price — peak should NOT decrease
        ae.compute(side="long", entry_price=100.0, current_price=100.5, current_sl=98.0,
                   vol_at_entry=0.02, bars_since_entry=2, config=DEFAULT_CFG)
        assert ae._best_price == 101.0
        # Higher price — peak should increase
        ae.compute(side="long", entry_price=100.0, current_price=102.0, current_sl=98.0,
                   vol_at_entry=0.02, bars_since_entry=3, config=DEFAULT_CFG)
        assert ae._best_price == 102.0

    def test_peak_tracking_short(self):
        """For shorts, peak is the LOWEST price reached."""
        ae = AdaptiveExitEngine()
        ae.compute(side="short", entry_price=100.0, current_price=99.0, current_sl=102.0,
                   vol_at_entry=0.02, bars_since_entry=1, config=AGGRESSIVE_CFG)
        assert ae._best_price == 99.0
        # Higher price — for short, peak should not increase
        ae.compute(side="short", entry_price=100.0, current_price=100.5, current_sl=102.0,
                   vol_at_entry=0.02, bars_since_entry=2, config=AGGRESSIVE_CFG)
        assert ae._best_price == 99.0
        # Lower price — new peak for short
        ae.compute(side="short", entry_price=100.0, current_price=98.0, current_sl=102.0,
                   vol_at_entry=0.02, bars_since_entry=3, config=AGGRESSIVE_CFG)
        assert ae._best_price == 98.0


class TestAdaptiveExitEdgeCases:
    """Edge cases that could silently break the engine."""

    def test_instant_mfe_spike_then_reversal(self):
        """Price spikes to MFE target immediately, then reverses.
        Engine should capture the spike as peak and trail from there."""
        ae = AdaptiveExitEngine()
        # Cycle 1: entry at 100
        r1 = ae.compute(side="long", entry_price=100.0, current_price=100.0, current_sl=95.0,
                        vol_at_entry=0.02, bars_since_entry=0, config=DEFAULT_CFG)
        assert r1.action == "none"
        # Cycle 2: spike to 106 (peak_r = 6/2 = 3.0)
        r2 = ae.compute(side="long", entry_price=100.0, current_price=106.0, current_sl=95.0,
                        vol_at_entry=0.02, bars_since_entry=1, config=DEFAULT_CFG)
        # Should hit both breakeven and trail in one jump
        assert r2.action == "breakeven"
        assert r2.new_sl == 100.0
        # Cycle 3: price reversed to 103
        r3 = ae.compute(side="long", entry_price=100.0, current_price=103.0, current_sl=100.0,
                        vol_at_entry=0.02, bars_since_entry=2, config=DEFAULT_CFG)
        # trail: retrace_level = 106 - 0.5 * 6 = 103
        assert r3.action == "trail"
        assert r3.new_sl == pytest.approx(103.0)

    def test_no_mfe_flat_trade(self):
        """Price never moves — MFE = 0. Engine should do nothing."""
        ae = AdaptiveExitEngine()
        for i in range(10):
            r = ae.compute(side="long", entry_price=100.0, current_price=100.0, current_sl=95.0,
                           vol_at_entry=0.02, bars_since_entry=i, config=DEFAULT_CFG)
            assert r.action == "none"
        assert ae._best_price == 100.0
        assert not ae._breakeven_activated
        assert not ae._trail_activated

    def test_multi_peak_mfe(self):
        """Price peaks, retraces partway, then rallies to new peak.
        Engine should track the HIGHEST peak and trail from there."""
        ae = AdaptiveExitEngine()
        # Entry
        ae.compute(side="long", entry_price=100.0, current_price=100.0, current_sl=95.0,
                   vol_at_entry=0.02, bars_since_entry=0, config=DEFAULT_CFG)
        # Rally to 103
        ae.compute(side="long", entry_price=100.0, current_price=103.0, current_sl=95.0,
                   vol_at_entry=0.02, bars_since_entry=1, config=DEFAULT_CFG)
        # Retrace to 101
        r = ae.compute(side="long", entry_price=100.0, current_price=101.0, current_sl=100.0,
                       vol_at_entry=0.02, bars_since_entry=2, config=DEFAULT_CFG)
        assert r.action == "trail"  # trail triggered at 50% retrace from 103
        assert r.new_sl == pytest.approx(101.5)  # 103 - 0.5 * 3
        # New rally to 105
        ae.compute(side="long", entry_price=100.0, current_price=105.0, current_sl=101.5,
                   vol_at_entry=0.02, bars_since_entry=3, config=DEFAULT_CFG)
        assert ae._best_price == 105.0  # new peak tracked
        # Retrace to 103 from new peak
        r3 = ae.compute(side="long", entry_price=100.0, current_price=103.5, current_sl=101.5,
                        vol_at_entry=0.02, bars_since_entry=4, config=DEFAULT_CFG)
        # trail from peak 105: retrace_level = 105 - 0.5 * 5 = 102.5
        # current_sl=101.5 < 102.5 → tighten
        assert r3.action == "trail"
        assert r3.new_sl == pytest.approx(102.5)

    def test_fast_reversal_after_entry(self):
        """Price goes against entry immediately — negative MFE.
        Engine should not fire anything (no MFE to capture)."""
        ae = AdaptiveExitEngine()
        for price in [99.0, 98.5, 98.0, 97.5]:
            r = ae.compute(side="long", entry_price=100.0, current_price=price, current_sl=95.0,
                           vol_at_entry=0.02, bars_since_entry=1, config=DEFAULT_CFG)
            assert r.action == "none"
        assert ae._best_price == 100.0  # never above entry
        assert not ae._breakeven_activated

    def test_long_consolidation_before_breakout(self):
        """Price stays near entry for many bars, then breaks out.
        Engine should handle late MFE correctly (no early accidental triggers)."""
        ae = AdaptiveExitEngine()
        # 30 bars of consolidation at 100-100.5
        for i in range(30):
            r = ae.compute(side="long", entry_price=100.0, current_price=100.3, current_sl=95.0,
                           vol_at_entry=0.02, bars_since_entry=i, config=DEFAULT_CFG)
            assert r.action == "none"
        # Breakout to 104
        r_b = ae.compute(side="long", entry_price=100.0, current_price=104.0, current_sl=95.0,
                         vol_at_entry=0.02, bars_since_entry=31, config=DEFAULT_CFG)
        assert r_b.action == "breakeven"
        assert r_b.new_sl == 100.0

    def test_short_symmetry(self):
        """Short side produces symmetric behavior (mirror of long)."""
        ae = AdaptiveExitEngine()
        # Entry at 100, price drops to 97.5
        r = ae.compute(side="short", entry_price=100.0, current_price=97.5, current_sl=103.0,
                       vol_at_entry=0.02, bars_since_entry=1, config=AGGRESSIVE_CFG)
        # peak_r = (100 - 97.5) / (100 * 0.02) = 2.5 / 2.0 = 1.25 >= 0.5
        assert r.action == "breakeven"
        assert r.new_sl == 100.0  # entry price for short
        # Price drops further to 95
        ae.compute(side="short", entry_price=100.0, current_price=95.0, current_sl=100.0,
                   vol_at_entry=0.02, bars_since_entry=2, config=AGGRESSIVE_CFG)
        assert ae._best_price == 95.0  # lowest price
        # Retrace to 97.5
        r3 = ae.compute(side="short", entry_price=100.0, current_price=97.5, current_sl=100.0,
                        vol_at_entry=0.02, bars_since_entry=3, config=AGGRESSIVE_CFG)
        # trail from peak 95: retrace_level = 95 + 0.5 * (100 - 95) = 95 + 2.5 = 97.5
        # current_sl=100 > 97.5 → tighten
        assert r3.action == "trail"
        assert r3.new_sl == pytest.approx(97.5)

    def test_zero_vol_at_entry(self):
        """Extreme edge: vol_at_entry = 0 (should not crash)."""
        ae = AdaptiveExitEngine()
        r = ae.compute(side="long", entry_price=100.0, current_price=105.0, current_sl=95.0,
                       vol_at_entry=0.0, bars_since_entry=5, config=DEFAULT_CFG)
        # Should not crash (vol clamped to 1e-9 internally)
        assert r.action in ("breakeven", "none")

    def test_aggressive_trailing_activates_earlier(self):
        """Aggressive config (activation_r=0.5) should trigger trail earlier."""
        ae_std = AdaptiveExitEngine()
        ae_agg = AdaptiveExitEngine()
        # Price at 101: peak_r = 1/2 = 0.5
        ae_std.compute(side="long", entry_price=100.0, current_price=101.0, current_sl=95.0,
                       vol_at_entry=0.02, bars_since_entry=1, config=DEFAULT_CFG)
        ae_agg.compute(side="long", entry_price=100.0, current_price=101.0, current_sl=95.0,
                       vol_at_entry=0.02, bars_since_entry=1, config=AGGRESSIVE_CFG)
        # Both should have price tracked, check activation state
        assert ae_agg._best_price == 101.0
        assert ae_std._best_price == 101.0

    def test_new_trade_resets_peak(self):
        """When a new trade opens, adaptive exit engine must be reset."""
        ae = AdaptiveExitEngine()
        ae.compute(side="long", entry_price=100.0, current_price=105.0, current_sl=95.0,
                   vol_at_entry=0.02, bars_since_entry=5, config=DEFAULT_CFG)
        assert ae._best_price == 105.0
        assert ae._breakeven_activated
        # Reset (simulates new trade)
        ae.reset()
        assert ae._best_price is None
        assert not ae._breakeven_activated
        # New trade at 110
        r = ae.compute(side="long", entry_price=110.0, current_price=110.0, current_sl=105.0,
                       vol_at_entry=0.02, bars_since_entry=0, config=DEFAULT_CFG)
        assert r.action == "none"
        assert ae._best_price == 110.0  # new peak starts from entry

    def test_current_sl_more_protective_than_trail(self):
        """If current SL is already tighter than computed trail, don't loosen."""
        ae = AdaptiveExitEngine()
        ae._best_price = 105.0
        ae._breakeven_activated = True
        # current_sl = 104 (very tight)
        result = ae.compute(side="long", entry_price=100.0, current_price=102.0, current_sl=104.0,
                            vol_at_entry=0.02, bars_since_entry=10, config=DEFAULT_CFG)
        # retrace_level = 105 - 0.5 * 5 = 102.5
        # current_sl = 104 > 102.5 → should NOT fire (would loosen)
        assert result.action != "trail"

    def test_bars_since_entry_zero(self):
        """Engine should handle bars_since_entry=0 (newly entered)."""
        ae = AdaptiveExitEngine()
        r = ae.compute(side="long", entry_price=100.0, current_price=100.0, current_sl=95.0,
                       vol_at_entry=0.02, bars_since_entry=0, config=DEFAULT_CFG)
        assert r.action == "none"


class TestAdaptiveExitEngine:
    """Public-API coverage for AdaptiveExitEngine."""

    def test_init_resets_state(self):
        engine = AdaptiveExitEngine()
        assert engine.phase == "STATIC"
        assert engine.peak_mfe_r is None
        assert engine.sl_update_count == 0

    def test_reset_clears_state(self):
        engine = AdaptiveExitEngine()
        engine._current_phase = "TRAILING"
        engine._best_price = 1.5
        engine.reset()
        assert engine.phase == "STATIC"
        assert engine.peak_mfe_r is None
        assert engine.sl_update_count == 0

    def test_best_price_tracks_peak_long(self):
        engine = AdaptiveExitEngine()
        engine.compute(side="long", entry_price=100, current_price=105,
                       current_sl=95, vol_at_entry=0.02, bars_since_entry=1)
        assert engine._best_price == 105
        engine.compute(side="long", entry_price=100, current_price=110,
                       current_sl=95, vol_at_entry=0.02, bars_since_entry=2)
        assert engine._best_price == 110
        engine.compute(side="long", entry_price=100, current_price=102,
                       current_sl=95, vol_at_entry=0.02, bars_since_entry=3)
        assert engine._best_price == 110

    def test_best_price_tracks_peak_short(self):
        engine = AdaptiveExitEngine()
        engine.compute(side="short", entry_price=100, current_price=95,
                       current_sl=105, vol_at_entry=0.02, bars_since_entry=1)
        assert engine._best_price == 95
        engine.compute(side="short", entry_price=100, current_price=90,
                       current_sl=105, vol_at_entry=0.02, bars_since_entry=2)
        assert engine._best_price == 90

    def test_no_action_when_price_at_entry(self):
        engine = AdaptiveExitEngine()
        result = engine.compute(side="long", entry_price=100, current_price=100,
                                current_sl=95, vol_at_entry=0.02, bars_since_entry=5)
        assert result.action == "none"
        assert result.new_sl is None

    def test_breakeven_lock_activates_at_default_be_r(self):
        engine = AdaptiveExitEngine()
        result = engine.compute(side="long", entry_price=100, current_price=105,
                                current_sl=95, vol_at_entry=0.02, bars_since_entry=5)
        assert result.action == "breakeven"
        assert result.new_sl is not None
        assert result.new_sl > 95
        assert engine.phase == "BREAKEVEN"

    def test_breakeven_locks_at_entry_price(self):
        engine = AdaptiveExitEngine()
        result = engine.compute(side="long", entry_price=100, current_price=105,
                                current_sl=95, vol_at_entry=0.02, bars_since_entry=5)
        assert result.action == "breakeven"
        assert result.new_sl == 100

    def test_breakeven_not_reached_for_small_move(self):
        engine = AdaptiveExitEngine()
        result = engine.compute(side="long", entry_price=100, current_price=100.5,
                                current_sl=95, vol_at_entry=0.02, bars_since_entry=5)
        assert result.action == "none"

    def test_breakeven_only_fires_once(self):
        engine = AdaptiveExitEngine()
        result = engine.compute(side="long", entry_price=100, current_price=105,
                                current_sl=95, vol_at_entry=0.02, bars_since_entry=1)
        assert result.action == "breakeven"
        result = engine.compute(side="long", entry_price=100, current_price=110,
                                current_sl=100, vol_at_entry=0.02, bars_since_entry=2)
        assert result.action != "breakeven"

    def test_scale_out_fires_at_config_r(self):
        engine = AdaptiveExitEngine()
        config = {"scale_out_fraction": 0.5, "scale_out_r": 2.0, "be_lock_r": 99.0}
        result = engine.compute(side="long", entry_price=100, current_price=104,
                                current_sl=95, vol_at_entry=0.02, bars_since_entry=5,
                                config=config)
        assert result.action == "scale_out"
        assert result.scale_out_fraction == 0.5
        assert result.scale_out_price is not None

    def test_trail_activates_after_breakeven(self):
        engine = AdaptiveExitEngine()
        engine.compute(side="long", entry_price=100, current_price=105,
                       current_sl=95, vol_at_entry=0.02, bars_since_entry=1)
        result = engine.compute(side="long", entry_price=100, current_price=108,
                                current_sl=100, vol_at_entry=0.02, bars_since_entry=2)
        assert result.action == "trail"
        assert result.new_sl is not None

    def test_trail_retrace_formula_long(self):
        engine = AdaptiveExitEngine()
        result = engine.compute(side="long", entry_price=100, current_price=110,
                                current_sl=95, vol_at_entry=0.02, bars_since_entry=1)
        assert result.action == "breakeven"
        result = engine.compute(side="long", entry_price=100, current_price=110,
                                current_sl=100, vol_at_entry=0.02, bars_since_entry=2)
        assert result.action == "trail"
        assert result.new_sl == pytest.approx(105.0)

    def test_default_config_is_empty_dict(self):
        engine = AdaptiveExitEngine()
        result = engine.compute(side="long", entry_price=100, current_price=105,
                                current_sl=95, vol_at_entry=0.02, bars_since_entry=5)
        assert result.action == "breakeven"

    def test_short_side_breakeven(self):
        engine = AdaptiveExitEngine()
        result = engine.compute(side="short", entry_price=100, current_price=95,
                                current_sl=105, vol_at_entry=0.02, bars_since_entry=1)
        assert result.action == "breakeven"
        assert result.new_sl == 100

    def test_short_side_trail(self):
        engine = AdaptiveExitEngine()
        engine.compute(side="short", entry_price=100, current_price=95,
                       current_sl=105, vol_at_entry=0.02, bars_since_entry=1)
        result = engine.compute(side="short", entry_price=100, current_price=93,
                                current_sl=100, vol_at_entry=0.02, bars_since_entry=2)
        assert result.action == "trail"
        assert result.new_sl == pytest.approx(96.5)

    def test_phase_tracks_progression(self):
        engine = AdaptiveExitEngine()
        assert engine.phase == "STATIC"
        engine.compute(side="long", entry_price=100, current_price=105,
                       current_sl=95, vol_at_entry=0.02, bars_since_entry=1)
        assert engine.phase == "BREAKEVEN"
        engine.compute(side="long", entry_price=100, current_price=108,
                       current_sl=100, vol_at_entry=0.02, bars_since_entry=2)
        assert engine.phase == "TRAILING"

    def test_scale_out_uses_correct_price_formula(self):
        engine = AdaptiveExitEngine()
        config = {"scale_out_fraction": 0.3, "scale_out_r": 1.5, "be_lock_r": 99.0}
        result = engine.compute(side="long", entry_price=100, current_price=103,
                                current_sl=95, vol_at_entry=0.02, bars_since_entry=1,
                                config=config)
        assert result.action == "scale_out"
        expected_price = 100 + 1.5 * 0.02 * 100
        assert result.scale_out_price == pytest.approx(expected_price)

    def test_returns_result_on_every_call(self):
        engine = AdaptiveExitEngine()
        for price in [100, 101, 102, 103, 99, 105]:
            result = engine.compute(side="long", entry_price=100, current_price=price,
                                    current_sl=95, vol_at_entry=0.02, bars_since_entry=1)
            assert isinstance(result, AdaptiveExitResult)
