"""Targeted tests for HaltState — coverage push from 48% to 70%+.

Covers the high-surface-area methods extracted from EngineOrchestrator:

    - restore_from_snapshot() + _reanchor_peak()
    - auto_clear_stale_halt()
    - check_auto_unhalt()
    - set_halt() / reset()
    - update_peak()
    - maybe_warn_persistent()
    - snapshot_dict()
"""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from paper_trading.orchestrator.halt_state import (
    DRAWDOWN_AUTO_UNHALT_MIN_CYCLES,
    DRAWDOWN_AUTO_UNHALT_THRESHOLD,
    HALT_REASON_AUTO_UNHALT_ALLOWED,
    HaltState,
)


def _make_snapshot(
    emergency_halt: bool = False,
    halt_reason: str = "",
    halt_detail: str = "",
    peak_portfolio_value: float | None = None,
    peak_capital_base: float | None = None,
    breaker_daily_pnl: list[float] | None = None,
):
    """Build a minimal EngineSnapshot-like object using __dict__ access.

    HaltState.restore_from_snapshot uses getattr() to read fields, so any
    object with the right attributes works — no need for the real dataclass.
    """
    snap = MagicMock()
    snap.emergency_halt = emergency_halt
    snap.halt_reason = halt_reason
    snap.halt_detail = halt_detail
    snap.peak_portfolio_value = peak_portfolio_value
    snap.peak_capital_base = peak_capital_base
    snap.breaker_daily_pnl = breaker_daily_pnl
    return snap


# ── Core lifecycle ───────────────────────────────────────────────────────────


class TestInit:
    def test_defaults(self):
        hs = HaltState()
        assert hs.emergency_halt is False
        assert hs.halt_reason is None
        assert hs.halt_detail == ""
        assert hs.peak_portfolio_value is None
        assert hs.unhalt_recovery_cycles == 0
        assert hs.halt_warn_last_cycle == -10


class TestSetHalt:
    def test_sets_halt_state(self):
        hs = HaltState()
        hs.set_halt("DRAWDOWN", "dd=-0.15")
        assert hs.emergency_halt is True
        assert hs.halt_reason == "DRAWDOWN"
        assert hs.halt_detail == "dd=-0.15"
        assert hs.unhalt_recovery_cycles == 0

    def test_multiple_set_halt_updates(self):
        hs = HaltState()
        hs.set_halt("DRAWDOWN", "first")
        hs.unhalt_recovery_cycles = 5  # simulate partial recovery
        hs.set_halt("HALT_RATIO", "second")
        assert hs.halt_reason == "HALT_RATIO"
        assert hs.halt_detail == "second"
        assert hs.unhalt_recovery_cycles == 0  # reset on each halt

    def test_set_halt_with_alternate_reason(self):
        hs = HaltState()
        hs.set_halt("VOL_SPIKE", "vol_spike_breach")
        assert hs.emergency_halt is True
        assert hs.halt_reason == "VOL_SPIKE"


class TestReset:
    def test_clears_halt(self):
        hs = HaltState()
        hs.set_halt("DRAWDOWN", "dd=-0.15")
        hs.reset()
        assert hs.emergency_halt is False
        assert hs.halt_reason is None
        assert hs.halt_detail == ""
        assert hs.unhalt_recovery_cycles == 0

    def test_reset_idempotent(self):
        hs = HaltState()
        hs.reset()  # was already clear
        assert hs.emergency_halt is False
        assert hs.halt_reason is None

    def test_reset_preserves_peak(self):
        hs = HaltState()
        hs.update_peak(100.0)
        hs.set_halt("DRAWDOWN", "test")
        hs.reset()
        assert hs.peak_portfolio_value == 100.0  # peak survives reset


