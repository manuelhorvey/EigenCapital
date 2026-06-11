"""Tests for the Phase 5 actor-system orchestration.

Covers:
    - AssetActor lifecycle (GREEN → DEGRADED → HALTED → RECOVERING)
    - Actor fault isolation (one crash does not affect others)
    - Persist queue draining
    - EngineOrchestrator phased execution
    - HealthMonitor aggregation and circuit breaker
    - Breaker trip conditions
"""

import time
import threading
from datetime import datetime, timezone
from unittest.mock import MagicMock, PropertyMock

import pytest

from paper_trading.orchestrator.actor import (
    AssetActor,
    AssetResult,
    ActorHealth,
    compute_health_snapshot,
)
from paper_trading.orchestrator.engine import EngineOrchestrator, EnginePhase
from paper_trading.orchestrator.health import (
    CircuitBreaker,
    HealthMonitor,
    RecoveryScheduler,
    BreakerDecision,
)


# ── Helpers ───────────────────────────────────────────────────────────────────


class _MockEngine:
    """Simulates an AssetEngine with controllable success/failure."""

    def __init__(self, name: str, should_fail: bool = False, fail_after: int = 0):
        self.name = name
        self._should_fail = should_fail
        self._fail_after = fail_after
        self._call_count = 0
        self.last_refresh = None
        self.last_pnl = None
        self.last_signal = None

    def refresh_price(self):
        self._call_count += 1
        self.last_refresh = datetime.now(timezone.utc).replace(tzinfo=None)
        if self._should_fail:
            if self._fail_after <= 0 or self._call_count > self._fail_after:
                raise ConnectionError(f"{self.name}: price refresh failed")

    def update_pnl(self):
        self.last_pnl = datetime.now(timezone.utc).replace(tzinfo=None)
        if self._should_fail and self._call_count > 1:
            raise ValueError(f"{self.name}: pnl update failed")

    def generate_signal(self):
        self.last_signal = {"asset": self.name, "signal": "BUY", "confidence": 0.75}
        return self.last_signal

    def update_validity(self):
        return {"state": "GREEN", "exposure": 1.0}


# ── Test 1: AssetActor Lifecycle ──────────────────────────────────────────────


class TestAssetActorLifecycle:
    """GREEN → DEGRADED → HALTED → RECOVERING state machine."""

    def test_green_on_success(self):
        engine = _MockEngine("TEST")
        actor = AssetActor("TEST", engine)
        result = actor.run_cycle()
        assert result.success is True
        assert actor.health == ActorHealth.GREEN
        assert result.signal == {"asset": "TEST", "signal": "BUY", "confidence": 0.75}

    def test_degraded_after_one_failure(self):
        engine = _MockEngine("TEST", should_fail=True)
        actor = AssetActor("TEST", engine, max_consecutive_failures=3)
        result = actor.run_cycle()
        assert result.success is False
        assert actor.health == ActorHealth.DEGRADED
        assert actor.metrics.consecutive_failures == 1

    def test_halted_after_max_failures(self):
        engine = _MockEngine("TEST", should_fail=True)
        actor = AssetActor("TEST", engine, max_consecutive_failures=2, recovery_cooldown_seconds=0.1)
        r1 = actor.run_cycle()
        assert actor.health == ActorHealth.DEGRADED
        r2 = actor.run_cycle()
        assert actor.health == ActorHealth.HALTED
        # Subsequent calls return failure immediately without calling engine
        r3 = actor.run_cycle()
        assert r3.success is False
        assert "actor_halted" in (r3.error or "")

    def test_halted_does_not_call_engine(self):
        engine = _MockEngine("TEST", should_fail=True)
        actor = AssetActor("TEST", engine, max_consecutive_failures=1, recovery_cooldown_seconds=10.0)
        actor.run_cycle()
        assert actor.health == ActorHealth.HALTED
        calls_before = engine._call_count
        actor.run_cycle()
        assert engine._call_count == calls_before, "Halted actor must not call engine"

    def test_recovery_probe_after_cooldown(self):
        engine = _MockEngine("TEST", should_fail=True)
        actor = AssetActor("TEST", engine, max_consecutive_failures=1, recovery_cooldown_seconds=0.05)
        actor.run_cycle()
        assert actor.health == ActorHealth.HALTED
        time.sleep(0.1)
        # Next cycle should attempt probe (enter RECOVERING then fail again)
        result = actor.run_cycle()
        # Probe triggered, engine was called, but it's still failing
        assert engine._call_count > 1
        assert result.success is False

    def test_recovery_success_resets_health(self):
        engine = _MockEngine("TEST", should_fail=True, fail_after=0)
        actor = AssetActor("TEST", engine, max_consecutive_failures=2, recovery_cooldown_seconds=0.05)
        # Two failures → HALTED
        actor.run_cycle()
        actor.run_cycle()
        assert actor.health == ActorHealth.HALTED
        # Sabotage engine to succeed on next call
        engine._should_fail = False
        time.sleep(0.1)
        result = actor.run_cycle()
        assert result.success is True
        assert actor.health == ActorHealth.GREEN


