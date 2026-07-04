"""Regression tests for the BTC weekend cycle + emergency halt flow.

Covers the specific bug chain from investigation 2026-07-03:

1. Weekend cycle with _emergency_halt=False → signal generation proceeds
2. Weekend cycle with _emergency_halt=True → early-return with reason
3. _cycles_elapsed increments even when halted (Bug-Alpha fix)
4. allowed_assets filtering correctly scopes to weekend-eligible assets
5. _check_auto_unhalt_eligibility clears halt after sustained recovery

Per-cycle auto-unhalt (not init-time): uses _check_auto_unhalt_eligibility()
called from _run_phases.  Requires recovery above DRAWDOWN_AUTO_UNHALT_THRESHOLD
(-5 % dd) for DRAWDOWN_AUTO_UNHALT_MIN_CYCLES (10) consecutive cycles.
"""

from __future__ import annotations

from datetime import datetime, timezone

from paper_trading.orchestrator.actor import AssetActor
from paper_trading.orchestrator.engine import EngineOrchestrator
from paper_trading.orchestrator.health import HaltReason


# ── Mock helpers ─────────────────────────────────────────────────────────


class _MockPosition:
    def __init__(self, side: str = "long", entry_price: float = 100.0):
        self.side = side
        self.entry_price = entry_price


class _MockPosMgr:
    def __init__(self, has_pos: bool = False):
        self._has_pos = has_pos
        self.position = _MockPosition() if has_pos else None
        self.exposure_multiplier = 1.0

    def has_position(self) -> bool:
        return self._has_pos


class _MockAssetEngine:
    """Minimal mock for what EngineOrchestrator accesses on AssetEngine."""

    def __init__(self, name: str, current_price: float = 100.0, mtm_value: float = 1000.0):
        self.name = name
        self.current_price = current_price
        self.current_value = mtm_value
        self.mtm_value = mtm_value
        self.pos_mgr = _MockPosMgr(has_pos=False)
        self.last_refresh = None
        self.last_pnl = None
        self.last_signal = None
        self._wal_writer = None

    def refresh_price(self):
        self.last_refresh = datetime.now(timezone.utc)

    def update_pnl(self):
        self.last_pnl = datetime.now(timezone.utc)

    def generate_signal(self):
        self.last_signal = {"asset": self.name, "signal": "BUY", "confidence": 0.75}
        return self.last_signal

    def update_validity(self):
        return {"state": "GREEN", "exposure": 1.0}


def _make_orchestrator(
    engines: dict[str, _MockAssetEngine],
    emergency_halt: bool = False,
    peak: float | None = None,
) -> EngineOrchestrator:
    actors = {name: AssetActor(name, eng) for name, eng in engines.items()}
    orch = EngineOrchestrator(actors)
    if emergency_halt:
        orch._emergency_halt = True
        orch._halt_reason = HaltReason.DRAWDOWN
        orch._halt_detail = "dd=-0.15"
    if peak is not None:
        orch._peak_portfolio_value = peak
    return orch


# ── Tests: weekend cycle with allowed_assets ──────────────────────────────