class TestUpdatePeak:
    def test_sets_peak_when_none(self):
        hs = HaltState()
        hs.update_peak(100.0)
        assert hs.peak_portfolio_value == 100.0

    def test_keeps_higher_peak(self):
        hs = HaltState()
        hs.update_peak(100.0)
        hs.update_peak(80.0)  # lower value
        assert hs.peak_portfolio_value == 100.0

    def test_updates_to_new_high(self):
        hs = HaltState()
        hs.update_peak(100.0)
        hs.update_peak(120.0)
        assert hs.peak_portfolio_value == 120.0

    def test_negative_value_does_not_lower_peak(self):
        hs = HaltState()
        hs.update_peak(100.0)
        hs.update_peak(-50.0)
        assert hs.peak_portfolio_value == 100.0

    def test_zero_does_not_lower_peak(self):
        hs = HaltState()
        hs.update_peak(100.0)
        hs.update_peak(0.0)
        assert hs.peak_portfolio_value == 100.0

    def test_peak_from_none_with_zero(self):
        hs = HaltState()
        hs.update_peak(0.0)
        assert hs.peak_portfolio_value == 0.0


class TestSnapshotDict:
    def test_defaults(self):
        hs = HaltState()
        d = hs.snapshot_dict()
        assert d["emergency_halt"] is False
        assert d["halt_reason"] == ""
        assert d["halt_detail"] == ""
        assert d["peak_portfolio_value"] is None
        assert d["unhalt_recovery_cycles"] == 0

    def test_after_halt(self):
        hs = HaltState()
        hs.set_halt("DRAWDOWN", "test")
        hs.update_peak(150.0)
        d = hs.snapshot_dict()
        assert d["emergency_halt"] is True
        assert d["halt_reason"] == "DRAWDOWN"
        assert d["peak_portfolio_value"] == 150.0

    def test_peak_rounding(self):
        hs = HaltState()
        hs.update_peak(123.45678)
        d = hs.snapshot_dict()
        assert d["peak_portfolio_value"] == 123.46  # rounded to 2dp

    def test_drawdown_pct(self):
        """drawdown_pct property always returns 0.0 — no live equity access."""
        hs = HaltState()
        assert hs.drawdown_pct == 0.0


# ── restore_from_snapshot + _reanchor_peak ───────────────────────────────────


