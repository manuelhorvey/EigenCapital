import logging
from typing import Optional, Tuple

import numpy as np
import pandas as pd

from paper_trading.decision import PositionIntent

logger = logging.getLogger("quantforge.position_manager")


class PositionManager:
    """
    Owns the position lifecycle: open, close, SL/TP checks, PnL.
    Pure state machine — no I/O, no model inference.
    """

    def __init__(self, initial_capital: float, position_size: float = 0.95):
        self.initial_capital = initial_capital
        self.current_value = initial_capital
        self.peak_value = initial_capital
        self.position_size = position_size
        self.exposure_multiplier = 1.0
        self.position: Optional[PositionIntent] = None
        self.trade_log: list = []

    def open(self, intent: PositionIntent) -> None:
        self.position = intent

    def close(self, exit_price: float, exit_date: str, reason: str) -> Optional[dict]:
        if self.position is None:
            return None
        side = self.position.side
        entry = self.position.entry_price
        if pd.isna(entry) or pd.isna(exit_price) or entry <= 0 or exit_price <= 0:
            logger.error("Invalid close entry=%s exit=%s", entry, exit_price)
            return None
        ret = (exit_price / entry - 1) if side == "long" else (entry / exit_price - 1)
        pnl = self.current_value * ret * self.position_size * self.exposure_multiplier
        trade = {
            "asset": "",
            "side": side,
            "entry": entry,
            "exit": exit_price,
            "entry_date": self.position.entry_date,
            "exit_date": exit_date,
            "return": ret,
            "pnl": pnl,
            "reason": reason,
        }
        self.trade_log.append(trade)
        self.current_value += pnl
        self.position = None
        if self.current_value > self.peak_value:
            self.peak_value = self.current_value
        return trade

    def check_sl_tp(self, current_price: float) -> Optional[Tuple[str, float]]:
        if self.position is None:
            return None
        sl = self.position.stop_loss
        tp = self.position.take_profit
        side = self.position.side
        if pd.isna(sl) or pd.isna(tp) or pd.isna(current_price):
            return None
        if side == "long":
            if current_price <= sl:
                return ("sl", sl)
            elif current_price >= tp:
                return ("tp", tp)
        else:
            if current_price >= sl:
                return ("sl", sl)
            elif current_price <= tp:
                return ("tp", tp)
        return None

    def position_pnl(self, current_price: float) -> float:
        if self.position is None:
            return 0.0
        if self.position.side == "long":
            return (current_price / self.position.entry_price - 1) * 100
        else:
            return (self.position.entry_price / current_price - 1) * 100

    def current_side(self) -> Optional[str]:
        return self.position.side if self.position else None

    def has_position(self) -> bool:
        return self.position is not None

    def compute_daily_pnl(self, direction: int, ret: float, pos_size: float = 1.0) -> float:
        return self.current_value * direction * ret * self.position_size * pos_size * self.exposure_multiplier

    def apply_pnl(self, pnl: float) -> None:
        self.current_value += pnl
        if self.current_value > self.peak_value:
            self.peak_value = self.current_value

    def reset(self, capital: float) -> None:
        self.initial_capital = capital
        self.current_value = capital
        self.peak_value = capital
        self.position = None
        self.trade_log = []
