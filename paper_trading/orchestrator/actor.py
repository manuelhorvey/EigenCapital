"""Per-asset actor with isolated execution lifecycle.

Each AssetActor owns ONE asset's complete lifecycle: data refresh, signal
generation, position management, and persistence.  No actor shares mutable
state with any other actor.

Health model (percentage-based rolling window):
    - A sliding window of the last N cycle outcomes (success/failure) is
      maintained.  health_score = (successes / window_size) * 100, ranging
      0-100.
    - GREEN:   health_score >= 80  (default threshold)
    - DEGRADED: health_score >= 50 (default threshold)
    - HALTED:   health_score < 50  OR consecutive_failures >= max_failures
    - Recovery (HALTED -> RECOVERING -> GREEN) unchanged.

    Cold-start grace: the first 5 cycles use the old consecutive-failure
    rules (any failure = DEGRADED, max_failures = HALTED) so a single
    early failure doesn't permanently lock the score before the window
    fills.

Thread safety:
    Actors communicate via immutable commands sent to a single writer thread.
    No actor reads or writes global state files directly.
"""

from __future__ import annotations

import logging
import time
from collections import deque
from dataclasses import dataclass, field
from enum import Enum, auto
from typing import Any

import pandas as pd

from eigencapital.domain.time import utc_now
from paper_trading.replay.wal import WalWriter

# Type alias for pre-fetched shared macro data dict (ticker → Series)
SharedMacroData = dict[str, pd.Series]

logger = logging.getLogger("eigencapital.orchestrator.actor")

# Default health thresholds — configurable per-actor via constructor.
HEALTH_WINDOW_SIZE: int = 20
HEALTH_GREEN_THRESHOLD: float = 80.0  # score >= 80 = GREEN
HEALTH_HALTED_THRESHOLD: float = 50.0  # score < 50 = HALTED (else DEGRADED)
HEALTH_MIN_CYCLES_BEFORE_SCORING: int = 5  # cold-start grace period


class FaultCategory(Enum):
    """Category of failure for an actor cycle.

    Discriminates between transient network/data issues (expected in
    production) and logic bugs (code defects requiring investigation).

    Values:
        NETWORK — OSError, ConnectionError, TimeoutError (transient I/O)
        LOGIC   — KeyError, AttributeError, RuntimeError, ImportError (code bugs)
        UNKNOWN — default when no exception was raised (e.g. halted actors)
    """

    NETWORK = "network"
    LOGIC = "logic"
    UNKNOWN = "unknown"


class ActorHealth(Enum):
    GREEN = auto()
    DEGRADED = auto()
    HALTED = auto()
    RECOVERING = auto()


@dataclass
class ActorMetrics:
    """Observable metrics for a single actor cycle."""

    cycle_id: int = 0
    last_success_time: float = 0.0
    last_failure_time: float = 0.0
    consecutive_failures: int = 0
    consecutive_successes: int = 0
    total_cycles: int = 0
    total_failures: int = 0
    cycle_duration_ms: float = 0.0
    avg_duration_ms: float = 0.0


@dataclass
class AssetResult:
    """Immutable outcome of one asset cycle."""

    asset: str
    success: bool
    signal: dict | None = None
    error: str | None = None
    fault_category: str = "unknown"
    cycle_id: int = 0
    duration_ms: float = 0.0

    @classmethod
    def ok(cls, asset: str, signal: dict, cycle_id: int = 0, duration_ms: float = 0.0) -> AssetResult:
        return cls(asset=asset, success=True, signal=signal, cycle_id=cycle_id, duration_ms=duration_ms)

    @classmethod
    def failed(
        cls,
        asset: str,
        error: str,
        cycle_id: int = 0,
        duration_ms: float = 0.0,
        fault_category: str = "unknown",
    ) -> AssetResult:
        return cls(
            asset=asset,
            success=False,
            error=error,
            cycle_id=cycle_id,
            duration_ms=duration_ms,
            fault_category=fault_category,
        )


@dataclass
class PersistCommand:
    """Immutable command sent from actor to persistence writer thread."""

    kind: str  # "trade", "snapshot", "attribution", "signal"
    payload: dict
    asset: str = ""
    timestamp: float = field(default_factory=time.monotonic)


