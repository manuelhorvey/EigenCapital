"""HaltState — encapsulated emergency halt state machine and peak tracking.

Extracted from ``EngineOrchestrator`` as part of MAINT-01 (split oversized
modules).  Owns the halt state flags, peak portfolio value tracking,
auto-unhalt eligibility logic, and persistent halt warning throttling.

Does NOT own actor iteration — the orchestrator passes actor references
when needed (e.g., ``reset_actors``, ``flatten_positions``).

Usage:
    halt_state = HaltState()
    halt_state.restore_from_snapshot(snapshot, init_equity, config)
    halt_state.update_peak(total_value)
    if halt_state.emergency_halt:
        if halt_state.check_auto_unhalt(...):
            resume_normal_operation(...)
"""

from __future__ import annotations

import logging
from typing import Any

from eigencapital.domain.time import utc_now

logger = logging.getLogger("eigencapital.orchestrator.halt_state")

# Drawdown recovery threshold for automatic unhalt (must be above trip
# threshold to avoid flapping).  Named separate constant — must NOT be
# derived from the drawdown_limit so the hysteresis gap is explicit.
DRAWDOWN_AUTO_UNHALT_THRESHOLD = -0.05  # -5% — recover above this to be eligible
DRAWDOWN_AUTO_UNHALT_MIN_CYCLES = 10  # must show recovery for N consecutive cycles

# Reasons that are eligible for automatic unhalt when drawdown recovers.
# halt_ratio and vol_spike require manual reset.
HALT_REASON_AUTO_UNHALT_ALLOWED: frozenset[str] = frozenset(
    {
        "DRAWDOWN",
        "CONSECUTIVE_LOSSES",
    }
)