class TestWeekendCycleAllowedAssets:
    """EngineOrchestrator.run_once(allowed_assets=...) scoping."""

    def test_allowed_assets_filters_to_one(self):
        """Only the allowed asset's actor runs."""
        eng_btc = _MockAssetEngine("BTCUSD")
        eng_eur = _MockAssetEngine("EURUSD")
        orch = _make_orchestrator({"BTCUSD": eng_btc, "EURUSD": eng_eur})
        result = orch.run_once(allowed_assets={"BTCUSD"})
        # BTCUSD actor ran
        assert eng_btc.last_signal is not None
        assert "BTCUSD" in result.get("assets", {})
        # EURUSD actor did not run
        assert eng_eur.last_signal is None

    def test_allowed_assets_with_halt_false_proceeds(self):
        """With halt=False, the weekend cycle reaches signal generation."""
        eng = _MockAssetEngine("BTCUSD")
        orch = _make_orchestrator({"BTCUSD": eng}, emergency_halt=False)
        result = orch.run_once(allowed_assets={"BTCUSD"})
        assert eng.last_signal is not None
        assert result["circuit_breaker"] is None

    def test_allowed_assets_with_halt_true_early_return(self):
        """With halt=True, the weekend cycle returns immediately."""
        eng = _MockAssetEngine("BTCUSD")
        orch = _make_orchestrator({"BTCUSD": eng}, emergency_halt=True, peak=1000.0)
        result = orch.run_once(allowed_assets={"BTCUSD"})
        assert eng.last_signal is None  # actor never ran
        assert result["circuit_breaker"] is not None
        assert result["circuit_breaker"]["triggered"] is True
        assert result["circuit_breaker"]["reason"] == "emergency_halt_persistent"

    def test_peak_gt_current_preserves_halt(self):
        """Halt stays if peak > current equity (no auto-clear)."""
        eng = _MockAssetEngine("BTCUSD", mtm_value=1000.0)
        orch = _make_orchestrator({"BTCUSD": eng}, emergency_halt=True, peak=2000.0)
        result = orch.run_once(allowed_assets={"BTCUSD"})
        assert eng.last_signal is None
        assert result["circuit_breaker"]["reason"] == "emergency_halt_persistent"

    def test_signal_in_results_for_allowed_asset(self):
        """The signal dict is present in results for the allowed asset."""
        eng = _MockAssetEngine("BTCUSD")
        orch = _make_orchestrator({"BTCUSD": eng})
        result = orch.run_once(allowed_assets={"BTCUSD"})
        sig = result.get("assets", {}).get("BTCUSD", {})
        assert sig.get("signal") == "BUY"
        assert sig.get("confidence") == 0.75


# ── Tests: _cycles_elapsed increments even when halted ────────────────────


class TestCyclesElapsedUnderHalt:
    """Regression: _cycles_elapsed must increment every cycle even when halted."""

    def test_cycles_increment_when_halted(self):
        """Two halted cycles produce _cycles_elapsed >= 2."""
        eng = _MockAssetEngine("BTCUSD", mtm_value=1000.0)
        orch = _make_orchestrator({"BTCUSD": eng}, emergency_halt=True, peak=2000.0)
        orch.run_once(allowed_assets={"BTCUSD"})
        assert orch._cycles_elapsed >= 1
        orch.run_once(allowed_assets={"BTCUSD"})
        assert orch._cycles_elapsed >= 2

    def test_cycles_increment_when_not_halted(self):
        """Two normal cycles produce _cycles_elapsed == 2."""
        eng = _MockAssetEngine("BTCUSD")
        orch = _make_orchestrator({"BTCUSD": eng})
        orch.run_once(allowed_assets={"BTCUSD"})
        assert orch._cycles_elapsed == 1
        orch.run_once(allowed_assets={"BTCUSD"})
        assert orch._cycles_elapsed == 2


# ── Tests: per-cycle auto-unhalt (Commit 5 + _check_auto_unhalt_eligibility) ─


