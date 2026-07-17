"""DEPRECATED — moved to ``archive.deprecated._cot_features``.

Kept as a backward-compatible shim.  Will be removed in v4.0.
"""

import warnings

from archive.deprecated._cot_features import cot_index  # noqa: F401

warnings.warn(
    "features.cot_features is deprecated. COT features were removed in 2026-07-09.",
    DeprecationWarning,
    stacklevel=2,
)