class HaltState:
    """Encapsulated emergency halt state machine and peak portfolio tracking.

    Owns:
        - Emergency halt flags (``emergency_halt``, ``halt_reason``, ``halt_detail``)
        - Peak portfolio value (``peak_portfolio_value``)
        - Auto-unhalt recovery cycles counter
        - Persistent halt warning throttling

    Delegates to orchestrator:
        - Actor resets (``reset_actors``)
        - Position flattening (``flatten_positions``)

    Lifecycle:
        - ``restore_from_snapshot()`` — re-anchor peak, auto-clear stale halt
        - ``update_peak()`` — monotonic peak update
        - ``maybe_warn_persistent()`` — throttled warning log
        - ``check_auto_unhalt()`` — attempt automatic recovery
        - ``set_halt()`` / ``reset()`` — state transitions
    """

    def __init__(self) -> None:
        # Set by the orchestrator; we accept via param or set directly
        self.emergency_halt: bool = False
        self.halt_reason: str | None = None
        self.halt_detail: str = ""
        self.peak_portfolio_value: float | None = None
        self.unhalt_recovery_cycles: int = 0
        self.halt_warn_last_cycle: int = -10  # throttling guard

    def restore_from_snapshot(
        self,
        snapshot: Any,
        init_equity: float | None,
        capital: float,
        peak_capital_base: float | None = None,
    ) -> None:
        """Re-anchor peak from persisted snapshot and auto-clear stale halts.

        Call during orchestrator init **before** the first cycle.  Handles:
            1. Peak re-anchoring when capital base changed between sessions
            2. Phantom drawdown clamp when portfolio composition changed
            3. Safety clamp ensuring peak >= current equity
            4. Auto-clear of stale emergency halt (equity >= 99% of peak)

        ``snapshot`` must have ``emergency_halt``, ``halt_reason``,
        ``halt_detail``, ``peak_portfolio_value``, ``peak_capital_base``,
        ``breaker_daily_pnl`` attributes (may be None).
        """
        if snapshot is None:
            self._reanchor_peak(init_equity, None, capital, None)
            return

        # 1. Restore halt flags from snapshot
        if getattr(snapshot, "emergency_halt", False):
            self.emergency_halt = True
            raw_reason = getattr(snapshot, "halt_reason", None)
            if raw_reason:
                self.halt_reason = str(raw_reason)
            self.halt_detail = getattr(snapshot, "halt_detail", "")

        # 2. Restore and re-anchor peak
        persisted_peak = getattr(snapshot, "peak_portfolio_value", None)
        if persisted_peak is not None:
            self.peak_portfolio_value = persisted_peak

        self._reanchor_peak(
            init_equity,
            self.peak_portfolio_value,
            capital,
            peak_capital_base or getattr(snapshot, "peak_capital_base", None),
        )

    def _reanchor_peak(
        self,
        init_equity: float | None,
        persisted_peak: float | None,
        capital: float,
        peak_capital_base_val: float | None,
    ) -> None:
        """Inner re-anchor logic shared by snapshot restore and init-only paths."""
        # 1. Capital ratio adjustment
        if peak_capital_base_val is not None and self.peak_portfolio_value is not None and peak_capital_base_val > 0:
            capital_ratio = capital / peak_capital_base_val
            self.peak_portfolio_value *= capital_ratio
            logger.info(
                "Peak re-anchored from %.2f (at peak_capital_base=%.2f) to %.2f (at capital=%.2f, ratio=%.4f)",
                persisted_peak or 0.0,
                peak_capital_base_val,
                self.peak_portfolio_value,
                capital,
                capital_ratio,
            )

        # 2. Phantom drawdown clamp (>15% on startup = composition change)
        if (
            self.peak_portfolio_value is not None
            and init_equity is not None
            and init_equity > 0
        ):
            dd_from_peak = (init_equity - self.peak_portfolio_value) / self.peak_portfolio_value
            if dd_from_peak < -0.15:
                logger.warning(
                    "Peak re-anchoring produced drawdown=%.2f%% on startup "
                    "(peak=%.2f, equity=%.2f) — likely due to portfolio composition "
                    "change. Re-anchoring peak to current equity.",
                    dd_from_peak * 100,
                    self.peak_portfolio_value,
                    init_equity,
                )
                self.peak_portfolio_value = init_equity

        # 3. Safety clamp: peak >= current equity
        if init_equity is not None and init_equity > 0 and (
            self.peak_portfolio_value is None or init_equity > self.peak_portfolio_value
        ):
            self.peak_portfolio_value = init_equity

    def auto_clear_stale_halt(
        self, init_equity: float | None, alert_callback: Any = None
    ) -> bool:
        """Auto-clear stale emergency halt if equity >= 99% of peak.

        Returns True if the halt was cleared.  Only applies when
        ``halt_reason`` is in ``HALT_REASON_AUTO_UNHALT_ALLOWED``.

        ``alert_callback`` is an optional callable ``(title, msg, details)``
        for dispatching a warning alert.
        """
        if not self.emergency_halt:
            return False
        if self.halt_reason not in HALT_REASON_AUTO_UNHALT_ALLOWED:
            return False
        if self.peak_portfolio_value is None or self.peak_portfolio_value <= 0:
            return False
        if init_equity is None:
            return False

        live_vs_peak = init_equity / max(self.peak_portfolio_value, 1.0)
        if live_vs_peak >= 0.99:
            logger.warning(
                "Stale emergency halt auto-cleared at startup — "
                "live_equity=%.2f peak=%.2f ratio=%.4f reason=%s detail=%s",
                init_equity,
                self.peak_portfolio_value,
                live_vs_peak,
                self.halt_reason or "unknown",
                self.halt_detail or "(empty)",
            )
            if alert_callback is not None:
                try:
                    alert_callback(
                        "Stale emergency halt auto-cleared on restart",
                        (
                            f"live_equity={init_equity:.2f} peak={self.peak_portfolio_value:.2f} "
                            f"ratio={live_vs_peak:.4f} reason={self.halt_reason}"
                        ),
                        details={
                            "live_equity": round(init_equity, 2),
                            "peak": round(self.peak_portfolio_value, 2) if self.peak_portfolio_value else None,
                            "ratio": round(live_vs_peak, 4),
                            "reason": self.halt_reason or "",
                            "detail": self.halt_detail,
                        },
                    )
                except (TypeError, ValueError):
                    logger.exception("Auto-clear alert callback failed")
            self.emergency_halt = False
            self.halt_reason = None
            self.halt_detail = ""
            return True
        return False

    def update_peak(self, total_value: float) -> None:
        """Update peak portfolio value (monotonic increase only)."""
        if self.peak_portfolio_value is None:
            self.peak_portfolio_value = total_value
        else:
            self.peak_portfolio_value = max(self.peak_portfolio_value, total_value)

    def set_halt(self, reason: str, detail: str) -> None:
        """Transition to emergency halt state."""
        self.emergency_halt = True
        self.halt_reason = reason
        self.halt_detail = detail
        self.unhalt_recovery_cycles = 0

    def reset(self) -> None:
        """Clear halt state (manual or auto-unhalt)."""
        self.emergency_halt = False
        self.halt_reason = None
        self.halt_detail = ""
        self.unhalt_recovery_cycles = 0

    def maybe_warn_persistent(
        self, cycles_elapsed: int, total_equity: float | None = None
    ) -> None:
        """Emit throttled WARNING when stuck in halt-persistent mode.

        Fires on throttle schedule (every 10 cycles) regardless of halt state.
        The caller guard (``_run_phases``) checks ``emergency_halt`` before
        calling this method — consistent with the original orchestrator design.
        No mutation — observability only.
        """
        if cycles_elapsed - self.halt_warn_last_cycle < 10:
            return
        self.halt_warn_last_cycle = cycles_elapsed
        logger.warning(
            "emergency_halt_persistent — cycle=%d reason=%s detail=%s peak=%s live_mtm=%s",
            cycles_elapsed,
            self.halt_reason or "unknown",
            self.halt_detail or "(empty)",
            f"{self.peak_portfolio_value:.2f}" if self.peak_portfolio_value is not None else "None",
            f"{total_equity:.2f}" if total_equity is not None else "None",
        )

    def check_auto_unhalt(
        self,
        cycles_elapsed: int,
        total_equity: float | None,
    ) -> bool:
        """Check if emergency halt can be automatically lifted.

        Eligible reasons: DRAWDOWN, CONSECUTIVE_LOSSES.
        Must show sustained recovery above DRAWDOWN_AUTO_UNHALT_THRESHOLD
        for DRAWDOWN_AUTO_UNHALT_MIN_CYCLES consecutive cycles.

        Returns True if the halt was lifted (caller should resume actors).
        """
        if not self.emergency_halt:
            return False
        if self.halt_reason not in HALT_REASON_AUTO_UNHALT_ALLOWED:
            return False
        if cycles_elapsed < 1:
            return False
        if self.peak_portfolio_value is None or self.peak_portfolio_value <= 0:
            return False
        if total_equity is None:
            return False

        current_dd = (total_equity - self.peak_portfolio_value) / self.peak_portfolio_value

        if current_dd >= DRAWDOWN_AUTO_UNHALT_THRESHOLD:
            self.unhalt_recovery_cycles += 1
            if self.unhalt_recovery_cycles >= DRAWDOWN_AUTO_UNHALT_MIN_CYCLES:
                logger.warning(
                    "AUTO-UNHALT: drawdown recovered from %s to %.2f%% "
                    "(threshold %.2f%%) after %d cycles — resuming normal operation",
                    self.halt_detail,
                    current_dd * 100,
                    DRAWDOWN_AUTO_UNHALT_THRESHOLD * 100,
                    self.unhalt_recovery_cycles,
                )
                self.emergency_halt = False
                self.halt_reason = None
                self.halt_detail = ""
                self.unhalt_recovery_cycles = 0
                return True
        else:
            self.unhalt_recovery_cycles = 0
        return False

    @property
    def drawdown_pct(self) -> float:
        """Current drawdown percentage from peak (negative = below peak)."""
        # Can't compute without live equity — caller must pass it
        return 0.0

    def snapshot_dict(self) -> dict[str, Any]:
        """Return halt state as dict for WAL/dashboard export."""
        return {
            "emergency_halt": self.emergency_halt,
            "halt_reason": self.halt_reason or "",
            "halt_detail": self.halt_detail,
            "peak_portfolio_value": round(self.peak_portfolio_value, 2) if self.peak_portfolio_value else None,
            "unhalt_recovery_cycles": self.unhalt_recovery_cycles,
        }
