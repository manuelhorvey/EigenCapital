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
import threading
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
from paper_trading.orchestrator.health import CircuitBreaker
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

        # Portfolio leverage guardrail (Phase 2)
        self._leverage_lock = threading.Lock()
        self._backstop_multiplier: float = 1.0
        self._backstop_decay_cycles: int = 0

        # Portfolio circuit breaker (vol spike + consecutive loss)
        self._circuit_breaker = CircuitBreaker()

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

        # ── Pre-phase: equity snapshot for sizing guardrails ────────────
        # All actors see the same total_equity and drawdown derived from
        # end-of-previous-cycle values, avoiding intra-cycle races.  The
        # leverage budget is decremented atomically via Lock.
        from paper_trading.config_manager import get_config

        defaults = get_config().defaults or {}
        max_leverage = defaults.get("portfolio_max_leverage", 2.0)
        total_equity = sum(a._engine.mtm_value for a in self._actors.values() if hasattr(a._engine, "mtm_value"))
        if self._peak_portfolio_value is None or total_equity > self._peak_portfolio_value:
            self._peak_portfolio_value = total_equity
        current_dd = (
            (total_equity - self._peak_portfolio_value) / max(self._peak_portfolio_value, 1.0)
            if self._peak_portfolio_value
            else 0.0
        )
        # Leverage budget: max_leverage × equity × backstop_multiplier.
        # _backstop_multiplier and exposure_multiplier (drawdown/risk) are
        # independent dampers that compound multiplicatively — intentional
        # since they respond to different triggers (notional overshoot vs PnL).
        leverage_budget = max_leverage * total_equity * self._backstop_multiplier
        self._backstop_initial_budget = leverage_budget
        self._backstop_initial_equity = total_equity
        with self._leverage_lock:
            self._leverage_budget_remaining = leverage_budget
        # Mutable list so all actors share the same budget object — each
        # atomic decrement is visible to all readers.
        budget_ref = [leverage_budget]
        for actor in self._actors.values():
            actor._engine._cycle_total_equity = total_equity
            actor._engine._cycle_drawdown_pct = current_dd
            actor._engine._leverage_budget_ref = budget_ref
            actor._engine._leverage_lock = self._leverage_lock

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
                "DRAWDOWN CIRCUIT BREAKER TRIGGERED: dd=%.2f%% — flattening and halting all actors",
                dd_result["drawdown"] * 100,
            )
            self.flatten_positions(reason="drawdown_circuit_breaker")
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

        # ── Phase 3b: Portfolio circuit breaker (vol spike + losses) ──────
        prev_value = getattr(self, "_prev_portfolio_value", total_value)
        if total_value < prev_value:
            self._circuit_breaker.record_daily_pnl(total_value - prev_value)
        self._prev_portfolio_value = total_value

        breaker_result = self._circuit_breaker.check(
            portfolio_value=total_value,
            actors=self._actors,
        )
        results["circuit_breaker_full"] = {
            "trip": breaker_result.trip,
            "reason": breaker_result.reason,
            "severity": breaker_result.severity,
        }
        if breaker_result.trip:
            self._emergency_halt = True
            logger.error(
                "VOLATILITY CIRCUIT BREAKER TRIGGERED: %s — flattening and halting",
                breaker_result.reason,
            )
            self.flatten_positions(reason=f"circuit_breaker_{breaker_result.reason}")
            results["circuit_breaker"] = {
                "triggered": True,
                "reason": breaker_result.reason,
            }
            return results

        # ── Phase 3d: Portfolio leverage backstop ─────────────────────────
        # Should never fire in normal operation: the atomic Lock decrement
        # in _submit_to_broker() prevents overshoot.  If it does fire,
        # the equity snapshot was stale (intra-cycle PnL move) or there
        # is a wiring/ordering bug.  The backstop ratchets down and decays
        # exponentially toward 1.0 on subsequent breach-free cycles.
        #
        # The correction uses the fair budget (max_leverage × equity) as its
        # denominator — NOT the backstop-compounded budget — so consecutive
        # breaches of the same severity don't feed back into themselves and
        # produce runaway decay toward zero.  The min() ratchet still provides
        # "memory" across cycles: the worst correction ever seen is retained
        # until decay gradually loosens it.
        total_entered = sum(getattr(actor._engine, "_last_entry_notional", 0.0) for actor in self._actors.values())
        tolerance = defaults.get("portfolio_leverage_tolerance", 0.001)
        fair_budget = max_leverage * self._backstop_initial_equity
        if total_entered > fair_budget * (1.0 + tolerance):
            correction = fair_budget / max(total_entered, 1e-9)
            self._backstop_multiplier = min(self._backstop_multiplier, correction)
            self._backstop_decay_cycles = 0
            logger.warning(
                "LEVERAGE BACKSTOP FIRED: entered=%.2f fair_budget=%.2f overshoot=%.2f%% correction=%.4f new_mult=%.4f",
                total_entered,
                fair_budget,
                (total_entered / fair_budget - 1) * 100,
                correction,
                self._backstop_multiplier,
            )
        else:
            # Exponential decay of the penalty (1 - multiplier) toward 1.0.
            # Decay rate 10%/cycle → 37 cycles to recover from 0.5 to 0.99.
            self._backstop_decay_cycles += 1
            penalty = 1.0 - self._backstop_multiplier
            penalty *= 0.9
            self._backstop_multiplier = 1.0 - penalty

        # ── Phase 3e: MT5 orphan reconciliation ───────────────────────────
        self._reconcile_mt5_orphans()

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

    def flatten_positions(self, reason: str = "circuit_breaker") -> list[str]:
        """Close all open positions across all actors immediately.

        Called by the drawdown circuit breaker before setting emergency halt.
        Returns a list of asset names whose positions were closed.
        """
        from datetime import datetime, timezone

        flattened: list[str] = []
        now_iso = datetime.now(timezone.utc).isoformat()
        for name, actor in self._actors.items():
            engine = getattr(actor, "_engine", None)
            if engine is None:
                continue
            pos_mgr = getattr(engine, "pos_mgr", None)
            if pos_mgr is None or not pos_mgr.has_position():
                continue
            exit_price = getattr(engine, "current_price", None)
            if exit_price is None or exit_price <= 0:
                continue
            try:
                engine._close_position(exit_price=exit_price, exit_date=now_iso, reason=reason)
                flattened.append(name)
                logger.warning("%s: position closed by circuit breaker (%.4f)", name, exit_price)
            except Exception as e:
                logger.error("%s: circuit breaker flatten failed: %s", name, e)
        if flattened:
            logger.error(
                "CIRCUIT BREAKER FLATTEN: %d position(s) closed: %s",
                len(flattened),
                ", ".join(flattened),
            )
        return flattened

    def reset_emergency_halt(self) -> None:
        """Reset emergency halt (e.g., after manual review)."""
        self._emergency_halt = False
        for actor in self._actors.values():
            actor.reset()
        logger.warning("Emergency halt reset — all actors restored to GREEN")

    def _resolve_broker(self):
        """Get the MT5 broker from the first actor that has one."""
        for actor in self._actors.values():
            bridge = getattr(actor._engine, "execution_bridge", None)
            if bridge is not None and getattr(bridge, "_is_real_broker", False):
                return bridge.broker
        return None

    MAX_CLEANUP_RETRIES = 5

    def _reconcile_mt5_orphans(self) -> None:
        """Reconcile MT5 orphaned positions every cycle.

        Phase A — Drain cleanup queues (event-triggered from close failures).
        Phase B — Detect stale paper mt5_tickets (MT5-native SL/TP, manual close).
        """
        broker = self._resolve_broker()
        if broker is None:
            return

        # ── Phase A: Drain cleanup queues ──────────────────────────────────
        for name, actor in self._actors.items():
            engine = actor._engine
            db = engine.__dict__
            queue = db.get("_mt5_cleanup_queue")
            if queue is None:
                continue
            if not queue:
                continue
            retries = db.get("_mt5_cleanup_retries", 0)

            if retries >= self.MAX_CLEANUP_RETRIES:
                logger.error(
                    "MT5_ORPHAN abandoned after %d retries: %s queue=%s — manual MT5 cleanup required",
                    self.MAX_CLEANUP_RETRIES,
                    name,
                    queue,
                )
                # FIXME: add abandoned-orphan counter to diagnostics/metrics
                # FIXME: Phase C deferral — orphaned MT5 positions without any
                # paper-side record (e.g. after engine restart) need a separate
                # startup recovery pass. Tracked as follow-up.
                engine._mt5_cleanup_queue = []
                engine._mt5_cleanup_retries = 0
                continue

            still_pending: list[tuple[str, int]] = []
            for mt5_symbol, ticket in queue:
                try:
                    ok = broker.close_position(mt5_symbol, str(ticket))
                    if ok:
                        logger.warning(
                            "MT5_ORPHAN cleaned: %s ticket=%s on %s",
                            name,
                            ticket,
                            mt5_symbol,
                        )
                    else:
                        still_pending.append((mt5_symbol, ticket))
                        logger.warning(
                            "MT5_ORPHAN retry %d/%d: %s ticket=%s on %s",
                            retries + 1,
                            self.MAX_CLEANUP_RETRIES,
                            name,
                            ticket,
                            mt5_symbol,
                        )
                except Exception as e:
                    still_pending.append((mt5_symbol, ticket))
                    logger.error(
                        "MT5_ORPHAN exception on retry %d: %s ticket=%s on %s: %s",
                        retries + 1,
                        name,
                        ticket,
                        mt5_symbol,
                        e,
                    )

            engine._mt5_cleanup_queue = still_pending
            engine._mt5_cleanup_retries = retries + 1 if still_pending else 0

        # ── Phase B: Stale ticket detection ────────────────────────────────
        # Catches MT5-native SL/TP hits and manual closes where paper still
        # holds a stale mt5_ticket but the MT5 position no longer exists.
        if not broker.ensure_connected():
            return
        try:
            mt5_positions = broker.get_positions()
        except Exception:
            return

        mt5_by_ticket: dict[str, object] = {}
        for p in mt5_positions:
            if p.position_id:
                mt5_by_ticket[p.position_id] = p

        for name, actor in self._actors.items():
            engine = actor._engine
            if not engine.position:
                continue
            mt5_ticket = engine.position.get("mt5_ticket")
            if mt5_ticket is None:
                continue
            if str(mt5_ticket) not in mt5_by_ticket:
                logger.warning(
                    "MT5_STALE_TICKET: %s ticket=%s not found on broker — clearing from paper state",
                    name,
                    mt5_ticket,
                )
                engine.position.pop("mt5_ticket", None)

    def shutdown(self) -> None:
        """Shut down the persistent thread pool (called on exit via atexit)."""
        self._pool.shutdown(wait=False)
        logger.debug("EngineOrchestrator thread pool shut down")
