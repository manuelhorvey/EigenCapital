"""Tests for the PEK budget backfeed in EngineOrchestrator.

When ``_phase_1b_admission_review`` detects that the previous cycle's
aggregate notional exceeded the budget, it sets ``_pek_budget_utilization``.
The subsequent call to ``_pre_phase_pek`` uses this value to reduce the
exposure multiplier for all actors, making budget control *proactive*
rather than purely reactive (closing positions after overrun).
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
        # Minimal pos_mgr so _inject_cycle_context can set exposure_multiplier
        pos_mgr = MagicMock()
        pos_mgr.has_position.return_value = False
        engine.pos_mgr = pos_mgr
        engine._cycle_total_equity = 0.0
        engine._cycle_drawdown_pct = 0.0

        actor = MagicMock(spec=AssetActor)
        actor.name = name
        actor.health = MagicMock()
        actor.health.HALTED = "HALTED"
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
    """Verify the backfeed correctly reduces the exposure multiplier."""

    def test_no_backfeed_on_first_cycle(self) -> None:
        """First cycle: ``_pek_budget_utilization`` attribute doesn't exist
        yet, so ``getattr`` returns ``1.0`` and no reduction is applied."""
        actors = _dummy_actors()
        orch = EngineOrchestrator(actors)

        # Pre-phase sets up defaults — the backfeed check should be a no-op
        defaults, max_leverage, budget_ref = orch._pre_phase_pek()

        # After pre-phase, the actors' exposure_multiplier should still be 1.0
        # (the default from compute_exposure_multiplier with 0% drawdown)
        for actor in actors.values():
            assert actor._engine.pos_mgr.exposure_multiplier == 1.0, (
                f"{actor.name}: expected 1.0, got {actor._engine.pos_mgr.exposure_multiplier}"
            )

    def test_backfeed_reduces_after_overrun(self) -> None:
        """After a budget overrun, the next cycle's exposure multiplier
        is reduced proportionally."""
        actors = _dummy_actors()
        orch = EngineOrchestrator(actors)

        # Simulate a budget overrun: set utilization > 1.0
        # This normally happens inside _phase_1b_admission_review
        orch._pek_budget_utilization = 2.0  # 2x budget used

        defaults, max_leverage, budget_ref = orch._pre_phase_pek()

        # With 2x utilization, exp_mult should be halved: 1.0 * (1/2) = 0.5
        for actor in actors.values():
            assert actor._engine.pos_mgr.exposure_multiplier == 0.5, (
                f"{actor.name}: expected 0.5, got {actor._engine.pos_mgr.exposure_multiplier}"
            )

    def test_no_backfeed_at_normal_utilization(self) -> None:
        """When utilization is exactly 1.0 or below, no reduction."""
        actors = _dummy_actors()
        orch = EngineOrchestrator(actors)

        orch._pek_budget_utilization = 1.0

        defaults, max_leverage, budget_ref = orch._pre_phase_pek()

        for actor in actors.values():
            assert actor._engine.pos_mgr.exposure_multiplier == 1.0, (
                f"{actor.name}: expected 1.0, got {actor._engine.pos_mgr.exposure_multiplier}"
            )

    def test_partial_backfeed(self) -> None:
        """At 1.5x utilization, exp_mult should be reduced to 1/1.5 ≈ 0.6667."""
        actors = _dummy_actors()
        orch = EngineOrchestrator(actors)

        orch._pek_budget_utilization = 1.5

        defaults, max_leverage, budget_ref = orch._pre_phase_pek()

        expected = round(1.0 / 1.5, 4)
        for actor in actors.values():
            actual = round(actor._engine.pos_mgr.exposure_multiplier, 4)
            assert actual == expected, (
                f"{actor.name}: expected {expected}, got {actual}"
            )

    def test_extreme_overrun_caps_at_minimum(self) -> None:
        """At 10x utilization, exp_mult is capped to 0.1 (1/10)."""
        actors = _dummy_actors()
        orch = EngineOrchestrator(actors)

        orch._pek_budget_utilization = 10.0

        defaults, max_leverage, budget_ref = orch._pre_phase_pek()

        expected = round(1.0 / 10.0, 4)
        for actor in actors.values():
            actual = round(actor._engine.pos_mgr.exposure_multiplier, 4)
            assert actual == expected, (
                f"{actor.name}: expected {expected}, got {actual}"
            )

    def test_getattr_default_on_first_cycle(self) -> None:
        """If ``_pek_budget_utilization`` is not set on the orchestrator
        (first cycle), ``getattr`` returns 1.0 and no reduction occurs."""
        # Deliberately do NOT set _pek_budget_utilization
        actors = _dummy_actors()
        orch = EngineOrchestrator(actors)

        # Verify attribute does not exist
        assert not hasattr(orch, "_pek_budget_utilization")

        defaults, max_leverage, budget_ref = orch._pre_phase_pek()

        for actor in actors.values():
            assert actor._engine.pos_mgr.exposure_multiplier == 1.0, (
                f"{actor.name}: expected 1.0, got {actor._engine.pos_mgr.exposure_multiplier}"
            )
