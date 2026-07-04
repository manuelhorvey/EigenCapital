"""OutcomeTracker — tracks recent trade outcomes for the Performance State Model.

Tracks win rate, R-multiples, streaks, and adverse/favorable excursion
over a rolling window of completed trades. Updated after Phase 4 each cycle."""

from __future__ import annotations

import threading
from collections import deque
from typing import Any


class OutcomeTracker:
    """Tracks the last N trade outcomes for a single asset (or portfolio-level pool).
    Window size is configurable (default 20 trades). Thread-safe."""

    def __init__(self, window: int = 20):
        self._window = window
        self._outcomes: deque[dict[str, Any]] = deque(maxlen=window)
        self._consecutive_losses = 0
        self._r_sum = 0.0
        self._lock = threading.RLock()

    def record_trade(
        self,
        exit_reason: str,  # "TP" | "SL" | "manual" | "circuit_breaker"
        r_multiple: float,
        mae_pct: float,
        mfe_pct: float,
    ) -> None:
        """Record a completed trade outcome."""
        with self._lock:
            is_win = exit_reason == "TP"
            self._outcomes.append(
                {
                    "exit_reason": exit_reason,
                    "r_multiple": r_multiple,
                    "mae_pct": mae_pct,
                    "mfe_pct": mfe_pct,
                    "is_win": is_win,
                }
            )
            if is_win:
                self._consecutive_losses = 0
            else:
                self._consecutive_losses += 1
            self._r_sum = sum(o["r_multiple"] for o in self._outcomes)

    def reset(self) -> None:
        with self._lock:
            self._outcomes.clear()
            self._consecutive_losses = 0
            self._r_sum = 0.0

    @property
    def win_rate(self) -> float:
        with self._lock:
            if not self._outcomes:
                return 0.0
            return sum(1 for o in self._outcomes if o["is_win"]) / len(self._outcomes)

    @property
    def consecutive_losses(self) -> int:
        with self._lock:
            return self._consecutive_losses

    @property
    def r_cumulative(self) -> float:
        with self._lock:
            return self._r_sum

    @property
    def avg_mae(self) -> float:
        with self._lock:
            if not self._outcomes:
                return 0.0
            return sum(o["mae_pct"] for o in self._outcomes) / len(self._outcomes)

    @property
    def avg_mfe(self) -> float:
        with self._lock:
            if not self._outcomes:
                return 0.0
            return sum(o["mfe_pct"] for o in self._outcomes) / len(self._outcomes)

    @property
    def trade_count(self) -> int:
        with self._lock:
            return len(self._outcomes)

    def outcome_scalar(self) -> float:
        """Compute outcome scalar in [0.3, 1.2] based on recent performance."""
        with self._lock:
            wr = self.win_rate
        consec = self.consecutive_losses
        r_cum = self.r_cumulative

        # Hard tighten on streaks
        if consec >= 5:
            return 0.3
        if consec >= 3:
            return 0.5

        # Mild tighten on poor win rate with negative R
        if wr < 0.40 and r_cum < 0:
            return 0.5

        # Neutral
        if 0.40 <= wr <= 0.55:
            return 1.0

        # Mild expansion on good win rate with positive R and no streak
        if wr > 0.55 and consec == 0 and r_cum > 3.0:
            return 1.1

        # Full expansion on strong performance
        if wr > 0.60 and consec == 0 and r_cum > 6.0:
            return 1.2

        return 1.0
