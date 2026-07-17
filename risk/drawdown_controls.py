"""DEPRECATED — moved to ``archive.deprecated._drawdown_controls``.

Kept as a backward-compatible shim.  Will be removed in v4.0.
"""

import warnings

from archive.deprecated._drawdown_controls import (  # noqa: F401
    check_drawdown_circuit_breaker,
    compute_drawdown,
    compute_exposure_multiplier,
)

warnings.warn(
    "risk.drawdown_controls is deprecated. Use paper_trading.governance.drawdown_controls instead.",
    DeprecationWarning,
    stacklevel=2,
)
