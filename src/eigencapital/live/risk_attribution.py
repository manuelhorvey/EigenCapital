"""Risk Outcome Attribution — connects risk state to realized trade outcomes.

Builds the dataset needed to answer:
"When EigenCapital took risk, did its risk system understand the risk correctly,
react correctly, and improve the outcome?"

Data flow:
  risk observation → risk decision → position state → market evolution
  → MAE/MFE → exit → realized P&L → counterfactual P&L

This module is Phase 2 infrastructure — it collects the data needed to
validate REDUCED and other risk interventions BEFORE they go live.

Shadow mode:
  During Phase 2, all REDUCED decisions are recorded as shadow decisions.
  This module enriches those records with subsequent market data to build
  the attribution dataset.
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any, Dict, List


@dataclass(frozen=True)
class TradeAttribution:
    """Attribution record for a single trade lifecycle."""

    ticket: int
    symbol: str
    direction: str
    entry_time: str
    entry_price: float
    entry_size: float

    # Risk state at entry
    equity_at_entry: float
    drawdown_at_entry: float
    risk_level_at_entry: str
    scale_factor_applied: float
    scale_factor_reason: str

    # Outcome
    exit_time: str | None = None
    exit_price: float | None = None
    realized_pnl: float | None = None

    # Risk metrics during holding period
    mae: float | None = None  # Maximum Adverse Excursion
    mfe: float | None = None  # Maximum Favorable Excursion
    holding_days: float | None = None

    # Counterfactual (what REDUCED would have done)
    counterfactual_size: float | None = None
    counterfactual_pnl: float | None = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "ticket": self.ticket,
            "symbol": self.symbol,
            "direction": self.direction,
            "entry_time": self.entry_time,
            "entry_price": self.entry_price,
            "entry_size": self.entry_size,
            "equity_at_entry": self.equity_at_entry,
            "drawdown_at_entry": self.drawdown_at_entry,
            "risk_level_at_entry": self.risk_level_at_entry,
            "scale_factor_applied": self.scale_factor_applied,
            "scale_factor_reason": self.scale_factor_reason,
            "exit_time": self.exit_time,
            "exit_price": self.exit_price,
            "realized_pnl": self.realized_pnl,
            "mae": self.mae,
            "mfe": self.mfe,
            "holding_days": self.holding_days,
            "counterfactual_size": self.counterfactual_size,
            "counterfactual_pnl": self.counterfactual_pnl,
        }


class RiskOutcomeAttribution:
    """Collects and analyzes risk-outcome attribution data.

    During Phase 2, this is a passive collector — it records risk state
    at trade entry and enriches records when trades close. It does NOT
    modify any trading behavior.
    """

    def __init__(self, data_dir: str = "reports/r4_qualification/attribution") -> None:
        self._data_dir = data_dir
        self._active_trades: Dict[int, Dict[str, Any]] = {}
        self._closed_trades: List[Dict[str, Any]] = []
        os.makedirs(data_dir, exist_ok=True)

    def record_trade_entry(
        self,
        ticket: int,
        symbol: str,
        direction: str,
        entry_price: float,
        entry_size: float,
        equity: float,
        drawdown_pct: float,
        risk_level: str,
        scale_factor: float,
        scale_reason: str,
    ) -> None:
        """Record risk state at trade entry.

        Called when a new position is opened. Captures the risk context
        that existed when the trade was initiated.
        """
        self._active_trades[ticket] = {
            "ticket": ticket,
            "symbol": symbol,
            "direction": direction,
            "entry_time": datetime.now(UTC).isoformat(),
            "entry_price": entry_price,
            "entry_size": entry_size,
            "equity_at_entry": equity,
            "drawdown_at_entry": drawdown_pct,
            "risk_level_at_entry": risk_level,
            "scale_factor_applied": scale_factor,
            "scale_factor_reason": scale_reason,
            "peak_adverse": entry_price,
            "peak_favorable": entry_price,
        }

    def update_price(self, ticket: int, current_price: float) -> None:
        """Update running MAE/MFE for an active trade.

        Called periodically with current market price to track
        maximum adverse and favorable excursion.
        """
        if ticket not in self._active_trades:
            return

        trade = self._active_trades[ticket]
        direction = trade["direction"]

        if direction == "LONG":
            # Adverse = price going down, favorable = price going up
            if current_price < trade["peak_adverse"]:
                trade["peak_adverse"] = current_price
            if current_price > trade["peak_favorable"]:
                trade["peak_favorable"] = current_price
        else:  # SHORT
            if current_price > trade["peak_adverse"]:
                trade["peak_adverse"] = current_price
            if current_price < trade["peak_favorable"]:
                trade["peak_favorable"] = current_price

    def record_trade_exit(
        self,
        ticket: int,
        exit_price: float,
        realized_pnl: float,
    ) -> Dict[str, Any]:
        """Record trade exit and compute attribution metrics.

        Returns the complete attribution record.
        """
        if ticket not in self._active_trades:
            return {"error": f"ticket {ticket} not found in active trades"}

        trade = self._active_trades.pop(ticket)
        entry_price = trade["entry_price"]
        direction = trade["direction"]

        # Compute MAE and MFE in price terms
        if direction == "LONG":
            mae = entry_price - trade["peak_adverse"]
            mfe = trade["peak_favorable"] - entry_price
        else:
            mae = trade["peak_adverse"] - entry_price
            mfe = entry_price - trade["peak_favorable"]

        # Holding period
        entry_dt = datetime.fromisoformat(trade["entry_time"])
        exit_dt = datetime.now(UTC)
        holding_days = (exit_dt - entry_dt).total_seconds() / 86400

        # Counterfactual: what if REDUCED had been active?
        # For shadow mode, scale_factor was recorded but not applied
        # So counterfactual_pnl = realized_pnl * scale_factor
        scale_factor = trade["scale_factor_applied"]
        counterfactual_pnl = realized_pnl * scale_factor if scale_factor < 1.0 else None
        counterfactual_size = trade["entry_size"] * scale_factor if scale_factor < 1.0 else None

        attribution = {
            **trade,
            "exit_time": exit_dt.isoformat(),
            "exit_price": exit_price,
            "realized_pnl": realized_pnl,
            "mae": mae,
            "mfe": mfe,
            "holding_days": holding_days,
            "counterfactual_size": counterfactual_size,
            "counterfactual_pnl": counterfactual_pnl,
        }

        self._closed_trades.append(attribution)
        self._append_attribution(attribution)

        return attribution

    def _append_attribution(self, record: Dict[str, Any]) -> None:
        """Append attribution record to JSONL file."""
        filepath = os.path.join(self._data_dir, "trade_attribution.jsonl")
        with open(filepath, "a") as f:
            f.write(json.dumps(record, default=str) + "\n")

    def get_active_count(self) -> int:
        return len(self._active_trades)

    def get_summary(self) -> Dict[str, Any]:
        """Get summary statistics of attribution data."""
        if not self._closed_trades:
            return {"total_trades": 0}

        pnls = [t["realized_pnl"] for t in self._closed_trades if t.get("realized_pnl") is not None]
        maes = [t["mae"] for t in self._closed_trades if t.get("mae") is not None]
        mfes = [t["mfe"] for t in self._closed_trades if t.get("mfe") is not None]
        scale_factors = [t["scale_factor_applied"] for t in self._closed_trades]

        # How many trades would REDUCED have affected?
        reduced_trades = [t for t in self._closed_trades if t.get("scale_factor_applied", 1.0) < 1.0]

        return {
            "total_trades": len(self._closed_trades),
            "winning_trades": sum(1 for p in pnls if p > 0),
            "losing_trades": sum(1 for p in pnls if p < 0),
            "total_pnl": sum(pnls) if pnls else 0,
            "avg_pnl": sum(pnls) / len(pnls) if pnls else 0,
            "avg_mae": sum(maes) / len(maes) if maes else 0,
            "avg_mfe": sum(mfes) / len(mfes) if mfes else 0,
            "avg_scale_factor": sum(scale_factors) / len(scale_factors) if scale_factors else 1.0,
            "reduced_trades_count": len(reduced_trades),
            "reduced_trades_pct": len(reduced_trades) / len(self._closed_trades) * 100 if self._closed_trades else 0,
        }
