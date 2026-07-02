"""ECETracker — online calibration quality monitoring.

Tracks per-asset ECE over a rolling window of probability-outcome pairs.
Exposes drift detection (ECE exceeding threshold) for alerting and
dashboard display.

This is the MONITORING side — it doesn't modify probabilities, only
reports on the quality of the current calibration.
"""

from __future__ import annotations

import logging
from collections import deque
from dataclasses import dataclass, field
from typing import Any

import numpy as np

from shared.calibration.calibrator import compute_ece

logger = logging.getLogger("eigencapital.calibration.ece_tracker")


@dataclass
class ECEState:
    """Per-asset ECE tracking state."""

    window_size: int = 200
    preds: deque[float] = field(default_factory=lambda: deque(maxlen=200))
    outcomes: deque[int] = field(default_factory=lambda: deque(maxlen=200))
    last_ece: float | None = None
    drift_alert: bool = False
    drift_persistent: bool = False  # True if drift sustained > 10 observations
    _drift_count: int = 0

    def record(self, prob: float, outcome: int) -> None:
        self.preds.append(prob)
        self.outcomes.append(outcome)

    def ece(self, n_bins: int = 10) -> float | None:
        if len(self.preds) < 20:
            return None
        return compute_ece(
            np.array(list(self.preds), dtype=float),
            np.array(list(self.outcomes), dtype=int),
            n_bins=n_bins,
        )


class ECETracker:
    """Tracks ECE per asset over a rolling window.

    Usage:
        tracker = ECETracker(window=200, drift_threshold=0.15)
        tracker.record("EURUSD", 0.72, 1)  # p_long=0.72, TP hit
        ece = tracker.get_ece("EURUSD")
        alerts = tracker.drift_alerts()
    """

    def __init__(self, window: int = 200, drift_threshold: float = 0.15):
        self.window = window
        self.drift_threshold = drift_threshold
        self._assets: dict[str, ECEState] = {}

    def record(self, asset: str, prob: float, outcome: int) -> None:
        """Record a single probability-outcome pair.

        Args:
            asset: Asset name
            prob: Calibrated (or raw) P(LONG) used for the decision
            outcome: 1 if TP hit (correct long), 0 if SL hit (correct short)
        """
        if asset not in self._assets:
            self._assets[asset] = ECEState(window_size=self.window)
        self._assets[asset].record(prob, outcome)

    def get_ece(self, asset: str, n_bins: int = 10) -> float | None:
        """Get current ECE for an asset, or None if insufficient data."""
        state = self._assets.get(asset)
        if state is None:
            return None
        return state.ece(n_bins=n_bins)

    def update_drift(self, asset: str) -> bool:
        """Check if asset has drifted beyond threshold. Returns True if drifted."""
        state = self._assets.get(asset)
        if state is None:
            return False
        ece_val = state.ece()
        state.last_ece = ece_val
        if ece_val is None:
            state.drift_alert = False
            return False
        drifted = ece_val > self.drift_threshold
        if drifted:
            state._drift_count += 1
            if state._drift_count >= 10:
                state.drift_persistent = True
                if not state.drift_alert:
                    state.drift_alert = True
                    logger.warning(
                        "CALIBRATION DRIFT on %s: ECE=%.4f > threshold=%.2f",
                        asset,
                        ece_val,
                        self.drift_threshold,
                    )
        else:
            state._drift_count = 0
            state.drift_persistent = False
            if state.drift_alert:
                state.drift_alert = False
                state.drift_persistent = False
                logger.info("Calibration drift CLEARED for %s: ECE=%.4f", asset, ece_val)
        return drifted

    def drift_alerts(self) -> dict[str, dict[str, Any]]:
        """Return dict of currently-alerted assets with their ECE states."""
        result: dict[str, dict[str, Any]] = {}
        for asset, state in self._assets.items():
            if state.drift_alert:
                result[asset] = {
                    "ece": state.last_ece,
                    "persistent": state.drift_persistent,
                    "n_samples": len(state.preds),
                }
        return result

    def summary(self) -> dict[str, Any]:
        """Full summary for state.json exposure."""
        return {
            "window": self.window,
            "drift_threshold": self.drift_threshold,
            "ece_by_asset": {asset: self._asset_summary(state) for asset, state in self._assets.items()},
            "drift_alerts": self.drift_alerts(),
        }

    def _asset_summary(self, state: ECEState) -> dict[str, Any]:
        ece_val = state.ece()
        return {
            "ece": ece_val,
            "n_samples": len(state.preds),
            "drift_alert": state.drift_alert,
            "drift_persistent": state.drift_persistent,
        }

    def status(self) -> dict[str, Any]:
        return {
            "ece_tracker": f"window={self.window}, drift_threshold={self.drift_threshold}",
            "assets_tracked": len(self._assets),
            "assets_with_ece": sum(1 for s in self._assets.values() if s.ece() is not None),
            "drift_alerts": len(self.drift_alerts()),
        }
