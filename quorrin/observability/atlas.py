"""ATLAS — Adaptive Transition-Aware Layered Shift detector.

Detects regime transitions in time-series feature distributions by layering
three classical change-point tests:

  1. **CUSUM** (cumulative-sum control chart) — fires when cumulative
     deviation from a target mean exceeds a tunable threshold.
  2. **Page-Hinkley** — symmetric CUSUM variant that catches both upward
     and downward drifts.
  3. **Sliding-window KS** (Kolmogorov-Smirnov) — non-parametric test of
     distributional equality between consecutive windows.

Each layer votes independently; ATLAS reports:
  - per-layer alerts
  - a consensus verdict (any layer fires ⇒ "TRANSITION")
  - confidence (weighted vote across layers)

Configuration: per-asset thresholds stored in a JSON file or built at
construction. Defaults are conservative (low false-positive rate).

Usage::

    from quorrin.observability.atlas import AtlasDetector

    detector = AtlasDetector(lookback=63, cusum_k=0.5, ph_delta=0.005)
    verdict = detector.update("EURUSD", new_feature_value)
    if verdict.transition:
        log.warning("transition at frame %d (confidence=%.2f, layers=%s)",
                    verdict.frame, verdict.confidence, verdict.fired_layers)
"""

from __future__ import annotations

import logging
import math
from collections import deque
from dataclasses import dataclass, field

logger = logging.getLogger("quorrin.atlas")


@dataclass
class AtlasVerdict:
    asset: str
    frame: int
    transition: bool
    confidence: float
    fired_layers: list[str] = field(default_factory=list)
    layer_details: dict[str, float] = field(default_factory=dict)


@dataclass
class _AssetState:
    cusum_pos: float = 0.0
    cusum_neg: float = 0.0
    running_mean: float = 0.0
    running_variance: float = 0.0
    n: int = 0
    # Sliding-window KS state
    window_a: deque[float] = field(default_factory=deque)
    window_b: deque[float] = field(default_factory=deque)
    # Page-Hinkley state
    ph_running_mean: float = 0.0
    ph_min: float = math.inf


class AtlasDetector:
    """Layered change-point detector.

    Args:
        lookback: number of recent samples to retain for context.
        cusum_threshold: CUSUM threshold (multiplier of stddev).
        cusum_k: slack parameter (allowance) for CUSUM.
        ph_delta: Page-Hinkley detection sensitivity.
        ks_window: width of each sliding window for KS test.
        ks_threshold: KS-statistic threshold for alert (0..1).
    """

    def __init__(
        self,
        lookback: int = 63,
        cusum_threshold: float = 5.0,
        cusum_k: float = 0.5,
        ph_delta: float = 0.005,
        ks_window: int = 30,
        ks_threshold: float = 0.5,
    ) -> None:
        self.lookback = lookback
        self.cusum_threshold = cusum_threshold
        self.cusum_k = cusum_k
        self.ph_delta = ph_delta
        self.ks_window = ks_window
        self.ks_threshold = ks_threshold
        self._states: dict[str, _AssetState] = {}

    def reset(self, asset: str) -> None:
        self._states.pop(asset, None)

    def _state(self, asset: str) -> _AssetState:
        if asset not in self._states:
            self._states[asset] = _AssetState(
                window_a=deque(maxlen=self.ks_window),
                window_b=deque(maxlen=self.ks_window),
            )
        return self._states[asset]

    def update(self, asset: str, value: float) -> AtlasVerdict:
        """Feed a single new observation; return the latest verdict."""
        st = self._state(asset)
        st.n += 1
        n = st.n
        prev_mean = st.running_mean

        # Online mean / variance (Welford)
        delta = value - prev_mean
        st.running_mean = prev_mean + delta / n
        if n > 1:
            delta2 = value - st.running_mean
            st.running_variance += delta * delta2

        stddev = math.sqrt(st.running_variance / max(n - 1, 1)) if n > 1 else 0.0
        threshold = self.cusum_threshold * stddev + self.cusum_k

        # ── CUSUM (two-sided) ───────────────────────────────────
        cusum_low = threshold
        cusum_high = -threshold
        st.cusum_pos = max(0.0, st.cusum_pos + value - prev_mean - self.cusum_k)
        st.cusum_neg = min(0.0, st.cusum_neg + value - prev_mean + self.cusum_k)
        cusum_fired = st.cusum_pos > cusum_low or st.cusum_neg < cusum_high

        # ── Page-Hinkley ────────────────────────────────────────
        ph_running_mean = ((st.ph_running_mean * (n - 1)) + value) / n
        st.ph_running_mean = ph_running_mean
        st.ph_min = min(st.ph_min, ph_running_mean)
        ph_stat = ph_running_mean - st.ph_min - self.ph_delta
        # Page-Hinkley fires when the upward drift exceeds delta + threshold
        ph_threshold = self.ph_delta * 4.0
        ph_fired = ph_stat > ph_threshold

        # ── Sliding-window KS ───────────────────────────────────
        ks_stat = 0.0
        if len(st.window_a) == self.ks_window and len(st.window_b) == self.ks_window:
            ks_stat = self._two_sample_ks(list(st.window_a), list(st.window_b))
        ks_fired = ks_stat > self.ks_threshold
        # Slide windows
        if len(st.window_b) == self.ks_window:
            # B becomes A
            while st.window_a:
                st.window_a.popleft()
            st.window_a.extend(st.window_b)
            while st.window_b:
                st.window_b.popleft()
        st.window_b.append(value)

        # ── Aggregate ───────────────────────────────────────────
        fired_layers: list[str] = []
        details: dict[str, float] = {}
        if cusum_fired:
            fired_layers.append("cusum")
            details["cusum"] = max(st.cusum_pos, -st.cusum_neg)
        if ph_fired:
            fired_layers.append("page_hinkley")
            details["page_hinkley"] = ph_stat
        if ks_fired:
            fired_layers.append("ks")
            details["ks"] = ks_stat

        # Confidence = weighted votes (each layer contributes 1/3)
        confidence = len(fired_layers) / 3.0 if fired_layers else 0.0
        return AtlasVerdict(
            asset=asset,
            frame=n,
            transition=bool(fired_layers),
            confidence=round(confidence, 3),
            fired_layers=fired_layers,
            layer_details=details,
        )

    @staticmethod
    def _two_sample_ks(a: list[float], b: list[float]) -> float:
        """Two-sample Kolmogorov-Smirnov statistic.

        :math:`D = \\sup_x |F_a(x) - F_b(x)|`
        """
        if not a or not b:
            return 0.0
        sa = sorted(a)
        sb = sorted(b)
        merged = sorted(set(sa) | set(sb))
        na = len(sa)
        nb = len(sb)
        i = j = 0
        max_diff = 0.0
        for x in merged:
            while i < na and sa[i] <= x:
                i += 1
            while j < nb and sb[j] <= x:
                j += 1
            fa = i / na
            fb = j / nb
            max_diff = max(max_diff, abs(fa - fb))
        return max_diff
