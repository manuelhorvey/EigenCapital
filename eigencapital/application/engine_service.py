"""EngineService — application-layer orchestrator for EigenCapital.

This is the primary entry point for the hexagonal architecture's application
layer. It abstracts the engine's lifecycle behind domain-typed interfaces,
allowing the infrastructure layer (paper_trading/) to be swapped without
affecting domain logic.

Usage::

    from eigencapital.application.engine_service import EngineService

    service = EngineService(config)
    service.start()
    while service.is_running:
        result = service.run_once()
        ...
    service.shutdown()

The EngineService delegates to the concrete PaperTradingEngine internally
but exposes domain-typed inputs and outputs so that callers never import
from ``paper_trading.engine`` directly.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from eigencapital.domain.entities.signal import SignalResult, SignalType

logger = logging.getLogger("eigencapital.application.engine_service")


@dataclass(frozen=True)
class EngineStatus:
    """Immutable snapshot of engine health and cycle state."""

    is_running: bool
    cycle_count: int
    emergency_halt: bool
    last_update: datetime | None
    total_equity: float | None
    portfolio_value: float | None
    n_assets: int


@dataclass(frozen=True)
class CycleResult:
    """Outcome of a single engine cycle."""

    cycle_id: int
    duration_ms: float
    signals: dict[str, SignalResult]
    health: dict[str, Any] | None
    circuit_breaker: dict[str, Any] | None
    errors: list[str]


class EngineService:
    """Application-layer facade over the paper trading engine.

    Owns the lifecycle of a ``PaperTradingEngine`` instance and provides
    domain-typed accessors for callers that should not depend on the
    infrastructure layer directly.

    Thread-safety: not guaranteed. Callers should run the engine loop from
    a single thread or provide external synchronization.
    """

    def __init__(self, config: Any | None = None):
        self._config = config
        self._engine: Any = None
        self._cycle_count: int = 0
        self._is_running: bool = False
        self._last_error: str | None = None

        # Lazy-import the infrastructure engine to avoid circular deps
        # at module-import time.  The EngineService is the architectural
        # boundary between domain and infrastructure.
        self._engine_cls: type | None = None

    # ── Lifecycle ───────────────────────────────────────────────────────────

    def start(self) -> None:
        """Initialize and start the engine.

        Creates a ``PaperTradingEngine`` instance from config and prepares
        all subsystems for cycle execution.
        """
        if self._is_running:
            logger.warning("EngineService.start() called but engine is already running")
            return

        try:
            from paper_trading.engine import PaperTradingEngine

            self._engine_cls = PaperTradingEngine
            self._engine = PaperTradingEngine(config=self._config)
            self._is_running = True
            logger.info("EngineService started with %d asset(s)", len(self._engine.assets or {}))
        except Exception as exc:
            self._last_error = f"EngineService.start() failed: {exc}"
            logger.critical(self._last_error)
            raise

    def run_once(self) -> CycleResult | None:
        """Execute one engine cycle and return domain-typed results.

        Returns ``None`` if the engine is not running or the cycle produced
        no results (e.g. market closed with no weekend-eligible assets).
        """
        if not self._engine:
            logger.warning("EngineService.run_once() called but engine not started")
            return None

        import time

        t0 = time.monotonic()
        try:
            raw = self._engine.run_once()
        except (OSError, RuntimeError, ValueError, TypeError, AttributeError, KeyError) as exc:
            self._last_error = f"Cycle {self._cycle_count + 1} failed: {exc}"
            logger.exception(self._last_error)
            return CycleResult(
                cycle_id=self._cycle_count + 1,
                duration_ms=0.0,
                signals={},
                health=None,
                circuit_breaker=None,
                errors=[f"Cycle failed: {exc}"],
            )

        if not raw:
            return None

        self._cycle_count += 1
        duration = (time.monotonic() - t0) * 1000.0

        # Convert raw signal dicts to domain SignalResult objects
        signals: dict[str, SignalResult] = {}
        for name, sig in raw.items():
            if not isinstance(sig, dict):
                continue
            try:
                side = sig.get("side", "none")
                signal_type = SignalType(side) if side and side != "none" else SignalType.NONE
            except ValueError:
                signal_type = SignalType.NONE
            sig_meta = {
                k: v
                for k, v in sig.items()
                if k not in ("side", "prob_long", "prob_short", "close_price", "position_size")
            }
            signals[name] = SignalResult(
                asset=name,
                signal_type=signal_type,
                probability=max(sig.get("prob_long", 0.0), sig.get("prob_short", 0.0)),
                entry_price=sig.get("close_price", 0.0),
                position_size=sig.get("position_size", 0.0),
                metadata=sig_meta,
            )

        return CycleResult(
            cycle_id=self._cycle_count,
            duration_ms=round(duration, 2),
            signals=signals,
            health=raw.get("orchestrator_health"),
            circuit_breaker=raw.get("orchestrator_circuit_breaker"),
            errors=[self._last_error] if self._last_error else [],
        )

    def shutdown(self) -> None:
        """Gracefully shut down the engine and release resources."""
        if not self._engine:
            return
        try:
            self._engine.shutdown()
        except (OSError, RuntimeError, AttributeError) as exc:
            logger.error("EngineService.shutdown() error: %s", exc)
        self._is_running = False
        self._engine = None
        logger.info("EngineService shut down")

    def get_status(self) -> EngineStatus:
        """Return an immutable snapshot of current engine status."""
        if not self._engine:
            return EngineStatus(
                is_running=False,
                cycle_count=self._cycle_count,
                emergency_halt=False,
                last_update=None,
                total_equity=None,
                portfolio_value=None,
                n_assets=0,
            )
        n_assets = len(getattr(self._engine, "assets", {}) or {})
        return EngineStatus(
            is_running=self._is_running,
            cycle_count=self._cycle_count,
            emergency_halt=getattr(self._engine, "emergency_halt", False),
            last_update=getattr(self._engine, "last_update", None),
            total_equity=self._get_total_equity(),
            portfolio_value=self._get_portfolio_value(),
            n_assets=n_assets,
        )

    # ── Helpers ─────────────────────────────────────────────────────────────

    def _get_total_equity(self) -> float | None:
        if not self._engine:
            return None
        try:
            return float(getattr(self._engine, "_cycle_total_equity", None) or 0.0) or None
        except (TypeError, ValueError):
            return None

    def _get_portfolio_value(self) -> float | None:
        if not self._engine:
            return None
        try:
            orch = getattr(self._engine, "_orchestrator", None)
            if orch:
                return orch.get_total_portfolio_value()
            return getattr(self._engine, "portfolio_peak_value", None)
        except (TypeError, ValueError):
            return None

    @property
    def is_running(self) -> bool:
        return self._is_running

    @property
    def last_error(self) -> str | None:
        return self._last_error

    @property
    def cycle_count(self) -> int:
        return self._cycle_count
