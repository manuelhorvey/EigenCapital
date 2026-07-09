"""Deterministic execution delay model.

Only degrades outcomes, never improves them.
All randomness seeded and deterministic.
"""

from __future__ import annotations

import hashlib
import logging
import random

from shared.execution_config import ExecutionConfig

logger = logging.getLogger("eigencapital.latency_model")


class LatencyModel:
    """Seeded execution delay — introduces bar-level latency under high vol.

    Latency only activates when vol z-score exceeds threshold.
    Delay is deterministic for a given seed + vol_zscore.
    """

    def __init__(self, seed: int = 42):
        self._rng = random.Random(seed + 2)

    def recreate(self, seed: int) -> LatencyModel:
        return LatencyModel(seed)

    def execution_delay_bars(
        self,
        vol_zscore: float,
        config: ExecutionConfig,
    ) -> int:
        """Return number of bars of execution delay.

        Zero when vol is below threshold.
        Up to delay_bars_max when vol is elevated.
        """
        if vol_zscore <= config.delay_vol_threshold:
            return 0

        max_delay = config.delay_bars_max
        if max_delay <= 0:
            return 0

        delay = self._rng.randint(0, max_delay)
        return delay

    def seed_hash(self) -> str:
        h = hashlib.md5(str(self._rng.getstate()).encode())  # nosec
        return h.hexdigest()[:12]
