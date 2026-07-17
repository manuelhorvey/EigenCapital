"""DEPRECATED — import from ``labels.compat`` or ``labels.triple_barrier`` instead.

Kept as a backward-compatible shim.  Will be removed in v4.0.
"""

import warnings

from labels.compat import PurgedWalkForwardFolds, triple_barrier_labels  # noqa: F401

warnings.warn(
    "features.labels is deprecated. Use labels.compat (legacy) or labels.triple_barrier instead.",
    DeprecationWarning,
    stacklevel=2,
)
