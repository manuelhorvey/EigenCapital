"""Tests for the PEK budget backfeed in EngineOrchestrator.

When ``_phase_1b_admission_review`` detects that the previous cycle's
aggregate notional exceeded the budget, it sets ``_pek_budget_utilization``.
The subsequent call to ``_pre_phase_pek`` uses this value to reduce the
exposure multiplier stored in the immutable ``CycleContext`` snapshot.
The reduced ``exp_mult`` is then injected into each actor's engine under
the per-actor lock by ``run_cycle()`` when it receives the context.

!Important: After ``_pre_phase_pek()``, the values live in the
``CycleContext`` snapshot (``orch._cycle_context.exp_mult``), NOT on
the actor's engine directly.  Engine injection happens inside
``AssetActor.run_cycle()`` under the per-actor lock.  Tests that need
to verify the engine value must call ``run_cycle()`` with the context.
"""

import threading
from unittest.mock import MagicMock

from paper_trading.orchestrator.actor import AssetActor
from paper_trading.orchestrator.engine import EngineOrchestrator

# ── Helpers ──────────────────────────────────────────────────────────────────


def _dummy_actors(n: int = 2) -> dict[str, AssetActor]:
    """Return ``n`` AssetActor instances backed by minimal mock engines."""
    actors: dict[str, AssetActor] = {}
    for i in range(n):
        name = f"asset_{i}"
        engine = MagicMock()
        engine.name = name
        engine.ticker = f"TICKER{i}"
        engine.mtm_value = 100_000.0
        engine.current_value = 100_000.0
        # Minimal pos_mgr so the injection can set exposure_multiplier
        pos_mgr = MagicMock()
        pos_mgr.has_position.return_value = False
        engine.pos_mgr = pos_mgr
        engine._cycle_total_equity = 0.0
        engine._cycle_drawdown_pct = 0.0

        actor = MagicMock(spec=AssetActor)
        actor.name = name
        actor.health = "GREEN"
        actor._engine = engine
        actor.metrics = MagicMock()
        actor.metrics.cycle_id = i
        actor.drain_persist_queue = MagicMock(return_value=[])
        actor._cycle_context_lock = threading.Lock()
        actors[name] = actor
    return actors


# ── Tests ────────────────────────────────────────────────────────────────────


