"""Gap-through detection and partial fill degradation.

Only degrades outcomes, never improves them.
All randomness seeded and deterministic.
"""

from __future__ import annotations

import hashlib
import logging
import random

from shared.execution_config import ExecutionConfig

logger = logging.getLogger("eigencapital.fill_model")


class FillModel:
    """Seeded fill simulation — gap-through and partial fill degradation.

    Gap-through: if price gaps beyond stop level, fill at open price.
    Partial fills: reduce fill quantity when vol exceeds thresholds.
    """

    def __init__(self, seed: int = 42):
        self._rng = random.Random(seed + 1)

    def recreate(self, seed: int) -> FillModel:
        return FillModel(seed)

    def check_gap_through(
        self,
        open_price: float,
        trigger_price: float,
        order_side: str,
    ) -> bool:
        """Returns True if price gapped through the trigger level.

        A stop-loss sell (protecting a long) gaps through when
        the open is BELOW the stop (worse fill).
        A stop-loss buy (protecting a short) gaps through when
        the open is ABOVE the stop (worse fill).

        Parameters
        ----------
        open_price : float
            The open price of the gap/candle.
        trigger_price : float
            The stop-loss price level.
        order_side : str
            The order side: "sell" for long-stop, "buy" for short-stop.
        """
        if order_side == "sell":
            return open_price <= trigger_price
        else:
            return open_price >= trigger_price

    def gap_fill_price(
        self,
        open_price: float,
        trigger_price: float,
        order_side: str,
    ) -> float:
        """Fill price when gap-through occurs.

        Always the WORST of open or trigger for the position.
        """
        if order_side == "sell":
            return min(open_price, trigger_price)
        else:
            return max(open_price, trigger_price)

    def fill_qty_fraction(
        self,
        requested_qty: float,
        vol_zscore: float,
        config: ExecutionConfig,
    ) -> float:
        """Return the actual fill quantity (may be degraded).

        Deterministic function of vol_zscore — no RNG dependency.
        Degradation increases with vol z-score above threshold.
        Never returns more than requested_qty.
        """
        if vol_zscore <= config.fill_vol_threshold or requested_qty <= 0:
            return requested_qty

        excess = vol_zscore - config.fill_vol_threshold
        slope = abs(config.fill_prob_slope) if config.fill_prob_slope < 0 else config.fill_prob_slope
        reduction = min(slope * excess, 1.0 - config.min_fill_prob)
        fill_prob = max(config.min_fill_prob, 1.0 - reduction)
        return float(requested_qty * fill_prob)

    def seed_hash(self) -> str:
        h = hashlib.md5(str(self._rng.getstate()).encode())
        return h.hexdigest()[:12]
