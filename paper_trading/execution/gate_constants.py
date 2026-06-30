from __future__ import annotations

import logging
from typing import Final

from paper_trading.config_manager import get_config

logger = logging.getLogger("quorrin.gate_constants")


def get_sell_only_assets() -> frozenset[str]:
    """Return SELL_ONLY_ASSETS from config, falling back to hardcoded set.

    The config source of truth lives in paper_trading.yaml under
    ``defaults.sell_only_assets``.  If config is not yet loaded (e.g. during
    import time), falls back to the known hardcoded 5-asset set derived from
    the 2026-06-26 walk-forward analysis.  Once config is loaded, the config
    value takes precedence.
    """
    try:
        cfg = get_config()
        if cfg.sell_only_assets:
            return cfg.sell_only_assets
    except Exception:
        logger.debug("Config not yet available — using hardcoded SELL_ONLY_ASSETS", exc_info=True)
    # Hardcoded fallback: 5 assets with confirmed inverted BUY signal
    return frozenset(
        {
            "CADCHF",
            "ES",
            "NQ",
            "NZDCHF",
            "EURAUD",
        }
    )


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
