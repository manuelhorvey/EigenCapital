"""DEPRECATED — moved to ``archive.deprecated._divergence``.

Kept as a backward-compatible shim.  Will be removed in v4.0.
"""

import warnings

from archive.deprecated._divergence import *  # noqa: F401, F403

warnings.warn(
    "features.divergence is deprecated. Use features.alpha_features instead.",
    DeprecationWarning,
    stacklevel=2,
)
