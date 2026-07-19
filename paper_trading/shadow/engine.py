"""Shadow SL/TP engine — isolated counterfactual replay of execution outcomes.

Architectural invariant
-----------------------
Shadow engines consume immutable execution artifacts and never share mutable
state with the live engine.  They replay the same market tape as the live
position but with alternative SL/TP parameters.

This enables online counterfactual research without contaminating:
  - replayability
  - attribution purity
  - governance stability
  - frozen execution contracts

::

    Live:  DynamicSLTPEngine -> PositionManager -> trade close (mutates capital)
    Shadow: ShadowSLTPEngine -> shadow buffer      (zero side effects)
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Literal

import pandas as pd

from paper_trading.position.dynamic_sltp import DynamicSLTPEngine, SLTPResult, TrailingResult
from paper_trading.position.manager import PositionManager
from shared.volatility import VolatilityPrimitive

logger = logging.getLogger("eigencapital.shadow_sltp")

ShadowExitReason = Literal["sl", "tp", "breakeven", "time_stop", "trailing", "signal_flip"]


@dataclass
class ShadowTradeRecord:
    """Counterfactual trade outcome under alternative SL/TP parameters.

    Records what WOULD have happened with different SL/TP settings
    on the exact same price path.  Zero effect on live state.
    """

    asset: str
    side: str
    entry_price: float
    entry_date: str
    exit_price: float
    exit_date: str
    exit_reason: ShadowExitReason
    bars_held: int
    realized_r: float
    sl_price: float
    tp_price: float
    alt_label: str  # which shadow configuration was used
    live_exit_reason: str  # what the live engine actually did
    live_realized_r: float
    mae: float = 0.0
    mfe: float = 0.0


class ShadowSLTPEngine:
    """Parallel-universe SL/TP evaluator.

    Each instance carries its own ``DynamicSLTPEngine`` and ``PositionManager``
    so replay can never leak into live state.  Replay is driven by the
    same price ticks the live engine sees.

    Parameters
    ----------
    name : str
        Label for this shadow configuration (e.g. ``"tight_trail"``).
    alt_engine : DynamicSLTPEngine
        Alternative SL/TP engine with different parameters.
    alt_vol_primitive : VolatilityPrimitive | None
        Alternative volatility primitive for barrier computation.
    """

    def __init__(
        self,
        name: str,
        alt_engine: DynamicSLTPEngine,
        alt_vol_primitive: VolatilityPrimitive | None = None,
    ):
        self.name = name
        self.alt_engine = alt_engine
        self.alt_vol_primitive = alt_vol_primitive
        # Isolated state — never shared with live engine
        self._shadow_pos_mgr: PositionManager | None = None
        self._shadow_entry_price: float = 0.0
        self._shadow_side: str = ""
        self._shadow_entry_date: str = ""
        self._shadow_bars: int = 0
        self._shadow_initial_sl: float = 0.0
        self._shadow_initial_tp: float = 0.0
        self._shadow_best_price: float = 0.0
        self._shadow_vol: float = 0.01
        self._shadow_active: bool = False
        self.shadow_trades: list[ShadowTradeRecord] = []
        self._max_seen: float = 0.0
        self._min_seen: float = float("inf")

    # ── Lifecycle ───────────────────────────────────────────────────

    def record_entry(
        self,
        side: str,
        entry_price: float,
        entry_date: str,
        df: pd.DataFrame,
        sl_mult: float,
        tp_mult: float,
        regime: str = "neutral",
        meta_confidence: float | None = None,
    ) -> None:
        """Record a hypothetical entry with this shadow's alternative params.

        Must be called at the same time as the live engine opens a position.
        """
        # Compute shadow barriers using this engine's params
        sltp_result: SLTPResult = self.alt_engine.compute_barriers(
            entry_price=entry_price,
            side=side,
            df=df,
            sl_mult=sl_mult,
            tp_mult=tp_mult,
            regime=regime,
            meta_confidence=meta_confidence,
        )

        self._shadow_entry_price = entry_price
        self._shadow_side = side
        self._shadow_entry_date = entry_date
        self._shadow_bars = 0
        self._shadow_initial_sl = float(sltp_result.stop_loss)
        self._shadow_initial_tp = float(sltp_result.take_profit)
        self._shadow_best_price = entry_price
        self._shadow_vol = sltp_result.stop_loss  # placeholder
        self._shadow_active = True
        self._max_seen = entry_price
        self._min_seen = entry_price

        self.alt_engine.reset_best_price(entry_price)

        logger.debug(
            "shadow[%s]: recorded entry at %.4f, sl=%.4f, tp=%.4f",
            self.name,
            entry_price,
            sltp_result.stop_loss,
            sltp_result.take_profit,
        )

    def tick(self, current_price: float, df: pd.DataFrame, date: str) -> None:
        """Process one price tick — check shadow SL/TP and trailing.

        Must be called on every live refresh while the shadow is active.
        Returns nothing — results are accumulated in ``shadow_trades``.
        """
        if not self._shadow_active:
            return

        self._shadow_bars += 1
        self._max_seen = max(self._max_seen, current_price)
        self._min_seen = min(self._min_seen, current_price)

        sl = self._shadow_initial_sl
        tp = self._shadow_initial_tp
        side = self._shadow_side

        # Check SL/TP hit
        if side == "long":
            if sl is not None and current_price <= sl:
                self._close_shadow(current_price, date, "sl")
                return
            if tp is not None and current_price >= tp:
                self._close_shadow(current_price, date, "tp")
                return
        else:
            if sl is not None and current_price >= sl:
                self._close_shadow(current_price, date, "sl")
                return
            if tp is not None and current_price <= tp:
                self._close_shadow(current_price, date, "tp")
                return

        # Check trailing stop (if this engine has trailing enabled)
        trailing: TrailingResult = self.alt_engine.compute_trailing_stop(
            side=side,
            entry_price=self._shadow_entry_price,
            current_price=current_price,
            initial_sl=self._shadow_initial_sl,
            current_sl=sl,
            take_profit=tp,
            df=df,
        )
        if trailing.trailing_sl is not None:
            self._close_shadow(trailing.trailing_sl, date, "trailing")

    def close_shadow(self, exit_price: float, date: str, reason: str) -> None:
        """Force-close the shadow position (e.g. when live engine closes)."""
        if self._shadow_active:
            self._close_shadow(exit_price, date, reason)  # type: ignore[arg-type]

    # ── Internal ────────────────────────────────────────────────────

    def _close_shadow(self, exit_price: float, exit_date: str, reason: ShadowExitReason) -> None:
        if not self._shadow_active:
            return

        side = self._shadow_side
        entry = self._shadow_entry_price
        sl_dist = abs(entry - self._shadow_initial_sl)

        ret = (exit_price / entry - 1) if side == "long" else (entry / exit_price - 1)
        realized_r = round(ret / (sl_dist / entry + 1e-9), 4) if sl_dist > 0 else 0.0
        mae = abs(self._min_seen - entry) / entry if side == "long" else abs(entry - self._max_seen) / entry
        mfe = abs(self._max_seen - entry) / entry if side == "long" else abs(entry - self._min_seen) / entry

        record = ShadowTradeRecord(
            asset="",
            side=side,
            entry_price=entry,
            entry_date=self._shadow_entry_date,
            exit_price=exit_price,
            exit_date=exit_date,
            exit_reason=reason,
            bars_held=self._shadow_bars,
            realized_r=realized_r,
            sl_price=self._shadow_initial_sl,
            tp_price=self._shadow_initial_tp,
            alt_label=self.name,
            live_exit_reason="",
            live_realized_r=0.0,
            mae=round(mae, 6),
            mfe=round(mfe, 6),
        )
        self.shadow_trades.append(record)

        logger.debug(
            "shadow[%s]: closed at %.4f (reason=%s, R=%.2f, bars=%d)",
            self.name,
            exit_price,
            reason,
            realized_r,
            self._shadow_bars,
        )
        self._shadow_active = False

    def flush_completed(self, asset_name: str = "") -> list[ShadowTradeRecord]:
        """Return and clear all completed shadow trades, setting asset name.

        This is the read-once pattern for persisting shadow results to durable
        storage without keeping them in memory.
        """
        records = list(self.shadow_trades)
        for r in records:
            if not r.asset:
                r.asset = asset_name
        self.shadow_trades.clear()
        return records

    def set_live_outcome(self, exit_reason: str, realized_r: float) -> None:
        """Attach the live outcome to the most recent shadow trade for comparison."""
        if self.shadow_trades:
            self.shadow_trades[-1].live_exit_reason = exit_reason
            self.shadow_trades[-1].live_realized_r = realized_r

    @property
    def is_active(self) -> bool:
        return self._shadow_active

    def reset(self) -> None:
        """Clear shadow state (e.g. at engine reset or retrain cycle)."""
        self._shadow_active = False
        self._shadow_entry_price = 0.0
        self._shadow_side = ""
        self._shadow_bars = 0
        self._shadow_initial_sl = 0.0
        self._shadow_initial_tp = 0.0
        self._shadow_best_price = 0.0
        self.shadow_trades = []
        self._max_seen = 0.0
        self._min_seen = float("inf")

    def summary(self) -> dict:
        """Return aggregate comparison metrics for this shadow configuration."""
        if not self.shadow_trades:
            return {"name": self.name, "n_trades": 0}

        df = pd.DataFrame([t.__dict__ for t in self.shadow_trades])
        n = len(df)
        sl_rate = (df["exit_reason"] == "sl").mean()
        tp_rate = (df["exit_reason"] == "tp").mean()
        avg_r = df["realized_r"].mean()
        win_rate = (df["realized_r"] > 0).mean()

        return {
            "name": self.name,
            "n_trades": n,
            "sl_rate": round(float(sl_rate), 4),
            "tp_rate": round(float(tp_rate), 4),
            "avg_r": round(float(avg_r), 4),
            "win_rate": round(float(win_rate), 4),
            "total_r": round(float(df["realized_r"].sum()), 4),
        }
