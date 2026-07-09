"""Asymmetric slippage model — SL worse, TP neutral, all deterministic.

Sits AFTER PolicyDecision freeze.
Only degrades outcomes, never improves them.
All functions are pure (no RNG) for deterministic replay.
"""

from __future__ import annotations

import hashlib
import logging

from shared.execution_config import ExecutionConfig

logger = logging.getLogger("eigencapital.slippage_model")


class SlippageModel:
    """Deterministic asymmetric slippage engine.

    All functions are pure functions of (price, vol_zscore, config) —
    no RNG, no mutable state. This ensures deterministic replay:
    same inputs → same FillResult regardless of call order.
    """

    def __init__(self, seed: int = 42):
        self._seed = seed

    def recreate(self, seed: int) -> SlippageModel:
        return SlippageModel(seed)

    def _slip_bps(self, base_bps: float, vol_zscore: float, config: ExecutionConfig) -> float:
        excess = max(0.0, vol_zscore - 1.0)
        slip = base_bps * (1.0 + config.spread_vol_slope * excess)
        slip = min(slip, config.spread_max_bps)
        return slip / 10000.0

    def entry_slippage(self, mid_price: float, vol_zscore: float, config: ExecutionConfig) -> float:
        """Deterministic entry slippage — pure function of mid, vol, config."""
        base = config.base_spread_bps
        slip_decimal = self._slip_bps(base, vol_zscore, config)
        return float(min(slip_decimal, config.spread_max_bps / 10000.0))

    def stop_loss_slippage(self, stop_price: float, vol_zscore: float, config: ExecutionConfig, side: str) -> float:
        """Adverse slippage on stop-loss fills — deterministic, pure function.

        Returns a POSITIVE slippage factor in price units.
        For longs:  fill = stop - factor  (worse)
        For shorts: fill = stop + factor  (worse)
        """
        base_bps = config.base_spread_bps * 0.5
        slip_decimal = self._slip_bps(base_bps, vol_zscore, config)
        slip_decimal *= 1.5  # SL penalty: 1.5x worse than entry
        total = min(slip_decimal, config.spread_max_bps * 1.5 / 10000.0)
        return float(stop_price * total)

    def take_profit_slippage(self, target_price: float, config: ExecutionConfig) -> float:
        """Slightly adverse slippage on take-profit fills (limit orders) — deterministic.

        Returns a small non-negative slippage factor in price units.
        Always adverse (never favorable, never zero), but much smaller than
        entry or stop-loss slippage (0.1x spread vs 1.0x/1.5x).

        Note: the docstring says 'neutral' but this is a documentation imprecision
        from an earlier version.  The function has always been degradation-only.
        """
        base_bps = config.base_spread_bps * 0.1
        slip_decimal = base_bps / 10000.0
        return float(target_price * slip_decimal)

    def seed_hash(self) -> str:
        return hashlib.md5(str(self._seed).encode()).hexdigest()[:12]  # nosec
