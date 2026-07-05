from __future__ import annotations

import logging
from typing import Final

from paper_trading.config_manager import get_config

logger = logging.getLogger("eigencapital.gate_constants")


def get_sell_only_assets() -> frozenset[str]:
    """Return SELL_ONLY_ASSETS from config.

    The config source of truth lives in paper_trading.yaml under
    ``defaults.sell_only_assets``. Config must be loaded before this
    function is called; if it is not, an error is raised because silently
    falling back would disable the BUY inversion safety filter.

    Raises
    ------
    RuntimeError
        If config is not yet loaded or is missing the sell_only_assets field.
    """
    cfg = get_config()
    if not cfg.sell_only_assets:
        raise RuntimeError(
            "SELL_ONLY_ASSETS not configured. Ensure paper_trading.yaml has defaults.sell_only_assets defined."
        )
    return cfg.sell_only_assets


# Legacy compatibility alias — prefer get_sell_only_assets() in new code.
# Kept for backward compat with existing imports; will be removed after
# all callers migrate to the function.
SELL_ONLY_ASSETS: Final[frozenset[str]] = get_sell_only_assets()

SPREAD_TIER_BPS: Final[dict[str, float]] = {
    "fx_major": 10.0,
    "fx_cross": 20.0,
    "indices": 15.0,
    "metals": 20.0,
}

SPREAD_GATE_STALENESS_SECS: Final[int] = 300