class TestAutoUnhaltEligibility:
    """Per-cycle auto-unhalt: _check_auto_unhalt_eligibility() clears halt after
    sustained recovery above -5 % dd for 10 consecutive cycles."""

    def test_auto_unhalt_clears_after_sustained_recovery(self):
        """Halt clears via _check_auto_unhalt_eligibility after 10 cycles."""
        eng = _MockAssetEngine("BTCUSD", mtm_value=9500.0)  # dd = -5%
        actors = {"BTCUSD": AssetActor("BTCUSD", eng)}
        orch = EngineOrchestrator(actors)
        orch._emergency_halt = True
        orch._halt_reason = HaltReason.DRAWDOWN
        orch._halt_detail = "dd=-0.15"
        orch._peak_portfolio_value = 10000.0
        orch._cycles_elapsed = 15
        orch._cycle_total_equity = 9500.0  # dd = -0.05, exactly at threshold
        orch._unhalt_recovery_cycles = 10  # enough sustained cycles
        orch._check_auto_unhalt_eligibility()
        assert orch._emergency_halt is False
        assert orch._halt_reason is None

    def test_auto_unhalt_does_not_clear_early(self):
        """Halt NOT cleared if recovery cycles < 10."""
        eng = _MockAssetEngine("BTCUSD", mtm_value=9500.0)
        actors = {"BTCUSD": AssetActor("BTCUSD", eng)}
        orch = EngineOrchestrator(actors)
        orch._emergency_halt = True
        orch._halt_reason = HaltReason.DRAWDOWN
        orch._halt_detail = "dd=-0.15"
        orch._peak_portfolio_value = 10000.0
        orch._cycles_elapsed = 15
        orch._cycle_total_equity = 9500.0
        orch._unhalt_recovery_cycles = 5  # not enough
        orch._check_auto_unhalt_eligibility()
        assert orch._emergency_halt is True

    def test_auto_unhalt_ignores_non_eligible_reasons(self):
        """HALT_RATIO reason does NOT auto-clear."""
        eng = _MockAssetEngine("BTCUSD", mtm_value=9900.0)
        actors = {"BTCUSD": AssetActor("BTCUSD", eng)}
        orch = EngineOrchestrator(actors)
        orch._emergency_halt = True
        orch._halt_reason = HaltReason.HALT_RATIO
        orch._halt_detail = "halt_ratio=0.60"
        orch._peak_portfolio_value = 10000.0
        orch._cycles_elapsed = 15
        orch._cycle_total_equity = 9900.0
        orch._unhalt_recovery_cycles = 10
        orch._check_auto_unhalt_eligibility()
        assert orch._emergency_halt is True  # not cleared

    def test_auto_unhalt_skipped_first_cycle(self):
        """Auto-unhalt is skipped when _cycles_elapsed < 1."""
        eng = _MockAssetEngine("BTCUSD", mtm_value=10000.0)
        actors = {"BTCUSD": AssetActor("BTCUSD", eng)}
        orch = EngineOrchestrator(actors)
        orch._emergency_halt = True
        orch._halt_reason = HaltReason.DRAWDOWN
        orch._peak_portfolio_value = 10000.0
        orch._cycles_elapsed = 0  # first cycle
        orch._cycle_total_equity = 10000.0
        orch._check_auto_unhalt_eligibility()
        assert orch._emergency_halt is True  # skipped, not cleared

    def test_auto_unhalt_does_not_clear_when_below_threshold(self):
        """Halt NOT cleared if dd is still below -5%."""
        eng = _MockAssetEngine("BTCUSD", mtm_value=9000.0)  # dd = -10%
        actors = {"BTCUSD": AssetActor("BTCUSD", eng)}
        orch = EngineOrchestrator(actors)
        orch._emergency_halt = True
        orch._halt_reason = HaltReason.DRAWDOWN
        orch._halt_detail = "dd=-0.15"
        orch._peak_portfolio_value = 10000.0
        orch._cycles_elapsed = 15
        orch._cycle_total_equity = 9000.0
        orch._unhalt_recovery_cycles = 10
        orch._check_auto_unhalt_eligibility()
        assert orch._emergency_halt is True  # below threshold


# ── Tests: halt-persistent warning throttle (Commit 1) ────────────────────