class TestRestoreFromSnapshot:
    def test_none_snapshot_sets_peak_to_equity(self):
        hs = HaltState()
        hs.restore_from_snapshot(None, init_equity=200.0, capital=100.0)
        assert hs.peak_portfolio_value == 200.0
        assert hs.emergency_halt is False

    def test_none_snapshot_none_equity(self):
        hs = HaltState()
        hs.restore_from_snapshot(None, init_equity=None, capital=100.0)
        assert hs.peak_portfolio_value is None

    def test_restores_halt_flags_when_snapshot_says_halted(self):
        hs = HaltState()
        snap = _make_snapshot(
            emergency_halt=True,
            halt_reason="DRAWDOWN",
            halt_detail="dd=-0.20",
            peak_portfolio_value=200.0,
        )
        hs.restore_from_snapshot(snap, init_equity=100.0, capital=100.0)
        assert hs.emergency_halt is True
        assert hs.halt_reason == "DRAWDOWN"
        assert hs.halt_detail == "dd=-0.20"

    def test_no_halt_flags_when_snapshot_not_halted(self):
        hs = HaltState()
        snap = _make_snapshot(emergency_halt=False, peak_portfolio_value=200.0)
        hs.restore_from_snapshot(snap, init_equity=100.0, capital=100.0)
        assert hs.emergency_halt is False
        assert hs.peak_portfolio_value is not None

    def test_peak_restored_and_safety_clamped(self):
        """Peak restored from snapshot; safety clamp ensures peak >= equity."""
        hs = HaltState()
        snap = _make_snapshot(peak_portfolio_value=150.0)
        hs.restore_from_snapshot(snap, init_equity=180.0, capital=100.0)
        # Safety clamp raises peak to 180 (equity > persisted peak)
        assert hs.peak_portfolio_value == 180.0

    def test_capital_ratio_adjustment(self):
        """When capital base changed, peak is adjusted proportionally."""
        hs = HaltState()
        snap = _make_snapshot(
            peak_portfolio_value=200.0,
            peak_capital_base=100.0,
        )
        # Small ratio increase (1.05×) so phantom dd clamp doesn't fire
        hs.restore_from_snapshot(
            snap, init_equity=190.0, capital=105.0,
        )
        # ratio = 105/100 = 1.05, peak = 200 * 1.05 = 210
        # phantom dd = (190-210)/210 = -9.5% > -15% → no clamp
        # safety: 190 < 210 → no clamp
        assert hs.peak_portfolio_value == pytest.approx(210.0)

    def test_capital_ratio_adjustment_with_negative_base(self):
        """Negative peak_capital_base skips capital ratio adjustment."""
        hs = HaltState()
        snap = _make_snapshot(
            peak_portfolio_value=200.0,
            peak_capital_base=-1.0,
        )
        # equity=180 → dd=(180-200)/200=-10% > -15% → no phantom clamp
        hs.restore_from_snapshot(snap, init_equity=180.0, capital=100.0)
        # capital ratio skipped (negative base); peak stays 200
        assert hs.peak_portfolio_value == 200.0

    def test_phantom_drawdown_clamp(self):
        """If restored peak produces >15% drawdown, clamp to equity."""
        hs = HaltState()
        snap = _make_snapshot(
            peak_portfolio_value=500.0,
            peak_capital_base=100.0,
        )
        hs.restore_from_snapshot(snap, init_equity=100.0, capital=100.0)
        # capital ratio: 100/100 = 1.0, peak stays 500
        # phantom dd = (100 - 500) / 500 = -80% → clamp to 100
        assert hs.peak_portfolio_value == 100.0

    def test_phantom_drawdown_clamp_without_init_equity(self):
        """When init_equity is None, phantom clamp is skipped."""
        hs = HaltState()
        snap = _make_snapshot(
            peak_portfolio_value=500.0,
            peak_capital_base=100.0,
        )
        hs.restore_from_snapshot(snap, init_equity=None, capital=100.0)
        # No safety clamp either (equity is None)
        # capital ratio: 100/100 = 1.0, peak = 500 * 1.0 = 500
        assert hs.peak_portfolio_value == 500.0

    def test_empty_halt_reason_from_snapshot(self):
        """When snapshot has halt_reason as empty string, don't set halt_reason."""
        hs = HaltState()
        snap = _make_snapshot(
            emergency_halt=True,
            halt_reason="",
            halt_detail="",
            peak_portfolio_value=100.0,
        )
        hs.restore_from_snapshot(snap, init_equity=100.0, capital=100.0)
        assert hs.emergency_halt is True
        # halt_reason remains None because empty string is falsy
        assert hs.halt_reason is None

    def test_reanchor_peak_with_capital_ratio_and_equity_safety(self):
        """Combined capital ratio + safety clamp in _reanchor_peak."""
        hs = HaltState()
        snap = _make_snapshot(
            peak_portfolio_value=100.0,
            peak_capital_base=100.0,
        )
        # capital stays same (ratio=1.0), equity=120 > peak=100 → clamp to 120
        hs.restore_from_snapshot(snap, init_equity=120.0, capital=100.0)
        assert hs.peak_portfolio_value == 120.0

    def test_restore_from_snapshot_passed_peak_capital_base(self):
        """peak_capital_base passed directly overrides snapshot's value."""
        hs = HaltState()
        snap = _make_snapshot(
            peak_portfolio_value=200.0,
            peak_capital_base=100.0,
        )
        # equity=190 → dd=(190-200)/200=-5% > -15% → no phantom clamp
        hs.restore_from_snapshot(
            snap, init_equity=190.0, capital=50.0, peak_capital_base=50.0,
        )
        # ratio = 50/50 = 1.0, peak stays 200
        # safety: 190 < 200 → no clamp
        assert hs.peak_portfolio_value == 200.0


