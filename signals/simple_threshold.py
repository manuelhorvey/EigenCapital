"""DEPRECATED — moved to ``archive.deprecated._simple_threshold``.

Kept as a backward-compatible shim.  Will be removed in v4.0.
"""

import warnings

from archive.deprecated._simple_threshold import (  # noqa: F401
    THRESHOLD,
    generate_signals,
)

warnings.warn(
    "signals.simple_threshold is deprecated. Use paper_trading.inference.pipeline instead.",
    DeprecationWarning,
    stacklevel=2,
)
