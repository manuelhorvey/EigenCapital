"""Per-asset actor with isolated execution lifecycle.

Each AssetActor owns ONE asset's complete lifecycle: data refresh, signal
generation, position management, and persistence.  No actor shares mutable
state with any other actor.

Health model:
    - GREEN:  normal operation, no recent failures
    - DEGRADED:  consecutive failures ≤ threshold, operations continue
    - HALTED:  consecutive failures > threshold, actor suspends execution
    - RECOVERING:  after HALTED, cooldown period, then probe before resume

Thread safety:
    Actors communicate via immutable commands sent to a single writer thread.
    No actor reads or writes global state files directly.
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum, auto
from typing import Any

import pandas as pd

from paper_trading.replay.wal import WalWriter

logger = logging.getLogger("eigencapital.orchestrator.actor")


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
    cycle_id: int = 0
    duration_ms: float = 0.0

    @classmethod
    def ok(cls, asset: str, signal: dict, cycle_id: int = 0, duration_ms: float = 0.0) -> AssetResult:
        return cls(asset=asset, success=True, signal=signal, cycle_id=cycle_id, duration_ms=duration_ms)

    @classmethod
    def failed(cls, asset: str, error: str, cycle_id: int = 0, duration_ms: float = 0.0) -> AssetResult:
        return cls(asset=asset, success=False, error=error, cycle_id=cycle_id, duration_ms=duration_ms)


@dataclass
class PersistCommand:
    """Immutable command sent from actor to persistence writer thread."""

    kind: str  # "trade", "snapshot", "attribution", "signal"
    payload: dict
    asset: str = ""
    timestamp: float = field(default_factory=time.monotonic)


class AssetActor:
    """Isolated execution unit for a single asset.

    Usage::
        actor = AssetActor("EURUSD", asset_engine)
        result = actor.run_cycle(market_data)
        if not result.success:
            actor.consecutive_failures += 1
    """

    def __init__(
        self,
        name: str,
        engine: Any,  # AssetEngine
        max_consecutive_failures: int = 3,
        recovery_cooldown_seconds: float = 60.0,
        wal_writer: WalWriter | None = None,
    ):
        self.name = name
        self._engine = engine
        self._max_failures = max_consecutive_failures
        self._recovery_cooldown = recovery_cooldown_seconds
        self._wal = wal_writer
        if wal_writer is not None:
            engine._wal_writer = wal_writer

        self.health: ActorHealth = ActorHealth.GREEN
        self.metrics = ActorMetrics()
        self._last_recovery_probe: float = 0.0
        self._persist_queue: list[PersistCommand] = []
        self._fault_reason: str = ""
        self._last_trade_count: int = 0
        self._last_price: float | None = None

    # ── Public API ────────────────────────────────────────────────────────────

    def run_cycle(self, market_data: dict | None = None) -> AssetResult:
        """Execute one full lifecycle cycle for this asset.

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

            signal = self._engine.generate_signal()
            self._write_signal(signal)

            self._handle_success(t0)
            self._queue_persist("signal", signal or {})
            return AssetResult.ok(self.name, signal or {}, self.metrics.cycle_id, self.metrics.cycle_duration_ms)
        except Exception as e:
            import traceback

            logger.error("%s actor exception:\n%s", self.name, traceback.format_exc())
            self._handle_failure(t0, str(e))
            return AssetResult.failed(self.name, str(e), self.metrics.cycle_id, self.metrics.cycle_duration_ms)

    def drain_persist_queue(self) -> list[PersistCommand]:
        """Return and clear queued persist commands.

        Called by the orchestrator's single writer thread.
        """
        commands = list(self._persist_queue)
        self._persist_queue.clear()
        return commands

    def reset(self) -> None:
        """Reset actor to GREEN health."""
        self.health = ActorHealth.GREEN
        self.metrics = ActorMetrics()
        self._fault_reason = ""
        self._persist_queue.clear()

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
        self.health = ActorHealth.GREEN

    def _handle_failure(self, t0: float, error: str) -> None:
        elapsed = (time.monotonic() - t0) * 1000.0
        self.metrics.last_failure_time = time.monotonic()
        self.metrics.consecutive_failures += 1
        self.metrics.total_failures += 1
        self.metrics.cycle_duration_ms = round(elapsed, 2)
        self._fault_reason = error

        if self.metrics.consecutive_failures >= self._max_failures:
            self.health = ActorHealth.HALTED
            logger.error(
                "%s actor HALTED after %d consecutive failures (max=%d). Last error: %s",
                self.name,
                self.metrics.consecutive_failures,
                self._max_failures,
                error,
            )
        else:
            self.health = ActorHealth.DEGRADED
            logger.warning(
                "%s actor degraded (%d/%d failures): %s",
                self.name,
                self.metrics.consecutive_failures,
                self._max_failures,
                error,
            )

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
                        "time": str(datetime.now()),
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
                        "time": str(datetime.now()),
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