# ── auto_clear_stale_halt ─────────────────────────────────────────────────────


class TestAutoClearStaleHalt:
    def test_not_halted_returns_false(self):
        hs = HaltState()
        assert hs.auto_clear_stale_halt(init_equity=100.0) is False

    def test_reason_not_in_allowed_set(self):
        hs = HaltState()
        hs.set_halt("HALT_RATIO", "halt_ratio_exceeded")
        assert hs.auto_clear_stale_halt(init_equity=100.0) is False

    def test_peak_is_none_returns_false(self):
        hs = HaltState()
        hs.set_halt("DRAWDOWN", "test")
        assert hs.auto_clear_stale_halt(init_equity=100.0) is False

    def test_peak_is_zero_returns_false(self):
        hs = HaltState()
        hs.set_halt("DRAWDOWN", "test")
        hs.update_peak(0.0)
        assert hs.auto_clear_stale_halt(init_equity=100.0) is False

    def test_equity_is_none_returns_false(self):
        hs = HaltState()
        hs.set_halt("DRAWDOWN", "test")
        hs.update_peak(100.0)
        assert hs.auto_clear_stale_halt(init_equity=None) is False

    def test_below_99pct_threshold_returns_false(self):
        hs = HaltState()
        hs.set_halt("DRAWDOWN", "test")
        hs.update_peak(100.0)
        # 98% ratio < 99% threshold
        assert hs.auto_clear_stale_halt(init_equity=98.0) is False
        assert hs.emergency_halt is True  # still halted

    def test_at_99pct_threshold_clears_halt(self):
        hs = HaltState()
        hs.set_halt("DRAWDOWN", "test")
        hs.update_peak(100.0)
        assert hs.auto_clear_stale_halt(init_equity=99.0) is True
        assert hs.emergency_halt is False
        assert hs.halt_reason is None
        assert hs.halt_detail == ""

    def test_above_99pct_threshold_clears_halt(self):
        hs = HaltState()
        hs.set_halt("DRAWDOWN", "test")
        hs.update_peak(100.0)
        assert hs.auto_clear_stale_halt(init_equity=105.0) is True
        assert hs.emergency_halt is False

    def test_consecutive_losses_allows_auto_clear(self):
        hs = HaltState()
        hs.set_halt("CONSECUTIVE_LOSSES", "7_consecutive")
        hs.update_peak(100.0)
        assert hs.auto_clear_stale_halt(init_equity=100.0) is True
        assert hs.emergency_halt is False

    def test_alert_callback_called_on_clear(self):
        hs = HaltState()
        hs.set_halt("DRAWDOWN", "test")
        hs.update_peak(100.0)
        callback = MagicMock()
        assert hs.auto_clear_stale_halt(init_equity=100.0, alert_callback=callback) is True
        callback.assert_called_once()
        args = callback.call_args[0]
        assert "auto-cleared" in args[0].lower()

    def test_alert_callback_exception_does_not_prevent_clear(self):
        hs = HaltState()
        hs.set_halt("DRAWDOWN", "test")
        hs.update_peak(100.0)

        def broken_callback(*_a, **_kw):
            raise TypeError("callback failed")

        assert hs.auto_clear_stale_halt(init_equity=100.0, alert_callback=broken_callback) is True
        assert hs.emergency_halt is False

    def test_vol_spike_reason_not_auto_cleared(self):
        hs = HaltState()
        hs.set_halt("VOL_SPIKE", "volatility_breach")
        hs.update_peak(100.0)
        assert hs.auto_clear_stale_halt(init_equity=100.0) is False


# ── check_auto_unhalt ──────────────────────────────────────────────────────────


