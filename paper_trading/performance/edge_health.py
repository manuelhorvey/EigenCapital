"""
EdgeHealthMonitor — Live structural edge health tracking.

Tracks the system's key structural metric: reversal rate = fraction of losing
trades where price reached meaningful MFE (>= 1R) before reversing to SL.

A declining reversal rate is the only remaining unknown failure mode —
it signals that the MFE distribution on which adaptive exits depend is
structurally degrading.

Usage:
    monitor = EdgeHealthMonitor()
    # On each trade close:
    monitor.record_trade(asset="AUDUSD", side="long", entry_price=1.0, ...)
    state = monitor.summary  # dict for state.json
"""

from __future__ import annotations

import logging
from collections import deque
from typing import Any

import numpy as np

logger = logging.getLogger("eigencapital.edge_health")

_DEFAULT_MAX_TRADES = 200
_DEFAULT_WARNING_THRESHOLD = 0.15  # reversal rate below 15% triggers WARNING


class EdgeHealthMonitor:
    """Rolling-window structural edge health tracker.

    Key metric: reversal_rate = losers_with_MFE_ge_1R / total_losers
    Rolling window prevents single-period dominance.
    """

    def __init__(
        self,
        max_trades: int = _DEFAULT_MAX_TRADES,
        warning_threshold: float = _DEFAULT_WARNING_THRESHOLD,
    ) -> None:
        self.max_trades = max_trades
        self.warning_threshold = warning_threshold
        self._trades: deque[dict[str, Any]] = deque(maxlen=max_trades)
        self._alert_active: bool = False

    def record_trade(
        self,
        asset: str,
        side: str,
        entry_price: float,
        exit_price: float,
        exit_reason: str,
        realized_r: float,
        peak_mfe_r: float | None = None,
    ) -> None:
        """Record a closed trade for edge health tracking."""
        is_loser = realized_r < 0
        had_mfe = (peak_mfe_r or 0.0) >= 1.0

        record = {
            "asset": asset,
            "side": side,
            "exit_reason": exit_reason,
            "entry_price": entry_price,
            "exit_price": exit_price,
            "realized_r": round(realized_r, 4),
            "peak_mfe_r": round(peak_mfe_r or 0.0, 4),
            "is_loser": is_loser,
            "had_mfe_ge_1r": had_mfe,
        }
        self._trades.append(record)
        self._check_alert()

    def _check_alert(self) -> None:
        rate = self.reversal_rate
        if rate is None:
            return
        was_active = self._alert_active
        self._alert_active = rate < self.warning_threshold
        if self._alert_active and not was_active:
            logger.warning(
                "EdgeHealth: reversal rate dropped to %.1f%% (threshold %.1f%%) — structural MFE base may be degrading",
                rate * 100,
                self.warning_threshold * 100,
            )
        elif was_active and not self._alert_active:
            logger.info(
                "EdgeHealth: reversal rate recovered to %.1f%% (above %.1f%% threshold)",
                rate * 100,
                self.warning_threshold * 100,
            )

    @property
    def reversal_rate(self) -> float | None:
        """Fraction of losing trades that had MFE >= 1R before reversing."""
        losers = [t for t in self._trades if t["is_loser"]]
        if not losers:
            return None
        reversed_losers = sum(1 for t in losers if t["had_mfe_ge_1r"])
        return reversed_losers / len(losers)

    @property
    def summary(self) -> dict[str, Any]:
        """Current edge health state — suitable for state.json."""
        rate = self.reversal_rate
        losers = [t for t in self._trades if t["is_loser"]]
        mfe_vals = [t["peak_mfe_r"] for t in self._trades if t["peak_mfe_r"] is not None]

        result: dict[str, Any] = {
            "n_trades": len(self._trades),
            "n_losers": len(losers),
            "n_reversal_candidates": sum(1 for t in losers if t["had_mfe_ge_1r"]),
            "reversal_rate": round(rate, 4) if rate is not None else None,
            "warning_threshold": self.warning_threshold,
            "alert": self._alert_active,
        }
        if mfe_vals:
            result["mean_mfe_r"] = round(float(np.mean(mfe_vals)), 4)
            result["median_mfe_r"] = round(float(np.median(mfe_vals)), 4)
        else:
            result["mean_mfe_r"] = None
            result["median_mfe_r"] = None

        return result


# ── Global singleton ────────────────────────────────────────────────────────

_monitor: EdgeHealthMonitor | None = None


def get_monitor() -> EdgeHealthMonitor:
    global _monitor
    if _monitor is None:
        _monitor = EdgeHealthMonitor()
    return _monitor


def reset_monitor() -> None:
    global _monitor
    _monitor = None
