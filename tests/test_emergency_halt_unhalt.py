"""Tests for automatic + manual un-halting of the HALT_RATIO emergency halt.

Covers:
    - halt_ratio auto-unhalt when actor health recovers (sustained healthy cycles)
    - no auto-unhalt while halt_ratio still exceeds max_halt_ratio
    - no auto-unhalt on the first cycle after restart (_cycles_elapsed < 1)
    - manual reset via orchestrator.reset_emergency_halt()
    - control route reaches the live registered engine
"""

from __future__ import annotations

import pytest

from paper_trading.api.control_routes import handle_emergency_halt_reset
from paper_trading.governance.health import get_registered_engine, register_engine
from paper_trading.orchestrator.actor import ActorHealth, AssetActor
from paper_trading.orchestrator.engine import (
    HALT_RATIO_AUTO_UNHALT_MIN_CYCLES,
    EngineOrchestrator,
    HaltReason,
)


class _MockPosMgr:
    def __init__(self):
        self.exposure_multiplier = 1.0


class _MockAssetEngine:
    """Minimal mock simulating what EngineOrchestrator accesses on AssetEngine."""

    def __init__(self, name: str, mtm_value: float = 1000.0):
        self.name = name
        self.mtm_value = mtm_value
        self.pos_mgr = _MockPosMgr()
        self.current_price = 100.0


def _make_halted_orchestrator(
    n_halted: int = 2,
    n_total: int = 3,
    cycles_elapsed: int = 10,
) -> tuple[EngineOrchestrator, dict[str, AssetActor]]:
    engines = {f"A{i}": _MockAssetEngine(f"A{i}") for i in range(n_total)}
    actors = {name: AssetActor(name, eng) for name, eng in engines.items()}
    orch = EngineOrchestrator(actors, max_halt_ratio=0.5)
    orch._cycles_elapsed = cycles_elapsed
    for i, name in enumerate(actors):
        if i < n_halted:
            actors[name].health = ActorHealth.HALTED
    orch._emergency_halt = True
    orch._halt_reason = HaltReason.HALT_RATIO
    orch._halt_detail = f"halt_ratio={n_halted / n_total:.4f}"
    return orch, actors


class TestHaltRatioAutoUnhalt:
    def test_unhalts_after_sustained_healthy_cycles(self):
        orch, actors = _make_halted_orchestrator(n_halted=0, n_total=3)
        assert orch.emergency_halt is True
        assert orch._halt_reason == HaltReason.HALT_RATIO

        for _ in range(HALT_RATIO_AUTO_UNHALT_MIN_CYCLES):
            orch._check_auto_unhalt_eligibility()

        assert orch.emergency_halt is False
        assert orch._halt_reason is None
        assert all(a.health == ActorHealth.GREEN for a in actors.values())

    def test_does_not_unhalt_while_ratio_still_high(self):
        orch, actors = _make_halted_orchestrator(n_halted=2, n_total=3)
        # 2/3 halted = 0.667 > max_halt_ratio=0.5, stays halted indefinitely
        for _ in range(HALT_RATIO_AUTO_UNHALT_MIN_CYCLES * 3):
            orch._check_auto_unhalt_eligibility()
        assert orch.emergency_halt is True
        assert orch._halt_reason == HaltReason.HALT_RATIO
        assert orch._unhalt_recovery_cycles == 0

    def test_resets_on_recovery_after_previously_high(self):
        orch, actors = _make_halted_orchestrator(n_halted=2, n_total=3)
        for _ in range(5):
            orch._check_auto_unhalt_eligibility()
        assert orch.emergency_halt is True

        # Actors recover: all GREEN → ratio drops to 0.0
        for name in actors:
            actors[name].health = ActorHealth.GREEN
        for _ in range(HALT_RATIO_AUTO_UNHALT_MIN_CYCLES):
            orch._check_auto_unhalt_eligibility()
        assert orch.emergency_halt is False

    def test_skips_first_cycle_after_restart(self):
        orch, actors = _make_halted_orchestrator(n_halted=0, n_total=3, cycles_elapsed=0)
        assert orch._cycles_elapsed < 1
        orch._check_auto_unhalt_eligibility()
        assert orch.emergency_halt is True


class TestManualReset:
    def test_reset_emergency_halt_clears_state(self):
        orch, actors = _make_halted_orchestrator(n_halted=2, n_total=3)
        orch.reset_emergency_halt()
        assert orch.emergency_halt is False
        assert orch._halt_reason is None
        assert orch._halt_detail == ""
        assert all(a.health == ActorHealth.GREEN for a in actors.values())

    def test_reset_idempotent(self):
        orch, _ = _make_halted_orchestrator(n_halted=0, n_total=3)
        orch.reset_emergency_halt()
        orch.reset_emergency_halt()
        assert orch.emergency_halt is False


class TestControlRoute:
    def test_reset_route_reaches_live_engine(self):
        orch, _ = _make_halted_orchestrator(n_halted=2, n_total=3)

        class _FakeEngine:
            _orchestrator = orch

        fake = _FakeEngine()
        register_engine(fake)
        try:
            assert get_registered_engine() is fake
            data, status = handle_emergency_halt_reset(b"{}")
        finally:
            register_engine(None)
        assert status == 200
        assert orch.emergency_halt is False

    def test_reset_route_503_without_engine(self):
        register_engine(None)
        data, status = handle_emergency_halt_reset(b"{}")
        assert status == 503


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-v"]))