class TestCheckAutoUnhalt:
    def test_not_halted_returns_false(self):
        hs = HaltState()
        assert hs.check_auto_unhalt(cycles_elapsed=10, total_equity=100.0) is False

    def test_reason_not_in_allowed_set(self):
        hs = HaltState()
        hs.set_halt("HALT_RATIO", "exceeded")
        assert hs.check_auto_unhalt(cycles_elapsed=10, total_equity=100.0) is False

    def test_cycles_elapsed_less_than_one(self):
        hs = HaltState()
        hs.set_halt("DRAWDOWN", "test")
        hs.update_peak(100.0)
        assert hs.check_auto_unhalt(cycles_elapsed=0, total_equity=100.0) is False

    def test_peak_is_none_returns_false(self):
        hs = HaltState()
        hs.set_halt("DRAWDOWN", "test")
        assert hs.check_auto_unhalt(cycles_elapsed=10, total_equity=100.0) is False

    def test_peak_is_zero_returns_false(self):
        hs = HaltState()
        hs.set_halt("DRAWDOWN", "test")
        hs.update_peak(0.0)
        assert hs.check_auto_unhalt(cycles_elapsed=10, total_equity=100.0) is False

    def test_equity_is_none_returns_false(self):
        hs = HaltState()
        hs.set_halt("DRAWDOWN", "test")
        hs.update_peak(100.0)
        assert hs.check_auto_unhalt(cycles_elapsed=10, total_equity=None) is False

    def test_below_threshold_resets_counter(self):
        hs = HaltState()
        hs.set_halt("DRAWDOWN", "test")
        hs.update_peak(100.0)
        hs.unhalt_recovery_cycles = 5  # partial progress
        # -10% < -5% threshold → resets counter
        result = hs.check_auto_unhalt(cycles_elapsed=10, total_equity=90.0)
        assert result is False
        assert hs.unhalt_recovery_cycles == 0

    def test_above_threshold_increments_counter(self):
        hs = HaltState()
        hs.set_halt("DRAWDOWN", "test")
        hs.update_peak(100.0)
        # equity=97, dd=-3% which is >= -5% threshold
        hs.check_auto_unhalt(cycles_elapsed=10, total_equity=97.0)
        assert hs.unhalt_recovery_cycles == 1

    def test_exactly_at_threshold_qualifies(self):
        hs = HaltState()
        hs.set_halt("DRAWDOWN", "test")
        hs.update_peak(100.0)
        # dd = (95 - 100) / 100 = -5% == threshold
        hs.check_auto_unhalt(cycles_elapsed=10, total_equity=95.0)
        assert hs.unhalt_recovery_cycles == 1

    def test_unhalt_after_consecutive_recovery_cycles(self):
        hs = HaltState()
        hs.set_halt("DRAWDOWN", "test")
        hs.update_peak(100.0)

        # Run enough cycles to trigger unhalt
        for _ in range(DRAWDOWN_AUTO_UNHALT_MIN_CYCLES):
            result = hs.check_auto_unhalt(cycles_elapsed=10, total_equity=97.0)

        assert result is True
        assert hs.emergency_halt is False
        assert hs.halt_reason is None
        assert hs.unhalt_recovery_cycles == 0  # reset after unhalt

    def test_unhalt_exactly_at_min_cycles(self):
        """unhalt occurs when recovery counter reaches exactly MIN_CYCLES."""
        hs = HaltState()
        hs.set_halt("DRAWDOWN", "test")
        hs.update_peak(100.0)

        # N-1 calls: still halted
        for _ in range(DRAWDOWN_AUTO_UNHALT_MIN_CYCLES - 1):
            assert hs.check_auto_unhalt(cycles_elapsed=10, total_equity=97.0) is False
        # Nth call: unhalt
        assert hs.check_auto_unhalt(cycles_elapsed=10, total_equity=97.0) is True

    def test_unhalt_with_consecutive_losses_reason(self):
        hs = HaltState()
        hs.set_halt("CONSECUTIVE_LOSSES", "7_consecutive")
        hs.update_peak(100.0)

        for _ in range(DRAWDOWN_AUTO_UNHALT_MIN_CYCLES):
            result = hs.check_auto_unhalt(cycles_elapsed=10, total_equity=97.0)
        assert result is True
        assert hs.emergency_halt is False

    def test_intermittent_drop_resets_counter(self):
        """A single bad cycle between good ones resets the counter."""
        hs = HaltState()
        hs.set_halt("DRAWDOWN", "test")
        hs.update_peak(100.0)

        # 2 good cycles
        hs.check_auto_unhalt(cycles_elapsed=10, total_equity=97.0)
        hs.check_auto_unhalt(cycles_elapsed=11, total_equity=97.0)
        assert hs.unhalt_recovery_cycles == 2

        # 1 bad cycle
        hs.check_auto_unhalt(cycles_elapsed=12, total_equity=85.0)  # -15% < -5%
        assert hs.unhalt_recovery_cycles == 0  # counter reset

    def test_vol_spike_not_allowed_for_auto_unhalt(self):
        hs = HaltState()
        hs.set_halt("VOL_SPIKE", "vol_breach")
        hs.update_peak(100.0)
        for _ in range(DRAWDOWN_AUTO_UNHALT_MIN_CYCLES + 1):
            result = hs.check_auto_unhalt(cycles_elapsed=10, total_equity=99.0)
        assert result is False  # VOL_SPIKE never unhalts automatically


