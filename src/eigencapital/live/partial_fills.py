"""Partial-fill management policy (Phase 1U item 5).

Tracks requested vs filled quantity, decides ACCEPT / CHASE / CANCEL for
remainders, and treats the broker-reported position as authoritative at
cancellation/reconciliation. Fill events are idempotent by fill_id.
"""

from __future__ import annotations

from enum import Enum
from typing import Dict


class ChaseDecision(str, Enum):
    ACCEPT = "ACCEPT"
    CHASE = "CHASE"
    CANCEL = "CANCEL"
    DONE = "DONE"


class PartialFillManager:
    def __init__(
        self,
        order_id: str,
        requested_qty: float,
        *,
        max_chase_attempts: int = 2,
        max_age_seconds: float = 60.0,
        max_cumulative_slippage_bps: float = 15.0,
        reference_price: float = 0.0,
    ) -> None:
        if requested_qty <= 0:
            raise ValueError("requested_qty must be > 0")
        self.order_id = order_id
        self.requested_qty = float(requested_qty)
        self.max_chase_attempts = int(max_chase_attempts)
        self.max_age_seconds = float(max_age_seconds)
        self.max_slip = float(max_cumulative_slippage_bps)
        self.reference_price = float(reference_price)
        self.filled_qty = 0.0
        self.avg_fill_price = 0.0
        self.chase_attempts = 0
        self.cancelled = False
        self._seen_fill_ids: Dict[str, float] = {}
        self._first_ts: float | None = None

    def on_fill(self, fill_id: str, qty: float, price: float, ts: float) -> str:
        """Idempotent fill intake; duplicate/replayed fill_ids are ignored."""
        if fill_id in self._seen_fill_ids:
            return "DUPLICATE_IGNORED"
        if self.cancelled:
            return "FILL_AFTER_CANCEL_IGNORED"
        self._seen_fill_ids[fill_id] = float(qty)
        prev_notional = self.avg_fill_price * self.filled_qty
        self.filled_qty += float(qty)
        self.avg_fill_price = (prev_notional + float(price) * float(qty)) / self.filled_qty
        self._first_ts = self._first_ts if self._first_ts is not None else float(ts)
        return "REMAINDER_OPEN" if self.remaining > 1e-12 else "FULLY_FILLED"

    @property
    def remaining(self) -> float:
        return max(0.0, self.requested_qty - self.filled_qty)

    def _slippage_bps(self) -> float:
        if not self.reference_price or not self.filled_qty:
            return 0.0
        return abs(self.avg_fill_price - self.reference_price) / self.reference_price * 10_000

    def decide(
        self,
        now_ts: float,
        spread_ok: bool = True,
        risk_and_exposure_ok: bool = True,
        position_limit_ok: bool = True,
    ) -> ChaseDecision:
        """Policy engine for the unfilled remainder."""
        if self.remaining <= 1e-12:
            return ChaseDecision.DONE
        if self.cancelled:
            return ChaseDecision.CANCEL
        age = now_ts - (self._first_ts if self._first_ts is not None else now_ts)
        if age > self.max_age_seconds:
            return self.execute_cancel(now_ts)
        if self.chase_attempts >= self.max_chase_attempts:
            return self.execute_cancel(now_ts)
        if self._slippage_bps() > self.max_slip:
            return self.execute_cancel(now_ts)
        if not spread_ok or not risk_and_exposure_ok or not position_limit_ok:
            return ChaseDecision.ACCEPT  # keep the fill, no new exposure
        self.chase_attempts += 1
        return ChaseDecision.CHASE

    def execute_cancel(self, now_ts: float) -> ChaseDecision:
        self.cancelled = True
        return ChaseDecision.CANCEL

    def reconcile_with_broker(self, broker_position_qty: float) -> Dict:
        """Broker-reported position is authoritative after cancellation."""
        local = self.filled_qty if not self.cancelled else min(self.filled_qty, self.requested_qty)
        discrepancy = round(float(broker_position_qty) - local, 12)
        return {
            "order_id": self.order_id,
            "local_filled_qty": local,
            "broker_qty": float(broker_position_qty),
            "discrepancy": discrepancy,
            "authoritative_qty": float(broker_position_qty),
            "needs_escalation": abs(discrepancy) > 1e-9,
        }
