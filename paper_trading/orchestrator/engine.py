"""EngineOrchestrator — fault-isolated, phased execution loop.

Replaces PaperTradingEngine.run_once() with an actor-based design.

Design:
    - Each asset runs in its own AssetActor with isolated health tracking
    - Phases execute sequentially, but within each phase actors run in parallel
    - No actor exception can crash another actor or the orchestrator
    - Persistence is serialized through a single writer actor
    - Portfolio-level phase executes only after all asset phases complete

Invariants:
    I.  NO single asset failure halts portfolio operation
    II. NO actor writes to global state directly (uses persist queue)
    III. Portfolio-level circuit breakers observe aggregated health
    IV. Recovery probes do not block the main loop
"""

from __future__ import annotations

import atexit
import logging
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from typing import Any

from paper_trading.governance.drawdown_controls import check_drawdown_circuit_breaker
from paper_trading.orchestrator.actor import (
    AssetActor,
    AssetResult,
    compute_health_snapshot,
)
from paper_trading.replay.wal import WalWriter

logger = logging.getLogger("quantforge.orchestrator.engine")


class EnginePhase:
    REFRESH = "refresh"
    SIGNAL = "signal"
    VALIDITY = "validity"
    PORTFOLIO = "portfolio"
    PERSIST = "persist"


