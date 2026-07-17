"""DEPRECATED — moved to ``archive.deprecated._position_sizing``.

Kept as a backward-compatible shim.  Will be removed in v4.0.
"""

import warnings

from archive.deprecated._position_sizing import (  # noqa: F401
    calculate_position_size,
)

warnings.warn(
    "risk.position_sizing is deprecated. Use paper_trading.entry.EntryService instead.",
    DeprecationWarning,
    stacklevel=2,
)
