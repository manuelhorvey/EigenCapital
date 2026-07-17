"""DEPRECATED — legacy drawdown controls module.

Replaced by ``paper_trading/governance/drawdown_controls.py`` which provides
identical functions. This module is kept as a thin re-export wrapper for
backward compatibility with existing scripts and tests.

The orchestrator (``EngineOrchestrator``) imports directly from
``paper_trading.governance.drawdown_controls`` — no production code uses this
module.

Will be removed in a future release.
"""

import warnings

# Re-export all public symbols from the canonical module
from paper_trading.governance.drawdown_controls import (  # noqa: F401
    check_drawdown_circuit_breaker,
    compute_drawdown,
    compute_exposure_multiplier,
)

warnings.warn(
    "risk.drawdown_controls is deprecated. Use paper_trading.governance.drawdown_controls instead.",
    DeprecationWarning,
    stacklevel=2,
)
