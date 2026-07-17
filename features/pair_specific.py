"""DEPRECATED — moved to ``archive.deprecated._pair_specific``.

Kept as a backward-compatible shim.  Will be removed in v4.0.
"""

import warnings

from archive.deprecated._pair_specific import (  # noqa: F401
    build_eurusd_features,
    build_gc_features,
    build_lead_lag_features,
    build_nzdjpy_features,
    build_usdjpy_features,
    yf_download_safe,
)

warnings.warn(
    "features.pair_specific is deprecated. Use features.alpha_features instead.",
    DeprecationWarning,
    stacklevel=2,
)
