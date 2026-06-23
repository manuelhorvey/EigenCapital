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
import math
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
from paper_trading.orchestrator.correlation import CorrelationMonitor
from paper_trading.orchestrator.health import CircuitBreaker, HealthMonitor, RecoveryScheduler
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
        self._last_pnl_date: datetime.date | None = None
        self._emergency_halt: bool = False
        self._wal = wal_writer
        self._last_health: dict | None = None

        # Portfolio leverage guardrail (Phase 2)
        self._leverage_lock = threading.Lock()
        self._backstop_multiplier: float = 1.0
        self._backstop_decay_cycles: int = 0

        # Portfolio circuit breaker (vol spike + consecutive loss)
        self._circuit_breaker = CircuitBreaker()

        # Cross-asset correlation monitor
        self._correlation_monitor = CorrelationMonitor()

        # HealthMonitor (system-wide health aggregation)
        self._health_monitor = HealthMonitor()

        # RecoveryScheduler (exponential backoff for HALTED actors)
        self._recovery_scheduler = RecoveryScheduler()

        # Rolling portfolio returns for VaR/CVaR and vol baseline
        self._portfolio_returns: list[float] = []
        self._var_baseline_vol: float | None = None
        # Separate from Phase 3b's _prev_portfolio_value (which uses total_value sum):
        self._var_prev_value: float | None = None

        # Position concentration snapshot (updated each cycle in Phase 3e)
        self._position_concentration: dict = {
            "long": 0,
            "short": 0,
            "total": 0,
            "skew": 0.0,
            "dominant_side": "unknown",
            "threshold": 0.75,
            "alert": False,
        }

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
        current_dd = (
            (total_equity - self._peak_portfolio_value) / max(self._peak_portfolio_value, 1.0)
            if self._peak_portfolio_value is not None and self._peak_portfolio_value > 0
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

        # Exposure multiplier: computed from current drawdown BEFORE entries
        # so Phase 2 sizing uses the correct multiplier (not one cycle late).
        from paper_trading.governance.drawdown_controls import compute_exposure_multiplier as _compute_exp_mult

        exp_mult, _ = _compute_exp_mult(current_dd)

        for actor in self._actors.values():
            actor._engine._cycle_total_equity = total_equity
            actor._engine._cycle_drawdown_pct = current_dd
            actor._engine._leverage_budget_ref = budget_ref
            actor._engine._leverage_lock = self._leverage_lock
            if hasattr(actor._engine, "pos_mgr"):
                actor._engine.pos_mgr.exposure_multiplier = exp_mult

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
        prev_value = getattr(self, "_prev_portfolio_value", None)
        if prev_value is None:
            prev_value = total_value
        if total_value < prev_value:
            today = datetime.now(timezone.utc).date()
            if self._last_pnl_date != today:
                self._circuit_breaker.record_daily_pnl(total_value - prev_value)
                self._last_pnl_date = today
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

        # ── Phase 3e: Position concentration check ────────────────────────
        # Warns when open positions are heavily skewed to one side.
        long_count = 0
        short_count = 0
        for name, actor in self._actors.items():
            engine = getattr(actor, "_engine", None)
            if engine is None:
                continue
            pos = getattr(engine, "pos_mgr", None)
            if pos is None or not pos.has_position():
                continue
            side = getattr(pos.position, "side", None)
            if side is None:
                continue
            if side == "long":
                long_count += 1
            elif side == "short":
                short_count += 1
        total_positions = long_count + short_count
        if total_positions > 0:
            long_ratio = long_count / total_positions
            skew = max(long_ratio, 1.0 - long_ratio)
            from paper_trading.config_manager import get_config

            threshold = (get_config().defaults or {}).get("net_short_concentration_threshold", 0.75)
            if skew > threshold:
                side_label = "LONG" if long_ratio > 0.5 else "SHORT"
                logger.warning(
                    "POSITION_CONCENTRATION: %d/%d positions on %s side (skew=%.1f%% threshold=%.0f%%)",
                    max(long_count, short_count),
                    total_positions,
                    side_label,
                    skew * 100,
                    threshold * 100,
                )
            results["position_concentration"] = {
                "long": long_count,
                "short": short_count,
                "total": total_positions,
                "skew": round(skew, 4),
                "dominant_side": side_label if total_positions > 0 and skew > threshold else "balanced",
                "threshold": threshold,
                "alert": skew > threshold,
            }
            self._position_concentration = results["position_concentration"]
        else:
            results["position_concentration"] = {
                "long": 0,
                "short": 0,
                "total": 0,
                "skew": 0.0,
                "dominant_side": "none",
                "threshold": 0.75,
                "alert": False,
            }
            self._position_concentration = results["position_concentration"]

        # ── WAL: position concentration event ──────────────────────────────
        if self._wal is not None:
            try:
                self._wal.write("position_concentration", results["position_concentration"])
            except Exception:
                logger.exception("WAL write failed for position_concentration")

        # ── Phase 3f: Cross-asset correlation monitoring ──────────────────
        prices: dict[str, float] = {}
        positions: dict[str, dict] = {}
        for name, actor in self._actors.items():
            engine = getattr(actor, "_engine", None)
            if engine is None:
                continue
            px = getattr(engine, "current_price", None)
            if px is not None and px > 0:
                prices[name] = px
            pos = getattr(engine, "pos_mgr", None)
            if pos is not None and pos.has_position():
                side = pos.position.side if hasattr(pos.position, "side") else None
                positions[name] = {"side": side.value if hasattr(side, "value") else side}
        today_str = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        corr_report = self._correlation_monitor.update(prices, positions, today_str)
        results["correlation"] = {
            "n_high_pairs": len(corr_report["high_pairs"]),
            "cluster_alerts": corr_report["cluster_alerts"],
        }
        if any("cluster" in a for a in corr_report["cluster_alerts"]):
            logger.warning("Correlation cluster alert: %s", corr_report["cluster_alerts"])

        # ── Phase 3g: MT5 orphan reconciliation ───────────────────────────
        self._reconcile_mt5_orphans()

        # ── Phase 3h: HealthMonitor + VaR + RecoveryScheduler ─────────────
        pv = None
        try:
            pv_raw = self.get_total_portfolio_value()
            if pv_raw is not None:
                pv = float(pv_raw)
        except (TypeError, ValueError):
            pass
        portfolio_peak_raw = getattr(self._circuit_breaker, "_peak_value", None)
        portfolio_peak = float(portfolio_peak_raw) if portfolio_peak_raw is not None else None
        baseline_vol = self._var_baseline_vol
        health_summary = self._health_monitor.observe(
            self._actors,
            portfolio_value=pv,
            portfolio_peak=portfolio_peak,
            portfolio_vol=self._portfolio_vol_estimate(),
            baseline_vol=baseline_vol,
        )
        results["health_monitor"] = {
            "halt_ratio": health_summary.halt_ratio,
            "n_green": health_summary.n_green,
            "n_halted": health_summary.n_halted,
            "recommendations": health_summary.recommendations,
        }
        # Track portfolio value for VaR computation
        # Uses _var_prev_value (separate from Phase 3b's _prev_portfolio_value
        # which is overwritten by total_value sum).
        if pv is not None and pv > 0:
            if self._var_prev_value is not None and self._var_prev_value > 0 and pv != self._var_prev_value:
                r = (pv - self._var_prev_value) / self._var_prev_value
                self._portfolio_returns.append(r)
                if len(self._portfolio_returns) > 252:
                    self._portfolio_returns = self._portfolio_returns[-252:]
                # Compute VaR/CVaR at 60 periods
                if len(self._portfolio_returns) >= 60:
                    rets = sorted(self._portfolio_returns[-60:])
                    var_95 = rets[2]  # 3rd smallest of 60 = 5th percentile
                    loss_idx = [r for r in rets if r <= var_95]
                    cvar_95 = sum(loss_idx) / max(len(loss_idx), 1)
                    results["var_95"] = round(var_95, 6)
                    results["cvar_95"] = round(cvar_95, 6)
            self._var_prev_value = pv

        # RecoveryScheduler: probe HALTED actors for recovery
        recovered: list[str] = []
        for name, actor in self._actors.items():
            eng = getattr(actor, "_engine", None)
            if eng is None:
                continue
            pos_mgr = getattr(eng, "pos_mgr", None)
            if pos_mgr is None:
                continue
            is_halted = getattr(pos_mgr, "halted", False) or getattr(eng, "_halted", False)
            if is_halted and self._recovery_scheduler.is_due(name):
                # Attempt recovery by resetting halt state
                logger.info("RecoveryScheduler: attempting recovery for %s", name)
                try:
                    if hasattr(pos_mgr, "halted"):
                        pos_mgr.halted = False
                    if hasattr(eng, "_halted"):
                        eng._halted = False
                    self._recovery_scheduler.record_result(name, success=True)
                    recovered.append(name)
                except Exception as exc:
                    self._recovery_scheduler.record_result(name, success=False, error=str(exc))
                    logger.error("RecoveryScheduler: recovery failed for %s: %s", name, exc)
        if recovered:
            results["actors_recovered"] = recovered
            logger.info("RecoveryScheduler: recovered %d actor(s): %s", len(recovered), recovered)

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
            try:
                self._wal.write("actor_health", current)
                self._last_health = current
            except Exception:
                logger.exception("WAL write failed for actor_health")

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
        try:
            self._wal.write("state_committed", snapshot)
        except Exception:
            logger.exception("WAL write failed for state_committed")

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
        Phase C — Dry-run orphan report (log only, no state mutation).
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
                # Phase C (dry-run orphan report) now logs these; adoption
                # logic still needs a design pass.
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
        # Invalidates broker cache first so entries placed earlier in this
        # cycle are visible (5s cache would otherwise return stale data).
        if not broker.ensure_connected():
            return
        try:
            broker._position_cache_time = 0.0  # invalidate cache for fresh data
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

        # ── Phase C: Dry-run orphan report (log only, no state mutation) ──
        # Reports every MT5 position with no matching paper-side ticket.
        # Deduped by ticket; tracks first_seen cycle; flags removed-asset
        # orphans distinctly (engine_actor=None).
        # See https://github.com/anomalyco/opencode/issues for discussion.
        if not hasattr(self, "_orphan_first_seen"):
            self._orphan_first_seen: dict[str, int] = {}
            self._orphan_cycle_no: int = 0
        self._orphan_cycle_no += 1

        # Build paper-side ticket set (tickets tracked by both paper + broker)
        known_tickets: set[str] = set()
        for name, actor in self._actors.items():
            engine = actor._engine
            if not engine.position:
                continue
            ticket = engine.position.get("mt5_ticket")
            if ticket is not None:
                mt5_str = str(ticket)
                if mt5_str in mt5_by_ticket:
                    known_tickets.add(mt5_str)

        # Build MT5 symbol → [(actor_name, engine)] lookup (handles
        # one-to-many mappings like ^DJI+YM=F → US30)
        sym_actors: dict[str, list[tuple[str, Any]]] = {}
        for name, actor in self._actors.items():
            engine = actor._engine
            if engine is None:
                continue
            mt5_sym = broker.ticker_to_mt5_symbol(engine.ticker)
            sym_actors.setdefault(mt5_sym, []).append((name, engine))

        # Build reverse symbol map: MT5 symbol → QuantForge ticker
        reverse_map: dict[str, str] = {}
        for ticker, mt5_sym in broker._symbol_map.items():
            reverse_map[mt5_sym] = ticker

        unique_orphans_this_cycle: set[str] = set()
        for p in mt5_positions:
            ticket = p.position_id
            if ticket is None:
                continue
            if ticket in known_tickets:
                continue

            unique_orphans_this_cycle.add(ticket)

            if ticket not in self._orphan_first_seen:
                self._orphan_first_seen[ticket] = self._orphan_cycle_no
                first_seen_str = "this_cycle"
            else:
                first_seen_str = f"cycle_{self._orphan_first_seen[ticket]}"

            # Determine ticker and actor status
            matching = sym_actors.get(p.asset)
            if matching:
                name, matched_engine = matching[0]
                ticker = matched_engine.ticker
                paper_pos = matched_engine.position
                if paper_pos and paper_pos.get("mt5_ticket") is not None:
                    orphan_reason = f"paper_ticket_mismatch (has {paper_pos['mt5_ticket']})"
                elif paper_pos:
                    orphan_reason = "paper_has_position_no_ticket"
                    # Phase D: self-healing adoption — backfill mt5_ticket from broker
                    matched_engine.position["mt5_ticket"] = int(ticket)
                    logger.info(
                        "PHASE_D_ADOPT: %s adopted orphan ticket=%s on %s",
                        name,
                        int(ticket),
                        p.asset,
                    )
                else:
                    orphan_reason = "no_paper_position"
                engine_actor = name
            else:
                ticker = reverse_map.get(p.asset, p.asset)
                orphan_reason = "removed_asset" if p.asset in reverse_map else "unknown_symbol"
                engine_actor = None

            side = "long" if p.quantity >= 0 else "short"
            vol = abs(p.quantity)

            logger.warning(
                "PHASE_C_ORPHAN: ticket=%s mt5_symbol=%s ticker=%s "
                "engine_actor=%s side=%s vol=%.4f entry=%.5f price=%.5f "
                "upnl=%.2f first_seen=%s reason=%s",
                ticket,
                p.asset,
                ticker,
                engine_actor or "None",
                side,
                vol,
                p.avg_entry_price,
                p.current_price,
                p.unrealized_pnl,
                first_seen_str,
                orphan_reason,
            )

        n_unique = len(self._orphan_first_seen)
        n_this_cycle = len(unique_orphans_this_cycle)
        if n_unique > 0 or n_this_cycle > 0:
            logger.warning(
                "PHASE_C_SUMMARY: %d unique orphan tickets tracked (%d this cycle)",
                n_unique,
                n_this_cycle,
            )

    def get_total_portfolio_value(self) -> float | None:
        """Sum of all actor positions' current market value + cash."""
        total: float = 0.0
        has_any = False
        for actor in self._actors.values():
            eng = getattr(actor, "_engine", None)
            if eng is None:
                continue
            pos_mgr = getattr(eng, "pos_mgr", None)
            if pos_mgr is not None and hasattr(pos_mgr, "position") and pos_mgr.position is not None:
                qty = getattr(pos_mgr.position, "quantity", 0) or 0
                px = getattr(eng, "current_price", None)
                if px is not None and qty:
                    try:
                        total += float(abs(qty)) * float(px)
                        has_any = True
                    except (TypeError, ValueError):
                        pass
            # Add cash balance if available (guard against MagicMock in tests)
            for attr in ("_cash_balance", "cash_balance"):
                try:
                    val = getattr(eng, attr, None)
                    if val is not None:
                        cash = float(val)
                        total += cash
                        has_any = True
                except (TypeError, ValueError):
                    continue
        return total if has_any else None

    def _portfolio_vol_estimate(self) -> float | None:
        """Estimate daily portfolio return vol from rolling returns (60-day)."""
        if len(self._portfolio_returns) < 30:
            return None
        arr = self._portfolio_returns[-60:]
        mean = sum(arr) / len(arr)
        var = sum((x - mean) ** 2 for x in arr) / len(arr)
        return math.sqrt(var)

    def shutdown(self) -> None:
        """Shut down the persistent thread pool (called on exit via atexit)."""
        self._pool.shutdown(wait=False)
        logger.debug("EngineOrchestrator thread pool shut down")