class AssetActor:
    """Isolated execution unit for a single asset.

    Health is determined by a rolling window of cycle outcomes.
    See module docstring for threshold details.

    Usage::
        actor = AssetActor("EURUSD", asset_engine)
        result = actor.run_cycle()
        if not result.success:
            actor.consecutive_failures += 1
    """

    def __init__(
        self,
        name: str,
        engine: Any,  # AssetEngine
        max_consecutive_failures: int = 10,
        recovery_cooldown_seconds: float = 60.0,
        wal_writer: WalWriter | None = None,
        health_window_size: int = HEALTH_WINDOW_SIZE,
        health_green_threshold: float = HEALTH_GREEN_THRESHOLD,
        health_halted_threshold: float = HEALTH_HALTED_THRESHOLD,
    ):
        self.name = name
        self._engine = engine
        self._max_failures = max_consecutive_failures
        self._recovery_cooldown = recovery_cooldown_seconds
        self._wal = wal_writer
        if wal_writer is not None:
            engine._wal_writer = wal_writer

        # ── Health scoring ──
        self.health: ActorHealth = ActorHealth.GREEN
        self._outcome_window: deque[bool] = deque(maxlen=health_window_size)
        self._health_window_size = health_window_size
        self._health_green_threshold = health_green_threshold
        self._health_halted_threshold = health_halted_threshold

        self.metrics = ActorMetrics()
        self._last_recovery_probe: float = 0.0
        self._persist_queue: list[PersistCommand] = []
        self._fault_reason: str = ""
        self._last_trade_count: int = 0
        self._last_price: float | None = None

    @property
    def health_score(self) -> float:
        """Current health percentage (0-100) from rolling outcome window."""
        if not self._outcome_window:
            return 100.0
        successes = sum(1 for x in self._outcome_window if x)
        return round((successes / len(self._outcome_window)) * 100.0, 1)

    # ── Public API ────────────────────────────────────────────────────────────

    def run_cycle(self, market_data: dict | None = None, shared_macro: SharedMacroData | None = None) -> AssetResult:
        """Execute one full lifecycle cycle for this asset.

        When *shared_macro* is provided (pre-fetched macro data from the
        orchestrator pre-phase), the actor passes it through to the inference
        pipeline so cross-asset data (DXY, VIX, SPX, WTI) is fetched once
        per cycle rather than redundantly in each actor thread.

        Returns an immutable AssetResult.  Does not raise.
        """
        t0 = time.monotonic()
        self.metrics.total_cycles += 1
        self.metrics.cycle_id += 1

        if self.health == ActorHealth.HALTED:
            self._maybe_probe_recovery()
            if self.health == ActorHealth.HALTED:
                return AssetResult.failed(
                    self.name,
                    f"actor_halted: {self._fault_reason}",
                    self.metrics.cycle_id,
                )

        try:
            self._engine.refresh_price()
            self._write_price_update()

            self._engine.update_pnl()
            self._write_position_events()

            signal = self._engine.generate_signal(shared_macro=shared_macro)
            self._write_signal(signal)

            self._handle_success(t0)
            self._queue_persist("signal", signal or {})
            return AssetResult.ok(self.name, signal or {}, self.metrics.cycle_id, self.metrics.cycle_duration_ms)
        # ── Network / data failures (expected transient) ─────────────────
        # OSError: MT5 connection timeout, socket reset, file I/O errors.
        # ValueError / TypeError: malformed data from external sources (empty
        # DataFrames, None where Series expected, type mismatches from yfinance).
        # These are EXPECTED in production. Log once at WARNING, not ERROR.
        except (OSError, ValueError, TypeError) as exc:
            _exc_type = type(exc).__name__
            logger.warning(
                "%s actor transient failure [%s]: %s",
                self.name,
                _exc_type,
                exc,
            )
            self._handle_failure(t0, f"transient:{_exc_type}:{exc}", fault_category=FaultCategory.NETWORK.value)
            return AssetResult.failed(
                self.name,
                f"actor_exception:transient:{_exc_type}",
                self.metrics.cycle_id,
                self.metrics.cycle_duration_ms,
                fault_category=FaultCategory.NETWORK.value,
            )
        # ── Logic bugs (code defects — need investigation) ────────────────
        # KeyError: dict access with missing key.
        # AttributeError: access to non-existent attribute on engine/position.
        # RuntimeError: general runtime invariant violation.
        # ImportError: missing module (deployment issue or broken refactor).
        # These indicate a CODE BUG. Log at ERROR with full traceback so
        # developers get actionable diagnostics.
        except (KeyError, AttributeError, RuntimeError, ImportError) as exc:
            import traceback

            _tb = traceback.format_exc()
            _exc_type = type(exc).__name__
            logger.error(
                "%s actor LOGIC BUG [%s]:\n%s",
                self.name,
                _exc_type,
                _tb,
            )
            self._handle_failure(t0, f"logic:{_exc_type}:{exc}", fault_category=FaultCategory.LOGIC.value)
            return AssetResult.failed(
                self.name,
                f"actor_exception:logic:{_exc_type}",
                self.metrics.cycle_id,
                self.metrics.cycle_duration_ms,
                fault_category=FaultCategory.LOGIC.value,
            )

    def drain_persist_queue(self) -> list[PersistCommand]:
        """Return and clear queued persist commands.

        Called by the orchestrator's single writer thread.
        """
        commands = list(self._persist_queue)
        self._persist_queue.clear()
        return commands

    def reset(self) -> None:
        """Reset actor to GREEN health and clear halted flags."""
        self.health = ActorHealth.GREEN
        self._outcome_window.clear()
        self.metrics = ActorMetrics()
        self._fault_reason = ""
        self._persist_queue.clear()
        eng = getattr(self, "_engine", None)
        if eng is not None:
            try:
                pos_mgr = getattr(eng, "pos_mgr", None)
                if pos_mgr is not None:
                    pos_mgr.halted = False
                if hasattr(eng, "_halted"):
                    eng._halted = False
            except (AttributeError, TypeError):
                pass

    # ── Internal ──────────────────────────────────────────────────────────────

    def _handle_success(self, t0: float) -> None:
        elapsed = (time.monotonic() - t0) * 1000.0
        self.metrics.last_success_time = time.monotonic()
        self.metrics.consecutive_failures = 0
        self.metrics.consecutive_successes += 1
        self.metrics.cycle_duration_ms = round(elapsed, 2)
        self.metrics.avg_duration_ms = round(
            (self.metrics.avg_duration_ms * (self.metrics.total_cycles - 1) + elapsed)
            / max(self.metrics.total_cycles, 1),
            2,
        )
        # Record success in rolling window and update health
        self._outcome_window.append(True)
        self._update_health()

    def _handle_failure(self, t0: float, error: str, fault_category: str = "unknown") -> None:
        elapsed = (time.monotonic() - t0) * 1000.0
        self.metrics.last_failure_time = time.monotonic()
        self.metrics.consecutive_failures += 1
        self.metrics.total_failures += 1
        self.metrics.cycle_duration_ms = round(elapsed, 2)
        self._fault_reason = f"[{fault_category}] {error}"

        # Record failure in rolling window and update health
        self._outcome_window.append(False)
        self._update_health()

        if self.health == ActorHealth.HALTED:
            logger.error(
                "%s actor HALTED [%s] after %d consecutive failures (max=%d). Last error: %s",
                self.name,
                fault_category,
                self.metrics.consecutive_failures,
                self._max_failures,
                error,
            )
        elif self.health == ActorHealth.DEGRADED:
            logger.warning(
                "%s actor DEGRADED [%s] (%d/%d failures, health_score=%.1f): %s",
                self.name,
                fault_category,
                self.metrics.consecutive_failures,
                self._max_failures,
                self.health_score,
                error,
            )
        else:
            logger.info(
                "%s actor failure [%s] (health still GREEN at score=%.1f): %s",
                self.name,
                fault_category,
                self.health_score,
                error,
            )

    def _update_health(self) -> None:
        """Update health state from rolling window score and consecutive failures.

        Priority:
            1. Consecutive failures >= max_failures → HALTED (rapid response)
            2. Cold start (< HEALTH_MIN_CYCLES_BEFORE_SCORING cycles in window):
               - 0 failures in window → GREEN
               - Any failures, but < max_failures → DEGRADED
            3. Standard percentage scoring:
               - health_score >= green_threshold → GREEN
               - health_score >= halted_threshold → DEGRADED
               - health_score < halted_threshold → HALTED
        """
        score = self.health_score

        # 1. Rapid halt on consecutive failures (always applies)
        if self.metrics.consecutive_failures >= self._max_failures:
            self.health = ActorHealth.HALTED
            return

        n = len(self._outcome_window)

        # 2. Cold-start grace period
        if n < HEALTH_MIN_CYCLES_BEFORE_SCORING:
            self.health = ActorHealth.DEGRADED if self.metrics.consecutive_failures > 0 else ActorHealth.GREEN
            return

        # 3. Standard percentage-based scoring
        if score >= self._health_green_threshold:
            self.health = ActorHealth.GREEN
        elif score >= self._health_halted_threshold:
            self.health = ActorHealth.DEGRADED
        else:
            self.health = ActorHealth.HALTED

    def _maybe_probe_recovery(self) -> None:
        """Check if enough time has passed to attempt recovery."""
        now = time.monotonic()
        if now - self.metrics.last_failure_time < self._recovery_cooldown:
            return
        if now - self._last_recovery_probe < self._recovery_cooldown:
            return
        self._last_recovery_probe = now
        self.health = ActorHealth.RECOVERING
        logger.info("%s actor attempting recovery probe", self.name)

    def _queue_persist(self, kind: str, payload: dict) -> None:
        self._persist_queue.append(PersistCommand(kind=kind, payload=payload, asset=self.name))

    # ── WAL event emission ───────────────────────────────────────────

    def _write_price_update(self) -> None:
        if self._wal is None:
            return
        price = self._engine.current_price
        if price is not None and not (isinstance(price, float) and pd.isna(price)):
            try:
                self._wal.write(
                    "price_update",
                    {
                        "asset": self.name,
                        "price": float(price),
                        "time": utc_now().isoformat(),
                    },
                )
            except Exception:
                logger.exception("WAL write failed for price_update on %s", self.name)
            self._last_price = float(price)

    def _write_position_events(self) -> None:
        if self._wal is None:
            return
        current_count = len(getattr(self._engine, "trade_log", []))
        if current_count > self._last_trade_count:
            for trade in getattr(self._engine, "trade_log", [])[self._last_trade_count :]:
                try:
                    self._wal.write(
                        "position_closed",
                        {
                            "asset": self.name,
                            "reason": trade.get("reason", "unknown"),
                            "pnl": trade.get("pnl", 0),
                            "exit_price": trade.get("exit_price", 0),
                            "entry_price": trade.get("entry_price", 0),
                            "side": trade.get("side", ""),
                            "exit_date": trade.get("exit_date", ""),
                        },
                    )
                except Exception:
                    logger.exception("WAL write failed for position_closed on %s", self.name)
        self._last_trade_count = current_count

    def _write_signal(self, signal: dict | None) -> None:
        if self._wal is None:
            return
        if signal is not None:
            try:
                self._wal.write(
                    "signal_generated",
                    {
                        "asset": self.name,
                        "signal": signal.get("signal"),
                        "confidence": signal.get("confidence"),
                        "position_size": signal.get("position_size", 0),
                        "time": utc_now().isoformat(),
                    },
                )
            except Exception:
                logger.exception("WAL write failed for signal_generated on %s", self.name)


# ── Actor Health Aggregator ───────────────────────────────────────────────────


@dataclass
class ActorHealthSnapshot:
    """Point-in-time health snapshot across all actors."""

    timestamp: float = field(default_factory=time.monotonic)
    green: int = 0
    degraded: int = 0
    halted: int = 0
    recovering: int = 0
    total_failures: int = 0
    total_cycles: int = 0
    total_assets: int = 0

    @property
    def halt_ratio(self) -> float:
        return self.halted / max(self.total_assets, 1)

    @property
    def is_system_healthy(self) -> bool:
        return self.halt_ratio < 0.5


def compute_health_snapshot(actors: dict[str, AssetActor]) -> ActorHealthSnapshot:
    snapshot = ActorHealthSnapshot(total_assets=len(actors))
    for actor in actors.values():
        match actor.health:
            case ActorHealth.GREEN:
                snapshot.green += 1
            case ActorHealth.DEGRADED:
                snapshot.degraded += 1
            case ActorHealth.HALTED:
                snapshot.halted += 1
            case ActorHealth.RECOVERING:
                snapshot.recovering += 1
        snapshot.total_failures += actor.metrics.total_failures
        snapshot.total_cycles += actor.metrics.total_cycles
    return snapshot
