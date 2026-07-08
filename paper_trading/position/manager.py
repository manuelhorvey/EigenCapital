import logging
from copy import deepcopy  # noqa: F401  — kept for backward-compatible downstream callers
from dataclasses import replace
from datetime import datetime

import pandas as pd

from paper_trading.entry.decision import PositionIntent

logger = logging.getLogger("eigencapital.position_manager")

# Cap trade_log to prevent unbounded memory growth.
_MAX_TRADE_LOG = 10_000


class PositionManager:
    """
    Owns the position lifecycle: open, close, SL/TP checks, PnL, scale-out,
    trailing stop, and post-entry adjustment.

    Pure state machine — no I/O, no model inference.
    """

    def __init__(self, initial_capital: float, position_size: float = 0.95):
        self.initial_capital = initial_capital
        self.current_value = initial_capital
        self.peak_value = initial_capital
        self.position_size = position_size
        self.exposure_multiplier = 1.0
        self.position: PositionIntent | None = None
        self.trade_log: list = []

        # Scale-out state
        self._scale_out_active: bool = False
        self._scale_out_breakeven: float | None = None
        self._remaining_fraction: float = 1.0
        self._partial_closes: list[dict] = []
        # Actual notional deployed at entry (from sizing chain).
        self._entry_notional: float = 0.0

    # ── Position lifecycle ────────────────────────────────────────

    def open(self, intent: PositionIntent) -> None:
        self.position = intent
        if intent.base_entry_size <= 0:
            intent.base_entry_size = self.position_size
        self._entry_notional = (
            intent.entry_notional if intent.entry_notional > 0 else self.current_value * self.position_size
        )
        self._scale_out_active = False
        self._scale_out_breakeven = None
        self._remaining_fraction = 1.0
        self._partial_closes = []

    def close(self, exit_price: float, exit_date: str, reason: str) -> dict | None:
        if self.position is None:
            return None
        side = self.position.side
        entry = self.position.entry_price

        if pd.isna(entry) or pd.isna(exit_price) or entry <= 0 or exit_price <= 0:
            logger.error("Invalid close entry=%s exit=%s", entry, exit_price)
            return None

        fraction = self._remaining_fraction
        ret = (exit_price / entry - 1) if side == "long" else (entry / exit_price - 1)
        pnl = self._entry_notional * ret * fraction

        try:
            bars = max(0, (pd.Timestamp(exit_date) - pd.Timestamp(self.position.entry_date)).days)
        except (ValueError, TypeError, AttributeError):
            bars = 1

        risk_pct = (
            abs(entry - self.position.stop_loss) / entry if self.position and self.position.stop_loss != entry else 0.0
        )
        total_pnl_realized = pnl + sum(pc.get("pnl", 0.0) for pc in self._partial_closes)

        logger.debug(
            "%s CLOSE: side=%s entry=%.4f exit=%.4f ret=%.4f%% pnl=%.2f reason=%s "
            "current_value_before=%.2f entry_notional=%.2f exposure=%.4f",
            getattr(self.position, "_asset_name", "?"),
            side,
            entry,
            exit_price,
            ret * 100,
            pnl,
            reason,
            self.current_value,
            self._entry_notional,
            self.exposure_multiplier,
        )

        trade = {
            "asset": "",
            "side": side,
            "entry": entry,
            "exit": exit_price,
            "entry_date": self.position.entry_date,
            "exit_date": exit_date,
            "bars": bars,
            "return": ret,
            "pnl": pnl,
            "total_pnl": total_pnl_realized,
            "reason": reason,
            "sl_price": self.position.stop_loss if self.position else None,
            "tp_price": self.position.take_profit if self.position else None,
            "vol_at_entry": self.position.vol if self.position else None,
            "realized_r": round(ret / risk_pct, 4) if risk_pct > 0 else 0.0,
            "partial_closes": list(self._partial_closes),
            "fraction_closed": fraction,
        }
        if len(self.trade_log) >= _MAX_TRADE_LOG:
            self.trade_log.pop(0)
        self.trade_log.append(trade)
        self.current_value += pnl
        self.position = None
        self._remaining_fraction = 0.0
        if self.current_value > self.peak_value:
            self.peak_value = self.current_value

        # All partial closes are settled immediately in partial_close(),
        # so this loop is intentionally empty — kept as documentation.
        # If partial_close ever defers settlement, re-enable:
        # for pc in self._partial_closes:
        #     if not pc.get("settled", False):
        #         self.current_value += pc["pnl"]
        #         pc["settled"] = True

        return trade

    # ── SL/TP checks ──────────────────────────────────────────────

    def check_sl_tp(self, current_price: float) -> tuple[str, float] | None:
        if self.position is None:
            return None

        # Check breakeven stop (from scale-out)
        if (
            self._scale_out_breakeven is not None
            and self._remaining_fraction > 0
            and (
                self.position.side == "long"
                and current_price <= self._scale_out_breakeven
                or self.position.side == "short"
                and current_price >= self._scale_out_breakeven
            )
        ):
            return ("breakeven", self._scale_out_breakeven)

        sl = self.position.effective_sl
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

    # ── Dynamic SL/TP adjustment ──────────────────────────────────

    def update_stop_loss(self, new_sl: float) -> bool:
        """Update the stop-loss level. Returns True if accepted."""
        if self.position is None:
            return False
        if pd.isna(new_sl):
            logger.error("Cannot update stop loss to NaN")
            return False
        # dataclasses.replace is faster than deepcopy: copies only the wrapped
        # fields without recursing into list-of-StackLayer or default factories.
        self.position = replace(self.position, stop_loss=new_sl)
        return True

    def update_take_profit(self, new_tp: float) -> bool:
        """Update the take-profit level. Returns True if accepted."""
        if self.position is None:
            return False
        if pd.isna(new_tp):
            logger.error("Cannot update take profit to NaN")
            return False
        self.position = replace(self.position, take_profit=new_tp)
        return True

    # ── Scale-out (partial close) ─────────────────────────────────

    def partial_close(self, fraction: float, fill_price: float, exit_date: str, reason: str) -> dict | None:
        """Close a fraction of the current position.

        Returns trade dict for the partial close, or None on failure.
        """
        if self.position is None or fraction <= 0 or fraction > self._remaining_fraction:
            return None

        side = self.position.side
        entry = self.position.entry_price
        ret = (fill_price / entry - 1) if side == "long" else (entry / fill_price - 1)
        pnl = self._entry_notional * ret * fraction

        pc = {
            "fraction": fraction,
            "fill_price": fill_price,
            "exit_date": exit_date,
            "reason": reason,
            "return": ret,
            "pnl": pnl,
            "settled": True,
        }
        self._partial_closes.append(pc)
        self._remaining_fraction -= fraction
        self.current_value += pnl
        if self.current_value > self.peak_value:
            self.peak_value = self.current_value

        logger.info(
            "Partial close: %.1f%% @ %.4f (reason=%s, pnl=%.2f, remaining=%.1f%%)",
            fraction * 100,
            fill_price,
            reason,
            pnl,
            self._remaining_fraction * 100,
        )
        return pc

    def activate_breakeven_stop(self) -> bool:
        """Move the remaining position's effective stop to entry price."""
        if self.position is None or self._remaining_fraction <= 0:
            return False
        self._scale_out_active = True
        self._scale_out_breakeven = self.position.entry_price
        logger.info("Breakeven stop activated for remaining %.1f%%", self._remaining_fraction * 100)
        return True

    # ── Stacking helpers ──────────────────────────────────────────

    def last_stack_time(self) -> datetime | None:
        if self.position is None or not self.position.layers:
            return None
        last = self.position.layers[-1]
        try:
            return datetime.fromisoformat(last.timestamp)
        except (ValueError, TypeError, AttributeError):
            return None

    def max_layers_reached(self, max_layers: int) -> bool:
        if self.position is None:
            return True
        return len(self.position.layers) >= max_layers

    def stack_layer_count(self) -> int:
        if self.position is None:
            return 0
        return max(0, len(self.position.layers) - 1)

    def enforce_invariant(self, asset_name: str = "?") -> bool:
        if self.position is None:
            return True
        return self.position.enforce_invariant(asset_name)

    # ── Market / position state hooks (pre-wired for future use) ──
    @property
    def regime(self) -> str:
        return getattr(self, "_regime", "neutral")

    @regime.setter
    def regime(self, value: str) -> None:
        self._regime = value

    @property
    def volatility_state(self) -> str:
        return getattr(self, "_volatility_state", "normal")

    @volatility_state.setter
    def volatility_state(self, value: str) -> None:
        self._volatility_state = value

    # ── Queries ───────────────────────────────────────────────────

    def position_pnl(self, current_price: float) -> float:
        if self.position is None or not current_price:
            return 0.0
        if self.position.side == "long":
            return (current_price / self.position.entry_price - 1) * 100
        else:
            return (self.position.entry_price / current_price - 1) * 100

    def current_side(self) -> str | None:
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
        self._entry_notional = 0.0
        self._scale_out_active = False
        self._scale_out_breakeven = None
        self._remaining_fraction = 1.0
        self._partial_closes = []
        self._regime = "neutral"
        self._volatility_state = "normal"

    def position_count(self) -> int:
        return 1 if self.position is not None else 0

    def max_positions_reached(self, max_positions: int) -> bool:
        if max_positions <= 0:
            return True
        return self.position_count() >= max_positions

    def get_remaining_fraction(self) -> float:
        return self._remaining_fraction