# ── maybe_warn_persistent ─────────────────────────────────────────────────────


class TestMaybeWarnPersistent:
    def test_throttle_skips_within_10_cycles(self, caplog):
        caplog.set_level("WARNING")
        hs = HaltState()
        hs.emergency_halt = True
        hs.maybe_warn_persistent(cycles_elapsed=1)
        assert caplog.text != ""  # first call fires
        caplog.clear()
        hs.maybe_warn_persistent(cycles_elapsed=2)
        assert caplog.text == ""  # within throttle window

    def test_fires_after_throttle_window(self, caplog):
        caplog.set_level("WARNING")
        hs = HaltState()
        hs.emergency_halt = True
        hs.maybe_warn_persistent(cycles_elapsed=1)
        caplog.clear()
        hs.maybe_warn_persistent(cycles_elapsed=12)  # +11 cycles → fires
        assert "emergency_halt_persistent" in caplog.text

    def test_fires_even_when_not_halted(self, caplog):
        """maybe_warn_persistent fires on throttle regardless of halt state.

        The caller (_run_phases) checks emergency_halt before calling.
        """
        caplog.set_level("WARNING")
        hs = HaltState()
        hs.emergency_halt = False  # not halted
        hs.halt_reason = "DRAWDOWN"
        hs.maybe_warn_persistent(cycles_elapsed=1)
        assert "emergency_halt_persistent" in caplog.text

    def test_includes_total_equity_in_log(self, caplog):
        caplog.set_level("WARNING")
        hs = HaltState()
        hs.emergency_halt = True
        hs.peak_portfolio_value = 1000.0
        hs.maybe_warn_persistent(cycles_elapsed=1, total_equity=950.0)
        assert "live_mtm=950.00" in caplog.text
        assert "1000.00" in caplog.text  # peak

    def test_none_equity_logs_none(self, caplog):
        caplog.set_level("WARNING")
        hs = HaltState()
        hs.emergency_halt = True
        hs.maybe_warn_persistent(cycles_elapsed=1, total_equity=None)
        assert "live_mtm=None" in caplog.text

    def test_none_peak_logs_none(self, caplog):
        caplog.set_level("WARNING")
        hs = HaltState()
        hs.emergency_halt = True
        hs.peak_portfolio_value = None
        hs.maybe_warn_persistent(cycles_elapsed=1)
        assert "peak=None" in caplog.text