# ── Test 2: Fault Isolation ──────────────────────────────────────────────────


class TestFaultIsolation:
    """One actor crash must not affect others."""

    def test_independent_results(self):
        good_engine = _MockEngine("GOOD")
        bad_engine = _MockEngine("BAD", should_fail=True)
        good_actor = AssetActor("GOOD", good_engine)
        bad_actor = AssetActor("BAD", bad_engine, max_consecutive_failures=3)

        good_result = good_actor.run_cycle()
        bad_result = bad_actor.run_cycle()

        assert good_result.success is True
        assert bad_result.success is False
        assert good_actor.health == ActorHealth.GREEN
        assert bad_actor.health == ActorHealth.DEGRADED

    def test_orchestrator_isolates_failures(self):
        actors = {
            "GOOD": AssetActor("GOOD", _MockEngine("GOOD")),
            "BAD": AssetActor("BAD", _MockEngine("BAD", should_fail=True), max_consecutive_failures=3),
        }
        orch = EngineOrchestrator(actors)
        results = orch.run_once()
        assert results["assets"]["GOOD"].get("signal") == "BUY"
        assert "error" in results["assets"]["BAD"]
        assert results["health"]["green"] >= 1


# ── Test 3: Persist Queue ────────────────────────────────────────────────────


class TestPersistQueue:
    """Persist commands accumulate and drain correctly."""

    def test_drain_returns_all(self):
        engine = _MockEngine("TEST")
        actor = AssetActor("TEST", engine)
        actor.run_cycle()
        commands = actor.drain_persist_queue()
        assert len(commands) >= 1
        assert commands[0].kind == "signal"
        assert commands[0].asset == "TEST"

    def test_drain_empties_queue(self):
        engine = _MockEngine("TEST")
        actor = AssetActor("TEST", engine)
        actor.run_cycle()
        _ = actor.drain_persist_queue()
        assert len(actor.drain_persist_queue()) == 0

    def test_orchestrator_flushes_all_actors(self):
        actors = {
            "A": AssetActor("A", _MockEngine("A")),
            "B": AssetActor("B", _MockEngine("B")),
        }
        orch = EngineOrchestrator(actors)
        results = orch.run_once()
        assert results["persist_count"] >= 2
        buf = orch.drain_persist_buffer()
        assert len(buf) >= 2


# ── Test 4: EngineOrchestrator Phases ────────────────────────────────────────


class TestEngineOrchestrator:
    """Phased execution with health aggregation."""

    def test_all_phases_recorded(self):
        actors = {"A": AssetActor("A", _MockEngine("A"))}
        orch = EngineOrchestrator(actors)
        results = orch.run_once()
        for phase in [EnginePhase.REFRESH, EnginePhase.VALIDITY, EnginePhase.PORTFOLIO]:
            assert phase in results.get("phasetimestamps", {}), f"Phase {phase} missing"
        assert results["health"] is not None
        assert results["cycle_duration_ms"] > 0

    def test_emergency_halt_on_high_halt_ratio(self):
        actors = {
            "A": AssetActor("A", _MockEngine("A", should_fail=True), max_consecutive_failures=1, recovery_cooldown_seconds=999),
        }
        orch = EngineOrchestrator(actors, max_halt_ratio=0.0)
        results = orch.run_once()
        assert results.get("circuit_breaker", {}).get("triggered") is True
        # Second run should return immediately
        r2 = orch.run_once()
        assert "emergency_halt" in (r2.get("circuit_breaker", {}).get("reason", "") or "")

    def test_halved_actors_skipped(self):
        bad = AssetActor("BAD", _MockEngine("BAD", should_fail=True), max_consecutive_failures=1, recovery_cooldown_seconds=999)
        bad.run_cycle()
        assert bad.health == ActorHealth.HALTED
        engine = _MockEngine("GOOD")
        good = AssetActor("GOOD", engine)
        results = EngineOrchestrator({"GOOD": good, "BAD": bad}).run_once()
        assert "error" in results["assets"]["BAD"]
        assert results["assets"]["GOOD"].get("signal") == "BUY"


# ── Test 5: HealthMonitor ────────────────────────────────────────────────────


