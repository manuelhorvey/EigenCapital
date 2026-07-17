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
import os
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime
from typing import Any

from eigencapital.domain.time import utc_now, utc_now_iso
from paper_trading.alerting.manager import global_alert_manager
from paper_trading.config_manager import EngineConfig, get_config
from paper_trading.governance.drawdown_controls import check_drawdown_circuit_breaker, compute_exposure_multiplier
from paper_trading.logging.correlation import set_correlation_id
from paper_trading.orchestrator.actor import (
    AssetActor,
    AssetResult,
    compute_health_snapshot,
)
from paper_trading.orchestrator.admission import AdmissionSignal, PortfolioAdmissionController
from paper_trading.orchestrator.admission.signal import PositionSide
from paper_trading.orchestrator.correlation import CorrelationMonitor, compute_position_concentration
from paper_trading.orchestrator.equity_tracker import EquityTracker
from paper_trading.orchestrator.halt_state import HaltState
from paper_trading.orchestrator.health import (
    CircuitBreaker,
    HaltReason,
    HealthMonitor,
    RecoveryScheduler,
)
from paper_trading.orchestrator.orphan_reconciliation import (
    MAX_CLEANUP_RETRIES,
    MAX_STALE_TICKET_CYCLES,
    STALE_TICKET_DEAL_CHECK_CYCLES,
    OrphanReconciler,
)
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
        config: EngineConfig | None = None,
    ):
        self._actors = actors
        self._config = config
        self._max_halt_ratio = max_halt_ratio
        self._max_workers = max_workers or len(actors) * 2
        self._persist_buffer: list[dict] = []
        self._halt_state = HaltState()
        self._equity_tracker = EquityTracker()
        self._last_pnl_date: datetime.date | None = None
        self._cycles_elapsed: int = 0
        self._wal = wal_writer
        self._last_health: dict | None = None
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
        # Restore trade outcomes from snapshot so win rate, consecutive losses,
        # and R-cumulative survive restarts.
        if snapshot is not None and snapshot.performance_state:
            self._perf_builder.load_state(snapshot.performance_state)

        # Portfolio circuit breaker (vol spike + consecutive loss)
        self._circuit_breaker = CircuitBreaker()

        # Restore emergency halt state from snapshot (delegated to HaltState)
        _init_equity = sum(a._engine.mtm_value for a in self._actors.values() if hasattr(a._engine, "mtm_value"))
        _current_capital = (self._config or get_config()).capital
        _peak_capital_base = getattr(snapshot, "peak_capital_base", None) if snapshot else None
        self._halt_state.restore_from_snapshot(snapshot, _init_equity, _current_capital, _peak_capital_base)

        # Restore circuit breaker state
        if snapshot is not None and getattr(snapshot, "emergency_halt", False):
            self._circuit_breaker.restore_state(
                peak_value=None,
                daily_pnl=getattr(snapshot, "breaker_daily_pnl", None),
            )
            logger.warning(
                "EngineOrchestrator: restored emergency halt from snapshot (reason=%s detail=%s peak=%.2f)",
                getattr(snapshot, "halt_reason", None),
                getattr(snapshot, "halt_detail", ""),
                getattr(snapshot, "peak_portfolio_value", 0.0) or 0.0,
            )

        # Auto-clear stale emergency halt
        def _alert(title, msg, **kw):
            with contextlib.suppress((OSError, RuntimeError, KeyError)):
                global_alert_manager().warning(title, msg, **kw)

        if self._halt_state.auto_clear_stale_halt(_init_equity, alert_callback=_alert):
            for actor in self._actors.values():
                actor.reset()

        # Cross-asset correlation monitor
        self._correlation_monitor = CorrelationMonitor()

        # HealthMonitor (system-wide health aggregation)
        self._health_monitor = HealthMonitor()

        # RecoveryScheduler (exponential backoff for HALTED actors)
        self._recovery_scheduler = RecoveryScheduler()

        # MT5 orphan reconciler (stateful — owns stale ticket counters, etc.)
        self._orphan_reconciler = OrphanReconciler()

        # PEK budget utilization from previous cycle (for sizing backfeed)
        # Not set here; _pre_phase_pek uses getattr with default 1.0 ("no throttling")

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
        # The portfolio-aggregate metrics that span the full set
        # (drawdown circuit breaker, peak re-anchor) read _saved_full_actors
        # so they see real portfolio equity, not the weekend-filtered total.
        _saved_actors = self._actors
        self._actors = self._filtered_actors(allowed_assets)
        self._saved_full_actors = _saved_actors
        try:
            return self._run_phases(market_data)
        finally:
            self._actors = _saved_actors
            self._saved_full_actors = None

    def _run_phases(self, market_data: dict | None = None) -> dict[str, Any]:
        """Execute the standard 4-phase cycle on self._actors (which may be filtered)."""
        results: dict[str, Any] = {
            "phasetimestamps": {},
            "assets": {},
            "circuit_breaker": None,
            "health": None,
        }

        set_correlation_id()
        self._cycles_elapsed += 1

        if self._halt_state.emergency_halt:
            self._halt_state.maybe_warn_persistent(self._cycles_elapsed, getattr(self, "_cycle_total_equity", None))
            if self._halt_state.check_auto_unhalt(self._cycles_elapsed, getattr(self, "_cycle_total_equity", None)):
                for actor in self._actors.values():
                    try:
                        actor.reset()
                    except (AttributeError, TypeError, RuntimeError, OSError):
                        logger.exception("Auto-unhalt: actor %s reset failed", actor.name)
            if self._halt_state.emergency_halt:
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

    def _inject_cycle_context(self, actor, total_equity: float, current_dd: float, exp_mult: float) -> None:
        """Atomically inject cycle context into an actor under its per-actor lock.

        Acquires the actor's ``_cycle_context_lock`` while writing so that
        the worker thread reading these attributes inside ``generate_signal()``
        sees a consistent snapshot.  The lock is held for <1 microsecond per
        write — contention is essentially zero because:
          (a) the pre-phase runs entirely on the main thread before any
              Phase 1a futures are submitted, and
          (b) the actor docs state "No actor reads or writes global state
              files directly" — the orchestrator writes before submission.
        """
        lock = getattr(actor, "_cycle_context_lock", None)
        if lock is not None:
            with lock:
                actor._engine._cycle_total_equity = total_equity
                actor._engine._cycle_drawdown_pct = current_dd
                if hasattr(actor._engine, "pos_mgr"):
                    actor._engine.pos_mgr.exposure_multiplier = exp_mult
        else:
            actor._engine._cycle_total_equity = total_equity
            actor._engine._cycle_drawdown_pct = current_dd
            if hasattr(actor._engine, "pos_mgr"):
                actor._engine.pos_mgr.exposure_multiplier = exp_mult

    def _pre_phase_pek(self) -> tuple[dict, float, list]:
        """Build PEK state: PortfolioStateSnapshot, PerformanceState, RiskBudget.

        Distributes cycle equity/drawdown to actors (no longer distributes
        leverage_budget_ref — that is now managed by the PEK).

        IMPORTANT: All actor._engine mutations MUST happen in this method,
        BEFORE _phase_1_refresh_signal submits futures to the ThreadPoolExecutor.
        The _inject_cycle_context helper is the single entrypoint for these writes.

        Returns (defaults, max_leverage, dummy_budget_ref) — keeping the
        same return signature as the old _pre_phase_equity_snapshot for
        backward compat with Phase 3 helpers.
        """
        defaults = (self._config or get_config()).defaults or {}
        max_leverage = defaults.get("portfolio_max_leverage", 2.0)
        # FIXED 2026-07-04: use the FULL portfolio for portfolio-aggregate
        # metrics (total_equity, drawdown).  During weekend/filtered cycles
        # self._actors is swapped to a subset (only weekend_eligible assets),
        # which makes drawdown read as ~-97% of peak and zero-out
        # exposure_multiplier across all actors — masking legitimate PnL
        # for sparse weekend coins (BTCUSD).  Phase 3c (commit 758410e)
        # already uses this pattern; PRE phase must match.
        _aggregate_actors = getattr(self, "_saved_full_actors", None) or self._actors
        total_equity = sum(a._engine.mtm_value for a in _aggregate_actors.values() if hasattr(a._engine, "mtm_value"))
        self._cycle_total_equity = total_equity
        _peak = self._halt_state.peak_portfolio_value
        current_dd = (total_equity - _peak) / max(_peak, 1.0) if _peak is not None and _peak > 0 else 0.0

        # Build portfolio state snapshot from live actors
        daily_pnl = 0.0
        if self._equity_tracker.var_prev_value is not None:
            current_value = sum(
                getattr(a._engine, "mtm_value", 0.0)
                for a in _aggregate_actors.values()
                if hasattr(a._engine, "mtm_value")
            )
            prev = self._equity_tracker.var_prev_value
            daily_pnl = (current_value - prev) if prev > 0 else 0.0
        self._portfolio_snapshot = PortfolioStateBuilder(
            mode_config=get_config().defaults or {},
        ).build(
            engine=self,
            cycle_count=self._cycles_elapsed,
            daily_pnl=daily_pnl,
            peak_value=self._halt_state.peak_portfolio_value or total_equity,
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

        # ── PERF-01: Pre-fetch shared macro data on the main thread ─────
        # Cross-asset data (DXY, VIX, SPX, commodities) was previously fetched
        # independently inside each actor's _build_feature_set, causing redundant
        # calls from 21 ThreadPoolExecutor workers.  Fetch once here (before any
        # futures are submitted) and pass to all actors via run_cycle().
        # The internal _macro_cache is also populated, so even actors that don't
        # receive shared_macro will hit the cache.
        from features.data_fetch import prefetch_shared_data

        self._shared_macro = prefetch_shared_data()
        self._shared_macro["_all_assets"] = {
            name: actor._engine.ticker for name, actor in self._actors.items() if hasattr(actor._engine, "ticker")
        }

        # Lazy-init PEK admission controller
        if self._pek is None:
            self._pek = PortfolioAdmissionController(
                mode_config=get_config().defaults or {},
            )

        # Distribute cycle values to actors (no leverage_budget_ref).
        # This is done BEFORE any ThreadPoolExecutor futures are submitted,
        # ensuring no data race on actor._engine attributes.
        exp_mult, _ = compute_exposure_multiplier(current_dd)
        for actor in self._actors.values():
            self._inject_cycle_context(actor, total_equity, current_dd, exp_mult)

        # PEK budget backfeed: if the previous cycle overran its budget,
        # reduce the exposure multiplier for the current cycle so that
        # position sizing stays within the budget proactively rather than
        # closing positions reactively after overrun.
        _budget_util = getattr(self, "_pek_budget_utilization", 1.0)
        if _budget_util > 1.0:
            _reduction = 1.0 / max(_budget_util, 1.001)
            exp_mult = min(exp_mult, exp_mult * _reduction)
            logger.info(
                "PEK_BUDGET_BACKFEED: utilization=%.2f%% reducing exp_mult by %.1f%% to %.3f",
                _budget_util * 100,
                (1 - _reduction) * 100,
                exp_mult,
            )

        # Dummy budget_ref for backward compat with any remaining callers
        budget_ref = [max_leverage * total_equity]
        return defaults, max_leverage, budget_ref

    def _phase_1_refresh_signal(self, market_data: dict | None, results: dict) -> None:
        """Parallel actor refresh + signal generation (Phase 1).

        Passes pre-fetched macro data (from _pre_phase_pek) to each actor
        so cross-asset data is fetched once per cycle on the main thread
        rather than redundantly in each worker thread.
        """
        results["phasetimestamps"][EnginePhase.REFRESH] = utc_now_iso()
        shared_macro = getattr(self, "_shared_macro", None)
        asset_results: dict[str, AssetResult] = {}

        def _run_actor(name: str, actor: AssetActor) -> AssetResult:
            if actor.health == actor.health.HALTED:
                return AssetResult.failed(name, "actor_halted", actor.metrics.cycle_id)
            return actor.run_cycle(market_data, shared_macro=shared_macro)

        futures = {self._pool.submit(_run_actor, n, a): n for n, a in self._actors.items()}
        for future in as_completed(futures):
            name = futures[future]
            try:
                asset_results[name] = future.result()
            except (RuntimeError, ValueError, TypeError, KeyError) as e:
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

            def _entry_notionals(actor) -> float:
                pos_mgr = getattr(actor._engine, "pos_mgr", None)
                if pos_mgr is None:
                    return getattr(actor._engine, "_last_entry_notional", 0.0) or 0.0
                entry_notional = getattr(pos_mgr, "_entry_notional", None)
                if isinstance(entry_notional, (int, float)) and entry_notional > 0:
                    return float(entry_notional)
                return getattr(actor._engine, "_last_entry_notional", 0.0) or 0.0

            current_notional = sum(_entry_notionals(actor) for actor in self._actors.values())
            # Store budget utilization for next cycle's sizing backfeed
            self._pek_budget_utilization = current_notional / max(max_notional, 1.0)
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
                    entry_notional_raw = getattr(pos_mgr, "_entry_notional", None)
                    entry_notional = (
                        float(entry_notional_raw)
                        if isinstance(entry_notional_raw, (int, float)) and entry_notional_raw > 0
                        else getattr(engine, "_last_entry_notional", 0.0) or 0.0
                    )
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
                    except (ValueError, TypeError, RuntimeError, AttributeError) as exc:
                        logger.error("PEK_BUDGET_CLOSE failed for %s: %s", sig.asset, exc)

                if closed_names:
                    with contextlib.suppress((OSError, RuntimeError, KeyError)):
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
            except (RuntimeError, ValueError, TypeError, AttributeError) as e:
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
        # Drawdown is a portfolio-aggregate metric.  When running a filtered
        # weekend cycle, sum over the FULL actor set, not the filtered subset,
        # so peak tracking reflects real portfolio equity.
        _aggregate_actors = getattr(self, "_saved_full_actors", None) or self._actors
        total_value = sum(
            actor._engine.current_value
            for actor in _aggregate_actors.values()
            if hasattr(actor._engine, "current_value")
        )

        # ── 3a: Drawdown circuit breaker ─────────────────────────────────
        self._halt_state.update_peak(total_value)
        dd_result = check_drawdown_circuit_breaker(
            total_value, self._halt_state.peak_portfolio_value, drawdown_limit=-0.15
        )
        results["drawdown"] = dd_result
        if dd_result["halted"]:
            logger.error(
                "DRAWDOWN CIRCUIT BREAKER TRIGGERED: dd=%.2f%% \u2014 flattening and halting all actors",
                dd_result["drawdown"] * 100,
            )
            flattened_assets = self.flatten_positions(reason="drawdown_circuit_breaker")
            for actor in self._actors.values():
                if hasattr(actor._engine, "pos_mgr"):
                    actor._engine.pos_mgr.exposure_multiplier = 0.0
            self._halt_state.set_halt(HaltReason.DRAWDOWN.value, f"dd={dd_result['drawdown']:.4f}")
            _peak_val = self._halt_state.peak_portfolio_value
            with contextlib.suppress((OSError, RuntimeError, KeyError)):
                global_alert_manager().critical(
                    "Portfolio halted — drawdown circuit breaker",
                    (
                        f"Drawdown {dd_result['drawdown'] * 100:.2f}% exceeded "
                        f"-15% limit. {len(flattened_assets)} position(s) flattened."
                    ),
                    details={
                        "drawdown_pct": round(dd_result["drawdown"] * 100, 2),
                        "limit_pct": 15.0,
                        "peak": round(_peak_val, 2) if _peak_val else None,
                        "total_value": round(total_value, 2),
                        "n_positions_flattened": len(flattened_assets),
                        "flattened_assets": flattened_assets,
                        "halt_reason": "DRAWDOWN",
                    },
                )
            results["circuit_breaker"] = {"triggered": True, "reason": f"drawdown_{dd_result['drawdown']:.4f}"}
            return True

        # ── 3b: Halt ratio circuit breaker ────────────────────────────────
        if not health.is_system_healthy:
            logger.error(
                "PORTFOLIO CIRCUIT BREAKER: halt_ratio=%.2f exceeds max=%.2f \u2014 initiating emergency shutdown",
                health.halt_ratio,
                self._max_halt_ratio,
            )
            self._halt_state.set_halt(HaltReason.HALT_RATIO.value, f"halt_ratio={health.halt_ratio:.4f}")
            with contextlib.suppress((OSError, RuntimeError, KeyError)):
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
        today = utc_now().date()
        if self._last_pnl_date != today:
            self._circuit_breaker.record_daily_pnl(total_value - prev_value)
            self._last_pnl_date = today
        self._prev_portfolio_value = total_value

        breaker_result = self._circuit_breaker.check(
            portfolio_value=total_value,
            peak_value=self._halt_state.peak_portfolio_value,
            actors=self._actors,
        )
        results["circuit_breaker_full"] = {
            "trip": breaker_result.trip,
            "reason": breaker_result.reason,
            "severity": breaker_result.severity,
        }
        if breaker_result.trip:
            halt_reason_str = (
                HaltReason.VOL_SPIKE.value
                if "vol_spike" in breaker_result.reason
                else HaltReason.CONSECUTIVE_LOSSES.value
            )
            self._halt_state.set_halt(halt_reason_str, breaker_result.reason)
            logger.error(
                "VOLATILITY CIRCUIT BREAKER TRIGGERED: %s \u2014 flattening and halting",
                breaker_result.reason,
            )
            with contextlib.suppress((OSError, RuntimeError, KeyError)):
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
        conc = compute_position_concentration(self._actors)
        results["position_concentration"] = conc
        self._position_concentration = conc
        if self._wal is not None:
            try:
                self._wal.write("position_concentration", conc)
            except (RuntimeError, OSError, KeyError):
                logger.exception("WAL write failed for position_concentration")

        # ── 3f: Cross-asset correlation ───────────────────────────────────
        corr = self._correlation_monitor.compute_portfolio_correlation(self._actors)
        results["correlation"] = corr

        # ── 3g: MT5 orphan reconciliation ────────────────────────────────
        self._reconcile_mt5_orphans()

        # ── 3h: HealthMonitor + VaR + RecoveryScheduler ──────────────────
        self._phase_3h_health_var_recovery(results)

        return False

    def _phase_3h_health_var_recovery(self, results: dict) -> None:
        """HealthMonitor observation, VaR/CVaR computation, and RecoveryScheduler."""
        pv = None
        try:
            pv_raw = self.get_total_portfolio_value()
            if pv_raw is not None:
                pv = float(pv_raw)
        except (TypeError, ValueError):
            pass
        # Use the orchestrator's canonical peak value (single source of truth).
        # CircuitBreaker no longer tracks its own _peak_value to avoid divergence.
        portfolio_peak = self._halt_state.peak_portfolio_value
        baseline_vol = self._equity_tracker.var_baseline_vol
        health_summary = self._health_monitor.observe(
            self._actors,
            portfolio_value=pv,
            portfolio_peak=portfolio_peak,
            portfolio_vol=self._equity_tracker.portfolio_vol_estimate(),
            baseline_vol=baseline_vol,
        )
        results["health_monitor"] = {
            "halt_ratio": health_summary.halt_ratio,
            "n_green": health_summary.n_green,
            "n_halted": health_summary.n_halted,
            "recommendations": health_summary.recommendations,
        }
        if pv is not None and pv > 0:
            var_95, cvar_95 = self._equity_tracker.record_return(pv)
            if var_95 is not None:
                results["var_95"] = var_95
            if cvar_95 is not None:
                results["cvar_95"] = cvar_95

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
            except (RuntimeError, OSError, KeyError):
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
        snapshot["emergency_halt"] = self._halt_state.emergency_halt
        snapshot["halt_reason"] = self._halt_state.halt_reason or ""
        snapshot["halt_detail"] = self._halt_state.halt_detail
        snapshot["abandoned_orphans"] = self._orphan_reconciler.abandoned_orphans
        try:
            self._wal.write("state_committed", snapshot)
        except (RuntimeError, OSError, KeyError):
            logger.exception("WAL write failed for state_committed")

    def drain_persist_buffer(self) -> list[dict]:
        """Return and clear the global persist buffer."""
        buf = list(self._persist_buffer)
        self._persist_buffer.clear()
        return buf

    @property
    def emergency_halt(self) -> bool:
        return self._halt_state.emergency_halt

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
            has_any = (pos_mgr is not None and pos_mgr.has_position()) or bool(getattr(engine, "batches", None))
            if not has_any:
                continue
            exit_price = getattr(engine, "current_price", None)
            if exit_price is None or exit_price <= 0:
                continue
            try:
                engine._close_all_positions(exit_price=exit_price, exit_date=now_iso, reason=reason)
                flattened.append(name)
                logger.warning("%s: position(s) closed by circuit breaker (%.4f)", name, exit_price)
            except (ValueError, TypeError, AttributeError, RuntimeError) as e:
                logger.error("%s: circuit breaker flatten failed: %s", name, e)
        if flattened:
            logger.error(
                "CIRCUIT BREAKER FLATTEN: %d asset(s) flattened: %s",
                len(flattened),
                ", ".join(flattened),
            )
        return flattened

    def reset_emergency_halt(self) -> None:
        """Reset emergency halt (e.g., after manual review)."""
        self._halt_state.reset()
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

    # Backward-compat class-level constants for test imports
    MAX_CLEANUP_RETRIES = MAX_CLEANUP_RETRIES
    MAX_STALE_TICKET_CYCLES = MAX_STALE_TICKET_CYCLES
    STALE_TICKET_DEAL_CHECK_CYCLES = STALE_TICKET_DEAL_CHECK_CYCLES

    def _reconcile_mt5_orphans(self) -> None:
        """Delegate to OrphanReconciler for all MT5 orphan reconciliation."""
        self._orphan_reconciler.reconcile(self._actors, self._resolve_broker)

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

    def shutdown(self) -> None:
        """Shut down the persistent thread pool (called on exit via atexit).

        Uses wait=True to drain in-flight actor work before exit,
        ensuring WAL events are not truncated mid-write.
        """
        self._pool.shutdown(wait=True)
        logger.debug("EngineOrchestrator thread pool shut down")