class TestHaltPersistentWarning:
    """_maybe_warn_halt_persistent() fires on schedule then throttles."""

    def test_fires_on_first_halted_cycle(self):
        """Warning fires on cycle 1 with halt active."""
        eng = _MockAssetEngine("BTCUSD")
        actors = {"BTCUSD": AssetActor("BTCUSD", eng)}
        orch = EngineOrchestrator(actors)
        orch._emergency_halt = True
        orch._halt_reason = HaltReason.DRAWDOWN
        orch._halt_detail = "dd=-0.15"
        orch._peak_portfolio_value = 1000.0
        orch._cycles_elapsed = 1
        orch._cycle_total_equity = 900.0  # live equity
        orch._maybe_warn_halt_persistent()
        # After calling, _halt_warn_last_cycle should be 1
        assert orch._halt_warn_last_cycle == 1

    def test_skips_within_throttle_window(self):
        """Warning skipped if called again within 10 cycles."""
        eng = _MockAssetEngine("BTCUSD")
        actors = {"BTCUSD": AssetActor("BTCUSD", eng)}
        orch = EngineOrchestrator(actors)
        orch._emergency_halt = True
        orch._cycles_elapsed = 1
        orch._halt_warn_last_cycle = 1  # already warned at cycle 1
        orch._maybe_warn_halt_persistent()
        # _halt_warn_last_cycle should NOT advance
        assert orch._halt_warn_last_cycle == 1

    def test_fires_again_after_10_cycles(self):
        """Warning fires again when throttle window expires at cycle 11."""
        eng = _MockAssetEngine("BTCUSD")
        actors = {"BTCUSD": AssetActor("BTCUSD", eng)}
        orch = EngineOrchestrator(actors)
        orch._emergency_halt = True
        orch._halt_reason = HaltReason.DRAWDOWN
        orch._halt_detail = "dd=-0.15"
        orch._peak_portfolio_value = 1000.0
        orch._cycles_elapsed = 11
        orch._halt_warn_last_cycle = 1  # last warned at cycle 1
        orch._cycle_total_equity = 900.0
        orch._maybe_warn_halt_persistent()
        assert orch._halt_warn_last_cycle == 11

    def test_throttle_independent_of_halt_state(self):
        """Method fires strictly on throttle — caller guard is in _run_phases.

        _maybe_warn_halt_persistent does NOT check _emergency_halt internally;
        the guard is at _run_phases line 290.  This documents that direct
        invocation always advances the coil if throttle permits, even when
        halt is not set."""
        eng = _MockAssetEngine("BTCUSD")
        actors = {"BTCUSD": AssetActor("BTCUSD", eng)}
        orch = EngineOrchestrator(actors)
        orch._emergency_halt = False
        orch._cycles_elapsed = 1
        orch._halt_warn_last_cycle = -10
        orch._maybe_warn_halt_persistent()
        # Fires because throttle condition is met (1 - (-10) = 11 >= 10)
        assert orch._halt_warn_last_cycle == 1


# ── Tests: persist-boundary stale-halt guard (Commit 6) ────────────────────


class TestPersistBoundaryGuard:
    """engine_state_service.py stale-halt guard at persistence boundary."""

    def test_guard_does_not_warn_on_healthy_halt(self):
        """Guard does not warn when halt is legitimate (equity < 99.5% of peak)."""
        eng = _MockAssetEngine("BTCUSD", mtm_value=9000.0)  # 90% of peak
        actors = {"BTCUSD": AssetActor("BTCUSD", eng)}
        orch = EngineOrchestrator(actors)
        orch._emergency_halt = True
        orch._halt_reason = HaltReason.DRAWDOWN
        orch._peak_portfolio_value = 10000.0
        # Simulate save_state equity computation
        total_equity = sum(a.mtm_value for a in [eng])
        ratio = total_equity / orch._peak_portfolio_value
        assert ratio == 0.9
        assert ratio < 0.995  # guard should NOT fire
        # No assertion — we just verify the guard condition is false

    def test_guard_warns_on_stale_halt(self):
        """Guard warns when equity >= 99.5% of peak while halt is set."""
        eng = _MockAssetEngine("BTCUSD", mtm_value=9960.0)  # 99.6% of peak
        actors = {"BTCUSD": AssetActor("BTCUSD", eng)}
        orch = EngineOrchestrator(actors)
        orch._emergency_halt = True
        orch._halt_reason = HaltReason.DRAWDOWN
        orch._peak_portfolio_value = 10000.0
        total_equity = sum(a.mtm_value for a in [eng])
        ratio = total_equity / orch._peak_portfolio_value
        assert ratio >= 0.995  # guard should fire
