"""Risk governance — delegate to RiskRegistry from risk_registry.

This module now delegates all state to a default RiskRegistry instance
for backward compatibility.  New code should import RiskRegistry directly
from risk_registry and instantiate its own instance.
"""

from __future__ import annotations

from paper_trading.governance.risk_registry import (
    FLAG_THRESHOLD,
    SL_HIT_RATE_ALERT,
    SL_HIT_RATE_CRITICAL,
    SL_HIT_RATE_WINDOW,
    TRIPWIRE_THRESHOLD,
    WEIGHTS,
    RiskRegistry,  # noqa: F401
    _default_registry,
)

# ── Module-level constants (preserved for external importers) ───────────

SELL_WIN_RATE_WINDOW = 20
SL_HIT_RATE_WINDOW = SL_HIT_RATE_WINDOW
SL_HIT_RATE_ALERT = SL_HIT_RATE_ALERT
SL_HIT_RATE_CRITICAL = SL_HIT_RATE_CRITICAL
TRIPWIRE_THRESHOLD = TRIPWIRE_THRESHOLD
FLAG_THRESHOLD = FLAG_THRESHOLD
WEIGHTS = WEIGHTS

# ── Delegate module-level functions to the default registry ────────────

reset = _default_registry.reset
record_trade_outcome = _default_registry.record_trade_outcome
get_sl_hit_rate = _default_registry.get_sl_hit_rate
get_sl_hit_rate_all = _default_registry.get_sl_hit_rate_all
record_sell_side_outcome = _default_registry.record_sell_side_outcome
get_sell_win_rate = _default_registry.get_sell_win_rate
get_sell_tripwire_state = _default_registry.get_sell_tripwire_state
get_risk_state = _default_registry.snapshot_state
set_risk_state = _default_registry.restore_state
evaluate = _default_registry.evaluate
get_latest = _default_registry.get_latest

# Internal state / helper access for test compatibility (private, may be removed)
_cache = _default_registry._cache
_generate_explanations = RiskRegistry._generate_explanations