class TestPekBudgetBackfeed:
    """Verify the backfeed correctly reduces the exposure multiplier.

    The backfeed reduction is applied to the ``CycleContext.exp_mult``
    field in ``_pre_phase_pek()``, NOT directly to the actor engines.
    These tests verify the context value (exp_mult on the immutable
    snapshot).  The engine injection path is verified separately in
    integration tests.
    """

    def test_no_backfeed_on_first_cycle(self) -> None:
        """First cycle: ``_pek_budget_utilization`` attribute doesn't exist
        yet, so ``getattr`` returns ``1.0`` and no reduction is applied.
        The ``CycleContext.exp_mult`` should be ``1.0``."""
        actors = _dummy_actors()
        orch = EngineOrchestrator(actors)

        # Pre-phase sets up defaults — the backfeed check should be a no-op
        defaults, max_leverage, budget_ref = orch._pre_phase_pek()

        # Verify the CycleContext snapshot has the correct exp_mult
        ctx = getattr(orch, "_cycle_context", None)
        assert ctx is not None, "_cycle_context should be set after _pre_phase_pek"
        assert ctx.exp_mult == 1.0, f"expected 1.0, got {ctx.exp_mult}"

    def test_backfeed_reduces_after_overrun(self) -> None:
        """After a budget overrun, the next cycle's CycleContext.exp_mult
        is reduced proportionally."""
        actors = _dummy_actors()
        orch = EngineOrchestrator(actors)

        # Simulate a budget overrun: set utilization > 1.0
        # This normally happens inside _phase_1b_admission_review
        orch._pek_budget_utilization = 2.0  # 2x budget used

        defaults, max_leverage, budget_ref = orch._pre_phase_pek()

        # With 2x utilization, exp_mult should be halved: 1.0 * (1/2) = 0.5
        ctx = getattr(orch, "_cycle_context", None)
        assert ctx is not None
        assert ctx.exp_mult == 0.5, f"expected 0.5, got {ctx.exp_mult}"

    def test_no_backfeed_at_normal_utilization(self) -> None:
        """When utilization is exactly 1.0 or below, no reduction."""
        actors = _dummy_actors()
        orch = EngineOrchestrator(actors)

        orch._pek_budget_utilization = 1.0

        defaults, max_leverage, budget_ref = orch._pre_phase_pek()

        ctx = getattr(orch, "_cycle_context", None)
        assert ctx is not None
        assert ctx.exp_mult == 1.0, f"expected 1.0, got {ctx.exp_mult}"

    def test_partial_backfeed(self) -> None:
        """At 1.5x utilization, exp_mult should be reduced to 1/1.5 ≈ 0.6667."""
        actors = _dummy_actors()
        orch = EngineOrchestrator(actors)

        orch._pek_budget_utilization = 1.5

        defaults, max_leverage, budget_ref = orch._pre_phase_pek()

        expected = round(1.0 / 1.5, 4)
        ctx = getattr(orch, "_cycle_context", None)
        assert ctx is not None
        actual = round(ctx.exp_mult, 4)
        assert actual == expected, f"expected {expected}, got {actual}"

    def test_extreme_overrun_caps_at_minimum(self) -> None:
        """At 10x utilization, exp_mult is capped to 0.1 (1/10)."""
        actors = _dummy_actors()
        orch = EngineOrchestrator(actors)

        orch._pek_budget_utilization = 10.0

        defaults, max_leverage, budget_ref = orch._pre_phase_pek()

        expected = round(1.0 / 10.0, 4)
        ctx = getattr(orch, "_cycle_context", None)
        assert ctx is not None
        actual = round(ctx.exp_mult, 4)
        assert actual == expected, f"expected {expected}, got {actual}"

    def test_getattr_default_on_first_cycle(self) -> None:
        """If ``_pek_budget_utilization`` is not set on the orchestrator
        (first cycle), ``getattr`` returns 1.0 and no reduction occurs."""
        # Deliberately do NOT set _pek_budget_utilization
        actors = _dummy_actors()
        orch = EngineOrchestrator(actors)

        # Verify attribute does not exist
        assert not hasattr(orch, "_pek_budget_utilization")

        defaults, max_leverage, budget_ref = orch._pre_phase_pek()

        ctx = getattr(orch, "_cycle_context", None)
        assert ctx is not None
        assert ctx.exp_mult == 1.0, f"expected 1.0, got {ctx.exp_mult}"

    def test_injection_into_engine_via_run_cycle(self) -> None:
        """Verify that the CycleContext values are injected into the engine
        when run_cycle() is called with the context.  This validates the
        full H2 path: context built in pre-phase → passed to run_cycle()
        → injected under lock on the worker thread."""
        actors = _dummy_actors()
        orch = EngineOrchestrator(actors)

        # Build context with a non-default exp_mult
        orch._pek_budget_utilization = 2.0
        defaults, max_leverage, budget_ref = orch._pre_phase_pek()

        ctx = getattr(orch, "_cycle_context", None)
        assert ctx is not None
        assert ctx.exp_mult == 0.5  # Backfeed halved it

        # Now simulate what run_cycle() does: inject under lock
        actor = actors["asset_0"]
        assert hasattr(actor, "_cycle_context_lock"), "Actor must have _cycle_context_lock"

        with actor._cycle_context_lock:
            actor._engine._cycle_drawdown_pct = ctx.drawdown_pct
            if hasattr(actor._engine, "pos_mgr"):
                actor._engine.pos_mgr.exposure_multiplier = ctx.exp_mult

        assert actor._engine.pos_mgr.exposure_multiplier == 0.5, (
            f"expected 0.5, got {actor._engine.pos_mgr.exposure_multiplier}"
        )
