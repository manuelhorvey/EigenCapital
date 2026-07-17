"""DEPRECATED — legacy threshold-based signal logic.

This module is no longer used in production.  Signal generation now flows
through ``paper_trading/inference/pipeline.py`` -> ``run_decision_pipeline``.

Kept for backward compatibility with existing tests and scripts.
Will be removed in a future release.
"""

import warnings

import numpy as np

warnings.warn(
    "signals.simple_threshold is deprecated and will be removed.",
    DeprecationWarning,
    stacklevel=2,
)

# Backward-compatible API (preserved for existing tests/scripts)
THRESHOLD = 0.475


def generate_signals(probs: np.ndarray) -> np.ndarray:
    """Generate signals from probabilities (deprecated — use decision pipeline)."""
    signals = np.zeros(len(probs), dtype=np.int8)
    signals[probs[:, 2] > THRESHOLD] = 1
    signals[probs[:, 0] > THRESHOLD] = -1
    return signals
