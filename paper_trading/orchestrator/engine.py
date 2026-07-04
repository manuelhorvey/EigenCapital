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
import contextlib
import logging
import math
import os
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime
from typing import Any

from eigencapital.domain.time import utc_now, utc_now_iso
from paper_trading.alerting.manager import global_alert_manager
from paper_trading.config_manager import get_config
from paper_trading.governance.drawdown_controls import check_drawdown_circuit_breaker, compute_exposure_multiplier
from paper_trading.logging.correlation import set_correlation_id
from paper_trading.orchestrator.actor import (
    AssetActor,
    AssetResult,
    compute_health_snapshot,
)
from paper_trading.orchestrator.admission import AdmissionSignal, PortfolioAdmissionController
from paper_trading.orchestrator.admission.signal import PositionSide
from paper_trading.orchestrator.correlation import CorrelationMonitor
from paper_trading.orchestrator.health import CircuitBreaker, HaltReason, HealthMonitor, RecoveryScheduler
from paper_trading.pek.contracts.performance_state import PerformanceState
from paper_trading.pek.contracts.portfolio_state import PortfolioStateSnapshot
from paper_trading.pek.contracts.risk_budget import RiskBudget
from paper_trading.pek.engine_v2 import RiskEngineV2
from paper_trading.pek.perf.performance_state_builder import PerformanceStateBuilder
from paper_trading.pek.state.portfolio_state_builder import PortfolioStateBuilder
from paper_trading.replay.wal import WalWriter
from paper_trading.state_store import EngineSnapshot
from shared.calibration import CalibrationRegistry

logger = logging.getLogger("eigencapital.orchestrator.engine")

# Drawdown recovery threshold for automatic unhalt (must be above trip threshold to avoid flapping).
# Named separate constant — must NOT be derived from the drawdown_limit passed to
# check_drawdown_circuit_breaker so that the hysteresis gap is explicit.
DRAWDOWN_AUTO_UNHALT_THRESHOLD = -0.05  # -5% — recover above this to be eligible
DRAWDOWN_AUTO_UNHALT_MIN_CYCLES = 10  # must show recovery for N consecutive cycles

