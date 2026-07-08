"""PositionBatch — per-entry tracked position with independent trailing lifecycle.

Each batch represents a single entry (anchor or runner) with its own
DynamicSLTPEngine instance, stop-loss tracking, and role-based trailing
configuration.  The ``asset.batches`` dict (keyed by ``trade_id``) is the
single source of truth for all open positions on an asset.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any

logger = logging.getLogger("eigencapital.position_batch")


@dataclass
class PositionBatch:
    """A single entry batch with independent trailing stop management.

    Parameters
    ----------
    trade_id : str
        Unique identifier for this batch (e.g. ``2026-07-08_long_XAUUSD_1``).
    role : str
        ``"anchor"`` for the base position, ``"runner"`` for stacked entries.
    is_anchor : bool
        Convenience flag; ``True`` only for the first entry on an asset.
    side : str
        ``"long"`` or ``"short"``.
    entry_price : float
        Fill price for this batch (immutable).
    entry_date : str
        ISO date of entry (immutable).
    vol : float
        Size of this batch (units).
    initial_sl : float
        Stop-loss at entry time (immutable reference for distance calc).
    initial_tp : float
        Take-profit at entry time (immutable reference).
    stop_loss : float
        Current effective stop-loss (mutated by trailing/adjust).
    take_profit : float
        Current effective take-profit (mutated by trailing/adjust).
    position_dict : dict
        The dict representation consumed by MT5 bridge and dashboard.
    sltp_engine : DynamicSLTPEngine | None
        Own trailing-stop engine (per-batch independent state).
    adaptive_exit_engine : AdaptiveExitEngine | None
        Own adaptive exit engine (per-batch independent state).
    bars_since_entry : int
        Number of bars elapsed since this batch was opened.
    """

    trade_id: str
    role: str
    is_anchor: bool
    side: str
    entry_price: float
    entry_date: str
    vol: float
    initial_sl: float
    initial_tp: float
    stop_loss: float
    take_profit: float
    position_dict: dict
    sltp_engine: Any = None  # DynamicSLTPEngine — avoid circular import at class level
    adaptive_exit_engine: Any = None  # AdaptiveExitEngine
    bars_since_entry: int = 0

    @property
    def is_long(self) -> bool:
        return self.side == "long"

    @property
    def is_short(self) -> bool:
        return self.side == "short"

    def update_stop_loss(self, new_sl: float) -> None:
        """Update the batch-level stop loss and sync to the dict."""
        self.stop_loss = new_sl
        self.position_dict["sl"] = new_sl

    def update_take_profit(self, new_tp: float) -> None:
        """Update the batch-level take profit and sync to the dict."""
        self.take_profit = new_tp
        self.position_dict["tp"] = new_tp
