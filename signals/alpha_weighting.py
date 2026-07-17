"""DEPRECATED — moved to ``archive.deprecated._alpha_weighting``.

Ensemble system disabled (ADR-026).  Kept as a backward-compatible shim.
Will be removed in v4.0.
"""

import warnings

from archive.deprecated._alpha_weighting import *  # noqa: F401, F403

warnings.warn(
    "signals.alpha_weighting is deprecated. Ensemble disabled per ADR-026.",
    DeprecationWarning,
    stacklevel=2,
)