# Reasons that are eligible for automatic unhalt when drawdown recovers.
# halt_ratio and vol_spike require manual EngineOrchestrator.reset_emergency_halt().
HALT_REASON_AUTO_UNHALT_ALLOWED: frozenset[HaltReason] = frozenset(
    {
        HaltReason.DRAWDOWN,
        HaltReason.CONSECUTIVE_LOSSES,
    }
)


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
        snapshot: EngineSnapshot | None = None,
    ):
        self._actors = actors
        self._max_halt_ratio = max_halt_ratio
        self._max_workers = max_workers or len(actors) * 2
        self._persist_buffer: list[dict] = []
        self._peak_portfolio_value: float | None = None
        self._last_pnl_date: datetime.date | None = None
        self._emergency_halt: bool = False
        self._halt_reason: HaltReason | None = None
        self._halt_detail: str = ""
        self._unhalt_recovery_cycles: int = 0
        self._cycles_elapsed: int = 0
        self._wal = wal_writer
        self._last_health: dict | None = None
        # Throttle counter for the halt-persistent warning log so a stuck
        # emergency halt doesn't spam engine.log every cycle. Emits on cycles
        # 1, 11, 21, … while a halt is active.
        self._halt_warn_last_cycle: int = -10

        # PEK state — built in pre-phase, consumed by admission
        self._portfolio_snapshot: PortfolioStateSnapshot | None = None
        self._risk_budget: RiskBudget | None = None
        self._performance_state: PerformanceState | None = None

        # Last cycle's admission results (stored for state.json export)
        self._last_admission: dict | None = None

        # PEK admission controller (lazy init)
        self._pek: PortfolioAdmissionController | None = None

        # Performance state builder — records trade outcomes each cycle
        self._perf_builder = PerformanceStateBuilder()
        # Wire CalibrationRegistry so calibration_ece reflects portfolio fit
        # quality rather than the legacy silent-zero path. get_or_load is
        # idempotent — every AssetEngine already populates this same singleton.
        _cal_dir = os.path.join(os.path.dirname(os.path.dirname(__file__)), "models", "calibration")
        self._perf_builder.set_calibration_registry(CalibrationRegistry.get_or_load(_cal_dir))

        # Portfolio circuit breaker (vol spike + consecutive loss)
        self._circuit_breaker = CircuitBreaker()

        # Restore emergency halt state from snapshot (if any)
        if snapshot is not None and snapshot.emergency_halt:
            self._emergency_halt = True
            if snapshot.halt_reason:
                try:
                    self._halt_reason = HaltReason(snapshot.halt_reason)
                except ValueError:
                    self._halt_reason = None
            self._halt_detail = snapshot.halt_detail
            if snapshot.peak_portfolio_value is not None:
                self._peak_portfolio_value = snapshot.peak_portfolio_value
            self._circuit_breaker.restore_state(
                snapshot.peak_portfolio_value,
                snapshot.breaker_daily_pnl,
            )
            logger.warning(
                "EngineOrchestrator: restored emergency halt from snapshot (reason=%s detail=%s peak=%.2f)",
                snapshot.halt_reason,
                snapshot.halt_detail,
                snapshot.peak_portfolio_value or 0.0,
            )

        # Re-anchor peak against live equity: the persisted peak from a prior
        # session may be stale (e.g. different capital base, intentional capital
        # reset).  Setting peak < current equity would create a false drawdown
        # at startup that blocks auto-unhalt.  Ensure peak ≥ current equity.
        _init_equity = sum(a._engine.mtm_value for a in self._actors.values() if hasattr(a._engine, "mtm_value"))
        if (
            _init_equity is not None
            and _init_equity > 0
            and (self._peak_portfolio_value is None or _init_equity > self._peak_portfolio_value)
        ):
            self._peak_portfolio_value = _init_equity

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

        # MT5 orphan cleanup tracking
        self._abandoned_orphans: int = 0
        self._stale_ticket_cycles: dict[str, int] = {}

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

    def _filtered_actors(self, allowed_assets: set[str] | None = None) -> dict[str, Any]:
        """Return filtered actor dict if allowed_assets is set, else all actors."""
        if allowed_assets is None:
            return self._actors
        return {n: a for n, a in self._actors.items() if n in allowed_assets}

    def run_once(self, market_data: dict | None = None, allowed_assets: set[str] | None = None) -> dict[str, Any]:
        """Execute one orchestrator cycle.  Returns phased results dict.

        Phases:
            PRE    — PortfolioStateSnapshot + RiskBudget + PerformanceState
            1a. REFRESH  — parallel actor cycles (price + PnL + signal)
            1b. ADMIT    — PEK admission review (observability + budget check)
            2. VALIDITY — parallel validity updates
            3. PORTFOLIO — aggregate health, circuit breakers, VaR, recovery
            4. PERSIST  — flush all persist queues to WAL

        When ``allowed_assets`` is provided (a set of asset names), only those
        actors participate in each phase. All other actors are skipped for the
        cycle. Used for weekend cycles where only weekend-eligible assets run.

        Returns a dict with keys for each phase plus aggregated health.
        """
        # Temporary actor subset for weekend cycles — all phase methods
        # use self._actors, so we swap it for the cycle duration.
        _saved_actors = self._actors
        self._actors = self._filtered_actors(allowed_assets)
        try:
            return self._run_phases(market_data)
        finally:
            self._actors = _saved_actors

    def _run_phases(self, market_data: dict | None = None) -> dict[str, Any]:
        """Execute the standard 4-phase cycle on self._actors (which may be filtered)."""
        results: dict[str, Any] = {
            "phasetimestamps": {},
            "assets": {},
            "circuit_breaker": None,
            "health": None,
        }

        set_correlation_id()

        if self._emergency_halt:
            self._maybe_warn_halt_persistent()
            self._check_auto_unhalt_eligibility()
            if self._emergency_halt:
                results["circuit_breaker"] = {"triggered": True, "reason": "emergency_halt_persistent"}
                return results

        t0 = time.monotonic()

        # ── Pre-phase ────────────────────────────────────────────────────
        defaults, max_leverage, budget_ref = self._pre_phase_pek()

        # ── Phase 1a: Signal generation ──────────────────────────────────
        self._phase_1_refresh_signal(market_data, results)

        # ── Phase 1b: PEK admission review ───────────────────────────────
        self._phase_1b_admission_review(results, defaults, max_leverage, budget_ref)

        # ── Phase 2 ──────────────────────────────────────────────────────
        self._phase_2_validity(results)

        # ── Phase 3 ──────────────────────────────────────────────────────
        halted = self._phase_3_portfolio_health(results, defaults, max_leverage)
        if halted:
            return results

        # ── Phase 4 ──────────────────────────────────────────────────────
        self._phase_4_persist(results)

        results["cycle_duration_ms"] = round((time.monotonic() - t0) * 1000.0, 2)
        return results

    # ── Phase helpers ───────────────────────────────────────────────────────────

    def _pre_phase_pek(self) -> tuple[dict, float, list]:
        """Build PEK state: PortfolioStateSnapshot, PerformanceState, RiskBudget.

        Distributes cycle equity/drawdown to actors (no longer distributes
        leverage_budget_ref — that is now managed by the PEK).

        Returns (defaults, max_leverage, dummy_budget_ref) — keeping the
        same return signature as the old _pre_phase_equity_snapshot for
        backward compat with Phase 3 helpers.
        """
        defaults = get_config().defaults or {}
        max_leverage = defaults.get("portfolio_max_leverage", 2.0)
        total_equity = sum(a._engine.mtm_value for a in self._actors.values() if hasattr(a._engine, "mtm_value"))
        self._cycle_total_equity = total_equity
        current_dd = (
            (total_equity - self._peak_portfolio_value) / max(self._peak_portfolio_value, 1.0)
            if self._peak_portfolio_value is not None and self._peak_portfolio_value > 0
            else 0.0
        )
        self._cycles_elapsed += 1

        # Build portfolio state snapshot from live actors
        daily_pnl = 0.0
        if self._var_prev_value is not None:
            current_value = sum(
                getattr(a._engine, "mtm_value", 0.0) for a in self._actors.values() if hasattr(a._engine, "mtm_value")
            )
            daily_pnl = (current_value - self._var_prev_value) if self._var_prev_value > 0 else 0.0
        self._portfolio_snapshot = PortfolioStateBuilder(
            mode_config=get_config().defaults or {},
        ).build(
            engine=self,
            cycle_count=self._cycles_elapsed,
            daily_pnl=daily_pnl,
            peak_value=self._peak_portfolio_value or total_equity,
        )

        # Build performance state from recorded outcomes
        self._performance_state = self._perf_builder.build(
            portfolio_value=total_equity,
        )

        # Compute adaptive risk budget
        if self._portfolio_snapshot is not None and self._performance_state is not None:
            risk_engine = RiskEngineV2(
                mode_config=get_config().defaults or {},
            )
            self._risk_budget = risk_engine.compute_budget(
                portfolio=self._portfolio_snapshot,
                perf=self._performance_state,
            )
        else:
            self._risk_budget = RiskBudget()

        # Lazy-init PEK admission controller
        if self._pek is None:
            self._pek = PortfolioAdmissionController(
                mode_config=get_config().defaults or {},
            )

        # Distribute cycle values to actors (no leverage_budget_ref)
        exp_mult, _ = compute_exposure_multiplier(current_dd)
        for actor in self._actors.values():
            actor._engine._cycle_total_equity = total_equity
            actor._engine._cycle_drawdown_pct = current_dd
            if hasattr(actor._engine, "pos_mgr"):
                actor._engine.pos_mgr.exposure_multiplier = exp_mult

        # Dummy budget_ref for backward compat with any remaining callers
        budget_ref = [max_leverage * total_equity]
        return defaults, max_leverage, budget_ref

    def _phase_1_refresh_signal(self, market_data: dict | None, results: dict) -> None:
        """Parallel actor refresh + signal generation (Phase 1)."""
        results["phasetimestamps"][EnginePhase.REFRESH] = utc_now_iso()
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

    def _phase_1b_admission_review(self, results: dict, defaults: dict, max_leverage: float, budget_ref: list) -> None:
        """PEK admission review — observe and enforce budget after signal gen.

        Collects intents from Phase 1a signals, runs PEK admission (observability),
        and if budget is exceeded, closes lowest-ranked positions immediately.
        """
        if self._pek is None or self._portfolio_snapshot is None:
            return

        # Collect trade intents from actor results
        intents: list[AdmissionSignal] = []
        rejection_reasons: dict[str, str] = {}
        for name, actor in self._actors.items():
            signal = results.get("assets", {}).get(name)
            if signal is None or not isinstance(signal, dict) or "error" in signal:
                continue

            side_str = signal.get("side")
            if side_str is None or side_str == "none":
                continue

            try:
                pos_side = PositionSide(side_str)
            except ValueError:
                rejection_reasons[name] = f"unknown_side:{side_str}"
                continue

            prob_long = signal.get("prob_long", 0.5)
            prob_short = signal.get("prob_short", 0.5)
            calibrated_prob = signal.get("calibrated_prob", max(prob_long, prob_short))
            entry_price = signal.get("close_price", 0.0)
            position_size = signal.get("position_size", 0.0)

            # Compute stop-loss and take-profit from existing position if available
            engine = getattr(actor, "_engine", None)
            pos_mgr = getattr(engine, "pos_mgr", None) if engine else None
            stop_loss = 0.0
            take_profit = 0.0
            if pos_mgr and pos_mgr.has_position():
                pos = getattr(pos_mgr, "position", None)
                if pos:
                    stop_loss = getattr(pos, "stop_loss", 0.0) or 0.0
                    take_profit = getattr(pos, "take_profit", 0.0) or 0.0

            sl_distance_pct = abs(entry_price - stop_loss) / max(entry_price, 0.0001) if stop_loss > 0 else 0.0
            tp_distance_pct = abs(take_profit - entry_price) / max(entry_price, 0.0001) if take_profit > 0 else 0.0
            notional_requested = position_size * entry_price if entry_price > 0 else 0.0
            risk_usd = notional_requested * sl_distance_pct
            tp_sl_ratio = tp_distance_pct / max(sl_distance_pct, 0.0001) if sl_distance_pct > 0 else 0.0

            # Regime confidence from asset's last regime row
            regime_confidence = 0.5
            if engine:
                last_regime = getattr(engine, "_last_regime_row", None)
                if last_regime:
                    regime_confidence = getattr(last_regime, "P_trend", 0.5)

            intent = AdmissionSignal(
                asset=name,
                side=pos_side,
                entry_price=entry_price,
                stop_loss=stop_loss,
                take_profit=take_profit,
                sl_distance_pct=sl_distance_pct,
                tp_distance_pct=tp_distance_pct,
                notional_requested=notional_requested,
                risk_usd=risk_usd,
                calibrated_prob=calibrated_prob,
                expected_value_r=0.0,
                tp_sl_ratio=tp_sl_ratio,
                regime_confidence=regime_confidence,
                feature_hash=signal.get("feature_hash", ""),
            )
            intents.append(intent)

        # Run PEK admission
        result = self._pek.run_admission(
            candidates=intents,
            snapshot=self._portfolio_snapshot,
            risk_budget=self._risk_budget,
        )
        admitted = result.admitted if result else []
        rejected_list = result.rejected if result else []

        # Build rejection reason dict: merge pre-PEK rejections (side errors) with PEK rejections
        for sig, reason in rejected_list:
            rejection_reasons[sig.asset] = reason
        rejected_assets = list(rejection_reasons.keys())

        # Budget enforcement: if actual notional > budget × tolerance, close
        # lowest-ranked admitted positions until within budget.
        if self._risk_budget is not None and budget_ref:
            max_notional = budget_ref[0] * (1.0 + defaults.get("portfolio_leverage_tolerance", 0.001))
            current_notional = sum(
                getattr(actor._engine, "_last_entry_notional", 0.0) for actor in self._actors.values()
            )
            if current_notional > max_notional:
                logger.warning(
                    "PEK_BUDGET_OVERRUN: notional=%.2f max=%.2f over=%.2f%% — reviewing %d admitted",
                    current_notional,
                    max_notional,
                    (current_notional / max_notional - 1) * 100,
                    len(admitted),
                )
                # Sort admitted by score ascending (worst first) and close until within budget
                closed_names: list[str] = []
                for sig in sorted(admitted, key=lambda s: s.peking_score or 0.0):
                    if current_notional <= max_notional:
                        break
                    actor = self._actors.get(sig.asset)
                    if actor is None:
                        continue
                    engine = getattr(actor, "_engine", None)
                    if engine is None:
                        continue
                    pos_mgr = getattr(engine, "pos_mgr", None)
                    if pos_mgr is None or not pos_mgr.has_position():
                        continue
                    entry_notional = getattr(engine, "_last_entry_notional", 0.0)
                    try:
                        exit_price = getattr(engine, "current_price", None)
                        if exit_price is not None and exit_price > 0:
                            engine._close_position(exit_price, utc_now(), "PEK_BUDGET_OVERRUN")
                            current_notional -= entry_notional
                            closed_names.append(sig.asset)
                            logger.warning(
                                "PEK_BUDGET_CLOSE: %s closed (score=%.4f) — freed %.2f notional",
                                sig.asset,
                                sig.peking_score or 0.0,
                                entry_notional,
                            )
                    except (ValueError, TypeError, RuntimeError) as exc:
                        logger.error("PEK_BUDGET_CLOSE failed for %s: %s", sig.asset, exc)

                if closed_names:
                    with contextlib.suppress(Exception):
                        global_alert_manager().warning(
                            "PEK budget overrun — positions closed",
                            f"Closed {len(closed_names)} lowest-ranked positions: {closed_names}",
                            details={
                                "current_notional": round(current_notional, 2),
                                "max_notional": round(max_notional, 2),
                                "closed": closed_names,
                            },
                        )

        adm = {
            "n_intents": len(intents),
            "n_admitted": len(admitted),
            "n_rejected": len(rejected_assets),
            "budget_notional": budget_ref[0] if budget_ref else 0.0,
            "admitted": [s.asset for s in admitted],
            "rejected": rejected_assets,
            "rejection_reasons": rejection_reasons,
            "ranking_scores": getattr(result, "ranking_scores", {}),
        }
        results["admission"] = adm
        self._last_admission = adm

    def _phase_2_validity(self, results: dict) -> None:
        """Parallel validity updates (Phase 2)."""
        results["phasetimestamps"][EnginePhase.VALIDITY] = utc_now_iso()

        def _run_validity(name: str, actor: AssetActor) -> str | None:
            if actor.health == actor.health.HALTED:
                return None
            try:
                actor._engine.update_validity()
                return None
            except Exception as e:
                return f"{name}: {e}"

        validity_futures = {self._pool.submit(_run_validity, n, a): n for n, a in self._actors.items()}
        for future in as_completed(validity_futures):
            err = future.result()
            if err is not None:
                logger.warning("%s validity update failed: %s", err.split(":")[0], err)

    def _phase_3_portfolio_health(self, results: dict, defaults: dict, max_leverage: float) -> bool:
        """Aggregate health, circuit breakers, position concentration,
        correlation, VaR, and recovery scheduling (Phase 3).

        Returns True if a circuit breaker halted the engine (results dict
        already populated with the halt reason).
        """
        results["phasetimestamps"][EnginePhase.PORTFOLIO] = utc_now_iso()
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

        # ── Compute total value (shared by several sub-phases) ───────────
        total_value = sum(
            actor._engine.current_value for actor in self._actors.values() if hasattr(actor._engine, "current_value")
        )

        # ── 3a: Drawdown circuit breaker ─────────────────────────────────
        if self._peak_portfolio_value is None:
            self._peak_portfolio_value = total_value
        self._peak_portfolio_value = max(self._peak_portfolio_value, total_value)
        dd_result = check_drawdown_circuit_breaker(total_value, self._peak_portfolio_value, drawdown_limit=-0.15)
        results["drawdown"] = dd_result
        if dd_result["halted"]:
            logger.error(
                "DRAWDOWN CIRCUIT BREAKER TRIGGERED: dd=%.2f%% \u2014 flattening and halting all actors",
                dd_result["drawdown"] * 100,
            )
            self.flatten_positions(reason="drawdown_circuit_breaker")
            for actor in self._actors.values():
                if hasattr(actor._engine, "pos_mgr"):
                    actor._engine.pos_mgr.exposure_multiplier = 0.0
            self._emergency_halt = True
            self._halt_reason = HaltReason.DRAWDOWN
            self._halt_detail = f"dd={dd_result['drawdown']:.4f}"
            results["circuit_breaker"] = {"triggered": True, "reason": f"drawdown_{dd_result['drawdown']:.4f}"}
            return True

        # ── 3b: Halt ratio circuit breaker ────────────────────────────────
        if not health.is_system_healthy:
            logger.error(
                "PORTFOLIO CIRCUIT BREAKER: halt_ratio=%.2f exceeds max=%.2f \u2014 initiating emergency shutdown",
                health.halt_ratio,
                self._max_halt_ratio,
            )
            self._emergency_halt = True
            self._halt_reason = HaltReason.HALT_RATIO
            self._halt_detail = f"halt_ratio={health.halt_ratio:.4f}"
            with contextlib.suppress(Exception):
                global_alert_manager().critical(
                    "Portfolio halted — halt ratio exceeded",
                    f"halt_ratio={health.halt_ratio:.4f}/{self._max_halt_ratio:.4f}",
                    details={"halt_ratio": health.halt_ratio, "threshold": self._max_halt_ratio},
                )
            results["circuit_breaker"] = {
                "triggered": True,
                "halt_ratio": health.halt_ratio,
                "threshold": self._max_halt_ratio,
            }
            return True

        # ── 3c: Vol spike + consecutive losses breaker ────────────────────
        prev_value = getattr(self, "_prev_portfolio_value", None)
        if prev_value is None:
            prev_value = total_value
        if total_value < prev_value:
            today = utc_now().date()
            if self._last_pnl_date != today:
                self._circuit_breaker.record_daily_pnl(total_value - prev_value)
                self._last_pnl_date = today
        self._prev_portfolio_value = total_value

        breaker_result = self._circuit_breaker.check(portfolio_value=total_value, actors=self._actors)
        results["circuit_breaker_full"] = {
            "trip": breaker_result.trip,
            "reason": breaker_result.reason,
            "severity": breaker_result.severity,
        }
        if breaker_result.trip:
            self._emergency_halt = True
            self._halt_reason = (
                HaltReason.VOL_SPIKE if "vol_spike" in breaker_result.reason else HaltReason.CONSECUTIVE_LOSSES
            )
            self._halt_detail = breaker_result.reason
            logger.error(
                "VOLATILITY CIRCUIT BREAKER TRIGGERED: %s \u2014 flattening and halting",
                breaker_result.reason,
            )
            with contextlib.suppress(Exception):
                global_alert_manager().critical(
                    f"Portfolio halted — {breaker_result.reason}",
                    "Volatility circuit breaker triggered — flattening all positions",
                    details={"reason": breaker_result.reason, "severity": breaker_result.severity},
                )
            self.flatten_positions(reason=f"circuit_breaker_{breaker_result.reason}")
            results["circuit_breaker"] = {"triggered": True, "reason": breaker_result.reason}
            return True

        # ── 3d: Leverage anomaly detector (observability only) ────────────
        # Backstop no longer takes corrective action — that is handled by
        # the PEK in Phase 1b. This sub-phase only logs anomalies for
        # post-hoc analysis and dashboard observability.
        total_entered = sum(getattr(actor._engine, "_last_entry_notional", 0.0) for actor in self._actors.values())
        tolerance = defaults.get("portfolio_leverage_tolerance", 0.001)
        fair_budget = max_leverage * self._cycle_total_equity
        anomaly_detected = total_entered > fair_budget * (1.0 + tolerance)
        if anomaly_detected:
            logger.warning(
                "BACKSTOP_ANOMALY: entered=%.2f budget=%.2f overshoot=%.2f%% — PEK should have prevented",
                total_entered,
                fair_budget,
                (total_entered / fair_budget - 1) * 100,
            )
        results["backstop"] = {
            "total_entered": round(total_entered, 2),
            "fair_budget": round(fair_budget, 2),
            "anomaly": anomaly_detected,
        }

        # ── 3e: Position concentration check ─────────────────────────────
        conc = self._compute_position_concentration()
        results["position_concentration"] = conc
        self._position_concentration = conc
        if self._wal is not None:
            try:
                self._wal.write("position_concentration", conc)
            except Exception:
                logger.exception("WAL write failed for position_concentration")

        # ── 3f: Cross-asset correlation ───────────────────────────────────
        corr = self._compute_cross_asset_correlation()
        results["correlation"] = corr

        # ── 3g: MT5 orphan reconciliation ────────────────────────────────
        self._reconcile_mt5_orphans()

        # ── 3h: HealthMonitor + VaR + RecoveryScheduler ──────────────────
        self._phase_3h_health_var_recovery(results)

        return False

    def _compute_position_concentration(self) -> dict:
        """Count open positions per side and compute skew ratio."""
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
        total = long_count + short_count
        if total == 0:
            return {
                "long": 0,
                "short": 0,
                "total": 0,
                "skew": 0.0,
                "dominant_side": "none",
                "threshold": 0.75,
                "alert": False,
            }
        long_ratio = long_count / total
        skew = max(long_ratio, 1.0 - long_ratio)
        threshold = (get_config().defaults or {}).get("net_short_concentration_threshold", 0.75)
        side_label = "LONG" if long_ratio > 0.5 else "SHORT"
        if skew > threshold:
            logger.warning(
                "POSITION_CONCENTRATION: %d/%d positions on %s side (skew=%.1f%% threshold=%.0f%%)",
                max(long_count, short_count),
                total,
                side_label,
                skew * 100,
                threshold * 100,
            )
            with contextlib.suppress(Exception):
                global_alert_manager().warning(
                    "Position concentration alert",
                    f"{max(long_count, short_count)}/{total} on {side_label} side",
                    details={
                        "long": long_count,
                        "short": short_count,
                        "skew": round(skew, 4),
                        "threshold": threshold,
                    },
                )
        return {
            "long": long_count,
            "short": short_count,
            "total": total,
            "skew": round(skew, 4),
            "dominant_side": side_label if skew > threshold else "balanced",
            "threshold": threshold,
            "alert": skew > threshold,
        }

    def _compute_cross_asset_correlation(self) -> dict:
        """Build price/position snapshot and update correlation monitor."""
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
        today_str = utc_now().strftime("%Y-%m-%d")
        corr_report = self._correlation_monitor.update(prices, positions, today_str)
        if any("cluster" in a for a in corr_report["cluster_alerts"]):
            logger.warning("Correlation cluster alert: %s", corr_report["cluster_alerts"])
        return {"n_high_pairs": len(corr_report["high_pairs"]), "cluster_alerts": corr_report["cluster_alerts"]}

    def _phase_3h_health_var_recovery(self, results: dict) -> None:
        """HealthMonitor observation, VaR/CVaR computation, and RecoveryScheduler."""
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
        if pv is not None and pv > 0:
            if self._var_prev_value is not None and self._var_prev_value > 0 and pv != self._var_prev_value:
                r = (pv - self._var_prev_value) / self._var_prev_value
                self._portfolio_returns.append(r)
                if len(self._portfolio_returns) > 252:
                    self._portfolio_returns = self._portfolio_returns[-252:]
                if len(self._portfolio_returns) >= 60:
                    rets = sorted(self._portfolio_returns[-60:])
                    n = len(rets)
                    idx = max(0, min(n - 1, int(0.05 * n)))
                    var_95 = rets[idx]
                    loss_idx = rets[: idx + 1]
                    cvar_95 = sum(loss_idx) / max(len(loss_idx), 1)
                    results["var_95"] = round(var_95, 6)
                    results["cvar_95"] = round(cvar_95, 6)
            self._var_prev_value = pv

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
                logger.info("RecoveryScheduler: attempting recovery for %s", name)
                try:
                    if hasattr(pos_mgr, "halted"):
                        pos_mgr.halted = False
                    if hasattr(eng, "_halted"):
                        eng._halted = False
                    self._recovery_scheduler.record_result(name, success=True)
                    recovered.append(name)
                except (AttributeError, TypeError) as exc:
                    self._recovery_scheduler.record_result(name, success=False, error=str(exc))
                    logger.error("RecoveryScheduler: recovery failed for %s: %s", name, exc)
        if recovered:
            results["actors_recovered"] = recovered
            logger.info("RecoveryScheduler: recovered %d actor(s): %s", len(recovered), recovered)

    def _phase_4_persist(self, results: dict) -> None:
        """Flush persist queues to buffer, record trade outcomes, commit WAL."""
        results["phasetimestamps"][EnginePhase.PERSIST] = utc_now_iso()
        persist_count = 0
        for name, actor in self._actors.items():
            commands = actor.drain_persist_queue()
            for cmd in commands:
                self._persist_buffer.append(cmd.__dict__)
                # Record completed trades to PerformanceStateBuilder
                if cmd.kind == "trade":
                    payload = cmd.payload
                    exit_reason = payload.get("exit_reason", "unknown")
                    if exit_reason in ("TP", "SL", "manual", "circuit_breaker", "PEK_BUDGET_OVERRUN"):
                        self._perf_builder.record_trade(
                            asset=cmd.asset or name,
                            exit_reason=exit_reason,
                            r_multiple=payload.get("r_multiple", 0.0),
                            mae_pct=payload.get("mae_pct", 0.0),
                            mfe_pct=payload.get("mfe_pct", 0.0),
                        )
                persist_count += 1
        results["persist_count"] = persist_count
        n_trades = (
            len(getattr(self._perf_builder, "_outcome_tracker", None)._outcomes or [])
            if hasattr(self._perf_builder, "_outcome_tracker")
            and hasattr(self._perf_builder._outcome_tracker, "_outcomes")
            else 0
        )
        results["performance"] = {"n_trades": n_trades}
        self._write_state_committed()

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
        snapshot["halt_reason"] = self._halt_reason.value if self._halt_reason else ""
        snapshot["halt_detail"] = self._halt_detail
        snapshot["abandoned_orphans"] = self._abandoned_orphans
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

    def _maybe_warn_halt_persistent(self) -> None:
        """Emit throttled WARNING when the engine is stuck in halt-persistent mode.

        Fires on cycle 1 with a halt active, then every 10 cycles. Captures the
        full halt context (reason, detail, peak, live equity) so the operator
        can diagnose staleness from engine.log without grepping state.json.

        No mutation — observability only.
        """
        if self._cycles_elapsed - self._halt_warn_last_cycle < 10:
            return
        self._halt_warn_last_cycle = self._cycles_elapsed
        peak = self._peak_portfolio_value
        live_equity = getattr(self, "_cycle_total_equity", None)
        if live_equity is None:
            live_equity = sum(a._engine.mtm_value for a in self._actors.values() if hasattr(a._engine, "mtm_value"))
        logger.warning(
            "emergency_halt_persistent — cycle=%d reason=%s detail=%s peak=%s live_mtm=%s",
            self._cycles_elapsed,
            self._halt_reason.value if self._halt_reason else "unknown",
            self._halt_detail or "(empty)",
            f"{peak:.2f}" if peak is not None else "None",
            f"{live_equity:.2f}" if live_equity is not None else "None",
        )

    def _check_auto_unhalt_eligibility(self) -> None:
        """Check if emergency halt can be automatically lifted.

        Eligible reasons: DRAWDOWN, CONSECUTIVE_LOSSES.
        Must show sustained recovery above DRAWDOWN_AUTO_UNHALT_THRESHOLD
        for DRAWDOWN_AUTO_UNHALT_MIN_CYCLES consecutive cycles.

        On first cycle after restart (_cycles_elapsed < 1), the equity
        snapshot is unstable — skip to avoid a noisy first read.
        """
        if not self._emergency_halt:
            return
        if self._halt_reason not in HALT_REASON_AUTO_UNHALT_ALLOWED:
            return
        if self._cycles_elapsed < 1:
            return
        if self._peak_portfolio_value is None or self._peak_portfolio_value <= 0:
            return

        total_equity = getattr(self, "_cycle_total_equity", None)
        if total_equity is None:
            total_equity = sum(a._engine.mtm_value for a in self._actors.values() if hasattr(a._engine, "mtm_value"))
        current_dd = (total_equity - self._peak_portfolio_value) / self._peak_portfolio_value

        if current_dd >= DRAWDOWN_AUTO_UNHALT_THRESHOLD:
            self._unhalt_recovery_cycles += 1
            if self._unhalt_recovery_cycles >= DRAWDOWN_AUTO_UNHALT_MIN_CYCLES:
                logger.warning(
                    "AUTO-UNHALT: drawdown recovered from %s to %.2f%% "
                    "(threshold %.2f%%) after %d cycles — resuming normal operation",
                    self._halt_detail,
                    current_dd * 100,
                    DRAWDOWN_AUTO_UNHALT_THRESHOLD * 100,
                    self._unhalt_recovery_cycles,
                )
                self._emergency_halt = False
                self._halt_reason = None
                self._halt_detail = ""
                self._unhalt_recovery_cycles = 0
                for actor in self._actors.values():
                    actor.reset()
                    if hasattr(actor._engine, "pos_mgr"):
                        actor._engine.pos_mgr.exposure_multiplier = 1.0
        else:
            self._unhalt_recovery_cycles = 0

    def flatten_positions(self, reason: str = "circuit_breaker") -> list[str]:
        """Close all open positions across all actors immediately.

        Called by the drawdown circuit breaker before setting emergency halt.
        Returns a list of asset names whose positions were closed.
        """

        flattened: list[str] = []
        now_iso = utc_now().isoformat()
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
            except (ValueError, TypeError, AttributeError, RuntimeError) as e:
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
        self._halt_reason = None
        self._halt_detail = ""
        self._unhalt_recovery_cycles = 0
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
    # Number of consecutive cycles a ticket must be missing from broker positions
    # before the paper position is closed as stale.  At 30s/cycle this is ~5 minutes.
    # Prevents premature closure during MT5 order fill propagation delay.
    MAX_STALE_TICKET_CYCLES = 10
    # After this many missing cycles, check the MT5 deal history (history_deals_get)
    # to determine whether the ticket was ever filled.  If it was, the position
    # was closed by MT5-native SL/TP or manual intervention.  If no deal exists,
    # the order was never filled (e.g. broker rejection) and the paper position
    # is a ghost.  At 30s/cycle this is ~90s for the deal-history check.
    STALE_TICKET_DEAL_CHECK_CYCLES = 3

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
                self._abandoned_orphans += 1
                logger.error(
                    "MT5_ORPHAN abandoned after %d retries: %s queue=%s — manual MT5 cleanup required",
                    self.MAX_CLEANUP_RETRIES,
                    name,
                    queue,
                )
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
                except (OSError, ValueError, TypeError) as e:
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
        #
        # Multi-cycle grace period: tickets must be missing for
        # MAX_STALE_TICKET_CYCLES (10) consecutive cycles before the paper
        # position is closed.  After STALE_TICKET_DEAL_CHECK_CYCLES (3)
        # cycles, the MT5 deal history is queried to distinguish between
        # "order never filled" (close paper) and "position MT5-closed but
        # paper stale" (close paper).  This prevents premature closure
        # during MT5 order fill propagation delay through Wine.
        if not broker.ensure_connected():
            return
        try:
            broker._position_cache_time = 0.0  # invalidate cache for fresh data
            mt5_positions = broker.get_positions()
        except (OSError, ValueError, TypeError):
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
            ticket_key = f"{name}:{mt5_ticket}"
            if str(mt5_ticket) not in mt5_by_ticket:
                # Ticket not found in broker positions — increment grace counter
                prev = self._stale_ticket_cycles.get(ticket_key, 0)
                self._stale_ticket_cycles[ticket_key] = prev + 1
                missing_for = self._stale_ticket_cycles[ticket_key]

                if missing_for >= self.MAX_STALE_TICKET_CYCLES:
                    # Grace period exhausted — close the paper position
                    logger.warning(
                        "MT5_STALE_TICKET: %s ticket=%s missing for %d/%d cycles — closing paper position",
                        name,
                        mt5_ticket,
                        missing_for,
                        self.MAX_STALE_TICKET_CYCLES,
                    )
                    self._stale_ticket_cycles.pop(ticket_key, None)
                    engine.position.pop("mt5_ticket", None)
                    exit_price = getattr(engine, "current_price", None)
                    if exit_price is not None and exit_price > 0:
                        try:
                            engine._close_position(
                                exit_price,
                                utc_now(),
                                "MT5_STALE_TICKET",
                            )
                        except Exception:
                            logger.exception(
                                "MT5_STALE_TICKET: %s failed to close paper position — position may be a ghost",
                                name,
                            )
                elif missing_for >= self.STALE_TICKET_DEAL_CHECK_CYCLES:
                    # Check MT5 deal history to determine if ticket was ever filled
                    try:
                        deal = broker.get_deal_by_ticket(int(mt5_ticket))
                    except Exception:
                        deal = None
                    if deal is not None:
                        logger.info(
                            "MT5_STALE_TICKET_DEAL_CHECK: %s ticket=%s found in deal history "
                            "(filled at %.5f profit=%.2f) — position was closed by MT5-native "
                            "SL/TP or manual intervention after %d/%d cycles",
                            name,
                            mt5_ticket,
                            deal["result"].get("price", 0),
                            deal["result"].get("profit", 0),
                            missing_for,
                            self.MAX_STALE_TICKET_CYCLES,
                        )
                        # Deal exists → position was genuinely filled and later closed.
                        # Don't pre-close the grace period — still wait for full
                        # MAX_STALE_TICKET_CYCLES to avoid race conditions with
                        # the paper position manager.  The log entry is for diagnostics.
                    else:
                        logger.warning(
                            "MT5_ORDER_REJECTED: %s ticket=%s missing for %d/%d cycles "
                            "and no deal found in history — order was never filled, "
                            "closing paper position early",
                            name,
                            mt5_ticket,
                            missing_for,
                            self.MAX_STALE_TICKET_CYCLES,
                        )
                        self._stale_ticket_cycles.pop(ticket_key, None)
                        engine.position.pop("mt5_ticket", None)
                        exit_price = getattr(engine, "current_price", None)
                        if exit_price is not None and exit_price > 0:
                            try:
                                engine._close_position(
                                    exit_price,
                                    utc_now(),
                                    "MT5_ORDER_REJECTED",
                                )
                            except Exception:
                                logger.exception(
                                    "MT5_ORDER_REJECTED: %s failed to close paper position — position may be a ghost",
                                    name,
                                )
                else:
                    logger.info(
                        "MT5_STALE_TICKET_GRACE: %s ticket=%s missing for %d/%d cycles "
                        "(deal check at %d cycles) — holding",
                        name,
                        mt5_ticket,
                        missing_for,
                        self.MAX_STALE_TICKET_CYCLES,
                        self.STALE_TICKET_DEAL_CHECK_CYCLES,
                    )
            else:
                # Ticket found in broker positions — recovered or normal
                if ticket_key in self._stale_ticket_cycles:
                    logger.info(
                        "MT5_STALE_TICKET_RECOVERED: %s ticket=%s reappeared after %d cycles — resetting grace counter",
                        name,
                        mt5_ticket,
                        self._stale_ticket_cycles[ticket_key],
                    )
                    self._stale_ticket_cycles.pop(ticket_key, None)

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

        # Build reverse symbol map: MT5 symbol → EigenCapital ticker
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
        """Shut down the persistent thread pool (called on exit via atexit).

        Uses wait=True to drain in-flight actor work before exit,
        ensuring WAL events are not truncated mid-write.
        """
        self._pool.shutdown(wait=True)
        logger.debug("EngineOrchestrator thread pool shut down")
