"""Deprecated — import from ``labels.compat`` instead."""
import warnings

from labels.compat import PurgedWalkForwardFolds, triple_barrier_labels  # noqa: F401

warnings.warn(
    "features.labels is deprecated. Use labels.compat for legacy functions "
    "or labels.triple_barrier for the vectorized implementation.",
    DeprecationWarning,
    stacklevel=2,
)