class EngineOrchestrator:
    """Fault-isolated execution orchestrator.

    Usage::
        orch = EngineOrchestrator(actors)
        results = orch.run_once()
    """

    def __init__(
        self,
        actors: dict[str, AssetActor],
        max_halt_ratio: float = 0.5,
        wal_writer: WalWriter | None = None,
        max_workers: int = 8,
    ):
        self._actors = actors
        self._max_halt_ratio = max_halt_ratio
        self._max_workers = max_workers or len(actors) * 2
        self._persist_buffer: list[dict] = []
        self._peak_portfolio_value: float | None = None
        self._emergency_halt: bool = False
        self._wal = wal_writer
        self._last_health: dict | None = None
        self._pool = ThreadPoolExecutor(
            max_workers=self._max_workers,
            thread_name_prefix="qf-actor",
        )
        atexit.register(self.shutdown)

    def run_once(self, market_data: dict | None = None) -> dict[str, Any]:
        """Execute one orchestrator cycle.  Returns phased results dict.

        Phases:
            1. REFRESH  — parallel actor cycles (price + PnL + signal)
            2. VALIDITY — parallel validity updates
            3. PORTFOLIO — aggregate health, circuit breakers
            4. PERSIST  — flush all persist queues to WAL

        Returns a dict with keys for each phase plus aggregated health.
        """
        results: dict[str, Any] = {
            "phasetimestamps": {},
            "assets": {},
            "circuit_breaker": None,
            "health": None,
        }

        if self._emergency_halt:
            results["circuit_breaker"] = {"triggered": True, "reason": "emergency_halt_persistent"}
            return results

        t0 = time.monotonic()

        # ── Phase 1: Refresh + Signal (parallel, isolated) ──────────────
        results["phasetimestamps"][EnginePhase.REFRESH] = datetime.now(timezone.utc).replace(tzinfo=None).isoformat()
        asset_results: dict[str, AssetResult] = {}

        def _run_actor(name: str, actor: AssetActor) -> AssetResult:
            if actor.health == actor.health.HALTED:
                return AssetResult.failed(name, "actor_halted", actor.metrics.cycle_id)
            return actor.run_cycle(market_data)

        futures = {self._pool.submit(_run_actor, n, a): n for n, a in self._actors.items()}
        for future in as_completed(futures):
            name = futures[future]
            try:
                asset_results[name] = future.result()
            except Exception as e:
                logger.critical("%s actor threw uncaught exception: %s", name, e)
                asset_results[name] = AssetResult.failed(name, f"uncaught: {e}")

        for name, result in asset_results.items():
            if result.success:
                results["assets"][name] = result.signal
            else:
                results["assets"][name] = {"error": result.error}

        # ── Phase 2: Validity updates (parallel) ────────────────────────
        results["phasetimestamps"][EnginePhase.VALIDITY] = datetime.now(timezone.utc).replace(tzinfo=None).isoformat()
        for name, actor in self._actors.items():
            if actor.health == actor.health.HALTED:
                continue
            try:
                actor._engine.update_validity()
            except Exception as e:
                logger.warning("%s validity update failed: %s", name, e)

        # ── Phase 3: Portfolio health aggregation ────────────────────────
        results["phasetimestamps"][EnginePhase.PORTFOLIO] = datetime.now(timezone.utc).replace(tzinfo=None).isoformat()
        health = compute_health_snapshot(self._actors)
        results["health"] = {
            "green": health.green,
            "degraded": health.degraded,
            "halted": health.halted,
            "halt_ratio": round(health.halt_ratio, 4),
            "total_failures": health.total_failures,
            "total_cycles": health.total_cycles,
            "system_healthy": health.is_system_healthy,
        }
        self._write_health_events(health)

        # ── Drawdown circuit breaker ──────────────────────────────────────
        total_value = sum(
            actor._engine.current_value for actor in self._actors.values() if hasattr(actor._engine, "current_value")
        )
        if self._peak_portfolio_value is None:
            self._peak_portfolio_value = total_value
        self._peak_portfolio_value = max(self._peak_portfolio_value, total_value)
        dd_result = check_drawdown_circuit_breaker(
            total_value,
            self._peak_portfolio_value,
            drawdown_limit=-0.15,
        )
        results["drawdown"] = dd_result
        if dd_result["halted"]:
            logger.error(
                "DRAWDOWN CIRCUIT BREAKER TRIGGERED: dd=%.2f%% — halting all actors",
                dd_result["drawdown"] * 100,
            )
            for actor in self._actors.values():
                if hasattr(actor._engine, "pos_mgr"):
                    actor._engine.pos_mgr.exposure_multiplier = 0.0
            self._emergency_halt = True
            results["circuit_breaker"] = {
                "triggered": True,
                "reason": f"drawdown_{dd_result['drawdown']:.4f}",
            }
            return results
        elif dd_result["exposure_multiplier"] < 1.0:
            for actor in self._actors.values():
                if hasattr(actor._engine, "pos_mgr"):
                    actor._engine.pos_mgr.exposure_multiplier = dd_result["exposure_multiplier"]

        # ── Halt ratio circuit breaker ──────────────────────────────────────
        if not health.is_system_healthy:
            logger.error(
                "PORTFOLIO CIRCUIT BREAKER: halt_ratio=%.2f exceeds max=%.2f — initiating emergency shutdown",
                health.halt_ratio,
                self._max_halt_ratio,
            )
            self._emergency_halt = True
            results["circuit_breaker"] = {
                "triggered": True,
                "halt_ratio": health.halt_ratio,
                "threshold": self._max_halt_ratio,
            }
            return results

        # ── Phase 4: Persist all queues ───────────────────────────────────
        results["phasetimestamps"][EnginePhase.PERSIST] = datetime.now(timezone.utc).replace(tzinfo=None).isoformat()
        persist_count = 0
        for name, actor in self._actors.items():
            commands = actor.drain_persist_queue()
            for cmd in commands:
                self._persist_buffer.append(cmd.__dict__)
                persist_count += 1
        results["persist_count"] = persist_count

        # ── WAL: commit state snapshot ────────────────────────────────────
        self._write_state_committed()

        results["cycle_duration_ms"] = round((time.monotonic() - t0) * 1000.0, 2)
        return results

    # ── WAL event emission ──────────────────────────────────────────────────────

    def _write_health_events(self, health) -> None:
        if self._wal is None:
            return
        current = {
            "green": health.green,
            "degraded": health.degraded,
            "halted": health.halted,
            "halt_ratio": round(health.halt_ratio, 4),
            "system_healthy": health.is_system_healthy,
        }
        if current != self._last_health:
            self._wal.write("actor_health", current)
            self._last_health = current

    def _write_state_committed(self) -> None:
        if self._wal is None:
            return
        snapshot: dict[str, Any] = {"actors": {}}
        for name, actor in self._actors.items():
            snapshot["actors"][name] = {
                "health": actor.health.name,
                "cycle_id": actor.metrics.cycle_id,
                "consecutive_failures": actor.metrics.consecutive_failures,
                "has_position": actor._engine.pos_mgr.has_position() if hasattr(actor._engine, "pos_mgr") else False,
            }
        snapshot["emergency_halt"] = self._emergency_halt
        self._wal.write("state_committed", snapshot)

    def drain_persist_buffer(self) -> list[dict]:
        """Return and clear the global persist buffer."""
        buf = list(self._persist_buffer)
        self._persist_buffer.clear()
        return buf

    @property
    def emergency_halt(self) -> bool:
        return self._emergency_halt

    def reset_emergency_halt(self) -> None:
        """Reset emergency halt (e.g., after manual review)."""
        self._emergency_halt = False
        for actor in self._actors.values():
            actor.reset()
        logger.warning("Emergency halt reset — all actors restored to GREEN")

    def shutdown(self) -> None:
        """Shut down the persistent thread pool (called on exit via atexit)."""
        self._pool.shutdown(wait=False)
        logger.debug("EngineOrchestrator thread pool shut down")