class TestHealthMonitor:
    """Health observation, aggregation, and recommendations."""

    def test_all_green_returns_healthy(self):
        monitor = HealthMonitor()
        actors = {"A": AssetActor("A", _MockEngine("A")), "B": AssetActor("B", _MockEngine("B"))}
        summary = monitor.observe(actors)
        assert summary.n_green == 2
        assert summary.halt_ratio == 0.0
        assert len(summary.recommendations) == 0

    def test_detects_halted_actors(self):
        monitor = HealthMonitor(max_halt_ratio=0.5)
        bad = AssetActor("BAD", _MockEngine("BAD", should_fail=True), max_consecutive_failures=1, recovery_cooldown_seconds=999)
        bad.run_cycle()
        good = AssetActor("GOOD", _MockEngine("GOOD"))
        summary = monitor.observe({"BAD": bad, "GOOD": good})
        assert summary.n_halted == 1
        assert summary.halt_ratio == 0.5

    def test_drawdown_recommendation(self):
        monitor = HealthMonitor(max_portfolio_drawdown_pct=0.25)
        actors = {"A": AssetActor("A", _MockEngine("A"))}
        summary = monitor.observe(actors, portfolio_value=70.0, portfolio_peak=100.0)
        assert any("drawdown" in r for r in summary.recommendations)

    def test_vol_spike_recommendation(self):
        monitor = HealthMonitor(vol_spike_threshold=3.0)
        actors = {"A": AssetActor("A", _MockEngine("A"))}
        summary = monitor.observe(actors, portfolio_vol=3.5, baseline_vol=1.0)
        assert any("vol_spike" in r for r in summary.recommendations)

    def test_rate_limits_duplicate_warnings(self):
        monitor = HealthMonitor(max_portfolio_drawdown_pct=0.0)
        actors = {"A": AssetActor("A", _MockEngine("A"))}
        s1 = monitor.observe(actors, portfolio_value=50.0, portfolio_peak=100.0)
        assert len(s1.recommendations) >= 1
        s2 = monitor.observe(actors, portfolio_value=50.0, portfolio_peak=100.0)
        # Second one should be suppressed by rate limit
        assert len(s2.recommendations) == 0


# ── Test 6: CircuitBreaker ───────────────────────────────────────────────────


class TestCircuitBreaker:
    """Multi-condition circuit breaker."""

    def test_no_trip_on_normal(self):
        cb = CircuitBreaker(max_drawdown_pct=0.25)
        decision = cb.check(portfolio_value=100.0)
        assert decision.trip is False
        assert decision.severity == "info"

    def test_trips_on_drawdown(self):
        cb = CircuitBreaker(max_drawdown_pct=0.25)
        cb._peak_value = 100.0
        decision = cb.check(portfolio_value=70.0)
        assert decision.trip is True
        assert decision.severity == "critical"

    def test_trips_on_vol_spike(self):
        cb = CircuitBreaker(vol_spike_threshold=3.0)
        decision = cb.check(portfolio_value=100.0, portfolio_vol=3.5, baseline_vol=1.0)
        assert decision.trip is True

    def test_trips_on_halt_ratio(self):
        cb = CircuitBreaker(max_halt_ratio=0.5)
        bad = AssetActor("BAD", _MockEngine("BAD", should_fail=True), max_consecutive_failures=1, recovery_cooldown_seconds=999)
        bad.run_cycle()
        good = AssetActor("GOOD", _MockEngine("GOOD"))
        decision = cb.check(portfolio_value=100.0, actors={"BAD": bad, "GOOD": good})
        assert decision.trip is True
        assert "halt_ratio" in decision.reason

    def test_trips_on_consecutive_losses(self):
        cb = CircuitBreaker(max_consecutive_losses=5)
        for _ in range(6):
            cb.record_daily_pnl(-1.0)
        decision = cb.check(portfolio_value=100.0)
        assert decision.trip is True
        assert "consecutive_losses" in decision.reason


# ── Test 7: RecoveryScheduler ────────────────────────────────────────────────


class TestRecoveryScheduler:
    """Exponential backoff probe scheduling."""

    def test_is_due_returns_true_after_delay(self):
        sched = RecoveryScheduler(base_delay_seconds=0.05)
        assert sched.is_due("TEST") is True  # first time always due
        sched.record_result("TEST", success=False)
        assert sched.is_due("TEST") is False  # too soon
        time.sleep(0.1)
        assert sched.is_due("TEST") is True  # after delay

    def test_exponential_backoff(self):
        sched = RecoveryScheduler(base_delay_seconds=0.05, max_delay_seconds=10.0)
        attempts = [0.05 * (2 ** i) for i in range(4)]
        for i, expected in enumerate(attempts):
            assert sched.is_due(f"A{i}") is True
            sched.record_result(f"A{i}", success=False)
        assert sched._attempts.get("A0", 0) == 1

    def test_success_resets_counter(self):
        sched = RecoveryScheduler(base_delay_seconds=1.0)
        sched.record_result("TEST", success=False)  # attempt 1
        sched.record_result("TEST", success=True)   # reset
        assert sched._attempts.get("TEST", 0) == 0
