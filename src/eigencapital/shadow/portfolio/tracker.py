"""Shadow persistence and realized-outcome tracking (Sections 12/14 of the brief).

Persistence:
    shadow_portfolio_decisions.jsonl  — one record per R4 cycle (provenance).
    shadow_portfolio_outcomes.jsonl   — one record per closed shadow position.

SAFETY (Section 17): the recorder refuses to write to any of the frozen R4
evidence files (decisions.jsonl, order_intents.jsonl, risk_gate_audit.jsonl,
shadow_decisions.jsonl) — shadow evidence lives ONLY in its own namespace.

Outcome tracking (Section 12): each shadow position is marked "as if traded":
    shadow_entry, shadow_size, shadow_price, shadow_stop, shadow_exit,
    shadow_PnL, shadow_R.

PnL CONVENTION (documented, no invented quantities): replay/observation has
no per-symbol contract-size guarantee, so shadow PnL is measured in the same
weight space as the R4 signal:
    notional_proxy   = |w| · equity            (weight space, no lot math)
    pnl_proxy        = direction · (exit/entry − 1) · notional_proxy
    R                = direction · (exit/entry − 1) / atr_pct_at_entry
This is an equity proxy for comparison purposes only — it never reaches a
broker and makes no contract-size assumptions.

NO LOOKAHEAD: entry uses the decision bar close; outcome paths use ONLY bars
the caller passes (strictly after the decision bar). The tracker has no data
access of its own — the caller decides what the tracker can see.
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Dict, List

PROTECTED_R4_EVIDENCE_FILES = {
    "decisions.jsonl",
    "order_intents.jsonl",
    "risk_gate_audit.jsonl",
    "shadow_decisions.jsonl",  # RiskEnforcer's own namespace — not ours
}

OUTCOME_SCHEMA_VERSION = "1.0"


class ShadowDecisionRecorder:
    """Append-only JSONL persistence for shadow decisions (isolated namespace)."""

    def __init__(self, audit_dir: str = "reports/r4_loop") -> None:
        self._dir = Path(audit_dir)
        self._dir.mkdir(parents=True, exist_ok=True)
        self._decisions_path = self._dir / "shadow_portfolio_decisions.jsonl"
        self._outcomes_path = self._dir / "shadow_portfolio_outcomes.jsonl"

    @property
    def decisions_path(self) -> Path:
        return self._decisions_path

    @property
    def outcomes_path(self) -> Path:
        return self._outcomes_path

    def record_decision(self, decision: Any) -> str:
        """Append a ShadowDecision (anything with to_dict). Returns the path."""
        record = decision.to_dict()
        record["schema"] = "shadow_portfolio_decision"
        record["record_timestamp"] = datetime.now(UTC).isoformat()
        self._append(self._decisions_path, record)
        return str(self._decisions_path)

    def record_outcome(self, outcome: Dict[str, Any]) -> str:
        outcome = dict(outcome)
        outcome["schema"] = "shadow_portfolio_outcome"
        outcome["schema_version"] = OUTCOME_SCHEMA_VERSION
        outcome["record_timestamp"] = datetime.now(UTC).isoformat()
        self._append(self._outcomes_path, outcome)
        return str(self._outcomes_path)

    def read_decisions(self) -> List[Dict[str, Any]]:
        return self._read(self._decisions_path)

    def read_outcomes(self) -> List[Dict[str, Any]]:
        return self._read(self._outcomes_path)

    # ── guards ────────────────────────────────────────────────────────
    @staticmethod
    def _append(path: Path, record: Dict[str, Any]) -> None:
        if path.name in PROTECTED_R4_EVIDENCE_FILES:
            raise PermissionError(f"refusing to write shadow evidence to protected R4 file: {path.name}")
        with open(path, "a") as f:
            f.write(json.dumps(record, default=str) + "\n")

    @staticmethod
    def _read(path: Path) -> List[Dict[str, Any]]:
        if not path.exists():
            return []
        records: List[Dict[str, Any]] = []
        with open(path) as f:
            for line in f:
                line = line.strip()
                if line:
                    try:
                        records.append(json.loads(line))
                    except json.JSONDecodeError:
                        continue
        return records


@dataclass
class ShadowPosition:
    """An open shadow position tracked as-if-traded."""

    cycle_id: str
    signal_date: str
    symbol: str
    direction: str  # LONG | SHORT
    weight: float
    entry_price: float
    entry_close_time: Any  # pd.Timestamp of the decision bar
    notional_proxy: float = 0.0
    atr_pct_at_entry: float | None = None  # ATR14 / close, dimensionless
    exit_price: float | None = None
    exit_time: Any | None = None
    exit_reason: str = "open"

    @property
    def direction_sign(self) -> float:
        return 1.0 if self.direction == "LONG" else -1.0

    def pnl_proxy(self, exit_price: float) -> float:
        """Weight-space PnL proxy: d·(exit/entry − 1)·notional."""
        if self.entry_price <= 0:
            return 0.0
        ret = self.direction_sign * (exit_price / self.entry_price - 1.0)
        return ret * self.notional_proxy

    def r_multiple(self, exit_price: float) -> float | None:
        """R multiple: d·(exit/entry − 1) / atr_pct_at_entry."""
        if self.entry_price <= 0 or not self.atr_pct_at_entry or self.atr_pct_at_entry <= 0:
            return None
        ret = self.direction_sign * (exit_price / self.entry_price - 1.0)
        return ret / self.atr_pct_at_entry

    def to_dict(self) -> Dict[str, Any]:
        return {
            "cycle_id": self.cycle_id,
            "signal_date": self.signal_date,
            "symbol": self.symbol,
            "direction": self.direction,
            "weight": round(self.weight, 6),
            "notional_proxy": round(self.notional_proxy, 4),
            "entry_price": round(self.entry_price, 6),
            "entry_close_time": str(self.entry_close_time),
            "atr_pct_at_entry": round(self.atr_pct_at_entry, 6) if self.atr_pct_at_entry is not None else None,
            "exit_price": round(self.exit_price, 6) if self.exit_price is not None else None,
            "exit_time": str(self.exit_time) if self.exit_time is not None else None,
            "exit_reason": self.exit_reason,
        }


class ShadowPositionTracker:
    """Tracks shadow positions across cycles and realizes their outcomes.

    The tracker holds no market data. Every observation (prices, times,
    selection) is supplied by the caller, so no-lookahead is enforced at the
    call site: the caller decides what the tracker can see at any moment.
    """

    def __init__(
        self,
        recorder: ShadowDecisionRecorder,
        equity: float = 5100.0,
    ) -> None:
        self._recorder = recorder
        self._equity = equity
        self._open: Dict[str, ShadowPosition] = {}

    def open_cycle(
        self,
        selected_symbols: List[str],
        weights: Dict[str, float],
        prices: Dict[str, float],
        atr_pct: Dict[str, float],
        cycle_id: str,
        signal_date: str,
        entry_time: Any,
    ) -> Dict[str, ShadowPosition]:
        """Open (or refresh) shadow positions for the selected symbols.

        Positions for symbols no longer selected are NOT closed here — the
        caller decides exits via `close_positions`. This mirrors R4's
        rotation: closed only when the target portfolio changes.
        """
        for sym in selected_symbols:
            price = prices.get(sym)
            if not price or price <= 0:
                continue
            w = weights.get(sym, 0.0)
            if w == 0.0:
                continue
            self._open[sym] = ShadowPosition(
                cycle_id=cycle_id,
                signal_date=signal_date,
                symbol=sym,
                direction="LONG" if w > 0 else "SHORT",
                weight=w,
                entry_price=float(price),
                entry_close_time=entry_time,
                notional_proxy=abs(w) * self._equity,
                atr_pct_at_entry=float(atr_pct[sym]) if sym in atr_pct and atr_pct[sym] is not None else None,
            )
        return dict(self._open)

    def close_positions(
        self,
        symbols: List[str],
        prices: Dict[str, float],
        exit_time: Any,
        cycle_id: str,
        signal_date: str,
        exit_reason: str = "rotated_out",
    ) -> List[Dict[str, Any]]:
        """Realize outcomes for the given open positions at the given prices.

        `prices` must be the closes at/after the exit decision; the caller
        guarantees these are bars the tracker is allowed to see.
        """
        outcomes: List[Dict[str, Any]] = []
        for sym in symbols:
            pos = self._open.get(sym)
            if pos is None:
                continue
            px = prices.get(sym)
            if px is None or px <= 0:
                continue
            pos.exit_price = float(px)
            pos.exit_time = exit_time
            pos.exit_reason = exit_reason
            r_multiple = pos.r_multiple(px)
            outcome = {
                "cycle_id": cycle_id,
                "signal_date": signal_date,
                "symbol": sym,
                "direction": pos.direction,
                "shadow_entry": pos.entry_price,
                "shadow_size": round(pos.notional_proxy, 4),
                "shadow_price": pos.entry_price,
                "shadow_stop": None,  # R4 uses signal-based exits, no SL
                "shadow_exit": float(px),
                "shadow_pnl": round(pos.pnl_proxy(px), 6),
                "shadow_r": round(r_multiple, 4) if r_multiple is not None else None,
                "exit_time": str(exit_time),
                "entry_close_time": str(pos.entry_close_time),
                "exit_reason": pos.exit_reason,
            }
            self._recorder.record_outcome(outcome)
            outcomes.append(outcome)
            self._open.pop(sym, None)
        return outcomes

    def close_all(
        self,
        prices: Dict[str, float],
        exit_time: Any,
        cycle_id: str,
        signal_date: str,
        exit_reason: str = "end_of_observation",
    ) -> List[Dict[str, Any]]:
        return self.close_positions(list(self._open.keys()), prices, exit_time, cycle_id, signal_date, exit_reason)

    def open_positions(self) -> Dict[str, ShadowPosition]:
        return dict(self._open)

    def clear(self) -> None:
        self._open.clear()


def default_output_dir() -> str:
    """Default evidence directory for shadow records."""
    return os.environ.get("EIGENCAPITAL_SHADOW_OUT_DIR", "reports/r4_loop")
