"""Catastrophic protection layer — containment only, never expectancy.

C3 of the P0 Safety Remediation campaign.

Preregistered safety boundary (from counterfactual family F2, trial ledger):
  disaster stop distance = max(2 x ATR14%, FLOOR_DISTANCE_PCT)
Evidence (reports/r4_economics_audit/counterfactual_results.json):
  F2_atr_1..2 cut MaxDD from -12.3% to -6.7%/-7.0% at Sharpe drag <= 0.05.
This layer is judged on CONTAINMENT criteria only; it is not an economic exit
and must never become one. R4's own exits remain rotation/sign-flip/regime-ride.

Rules:
  - Only R4_BOT-owned positions are protected. Foreign/manual positions are
    reported, never managed (they belong to another owner by definition).
  - Idempotent: a position already protected at-or-inside the boundary yields
    NO new action (restart cannot duplicate orders).
  - Flatten operations retry across passes until flat or attempts exhausted,
    then escalate to HALT.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Callable

from eigencapital.live.position_attribution import (
    ClassifiedPosition,
    PositionClass,
)

SAFETY_ATR_MULT = 2.0
FLOOR_DISTANCE_PCT = 0.01  # 1% minimum distance: avoid noise triggers on quiet crosses


class ActionKind(str, Enum):
    SET_STOP_LOSS = "SET_STOP_LOSS"
    FLATTEN_POSITION = "FLATTEN_POSITION"
    HALT = "HALT"


@dataclass(frozen=True)
class SafetyAction:
    kind: ActionKind
    ticket: int | None
    symbol: str
    detail: dict[str, Any] = field(default_factory=dict)


def disaster_stop_price(
    direction: str,
    entry_price: float,
    atr_pct: float | None,
    mult: float = SAFETY_ATR_MULT,
    floor_pct: float = FLOOR_DISTANCE_PCT,
) -> float | None:
    """Boundary stop for containment: >= mult*ATR away, floored for noise."""
    if entry_price <= 0:
        return None
    if atr_pct is None or not atr_pct > 0:
        dist = floor_pct
    else:
        dist = max(mult * atr_pct, floor_pct)
    if direction == "LONG":
        return round(entry_price * (1.0 - dist), 6)
    if direction == "SHORT":
        return round(entry_price * (1.0 + dist), 6)
    return None


def _sl_is_inside_boundary(direction: str, current_sl: float, boundary: float) -> bool:
    """True when existing SL already protects at least as tightly as boundary."""
    if not current_sl or current_sl <= 0:
        return False
    if direction == "LONG":
        return current_sl >= boundary  # higher stop = tighter protection
    return current_sl <= boundary  # lower stop = tighter protection for shorts


def plan_protection(
    classified: list[ClassifiedPosition],
    atr_pct_by_symbol: dict[str, float],
    current_sl_by_ticket: dict[int, float],
    entry_price_lookup: Callable[[ClassifiedPosition], float],
    mult: float = SAFETY_ATR_MULT,
) -> list[SafetyAction]:
    """Idempotent plan: set/repair disaster stops for R4 positions only."""
    actions: list[SafetyAction] = []
    for p in classified:
        if p.pclass != PositionClass.R4_BOT or p.ticket is None:
            continue
        boundary = disaster_stop_price(
            p.direction, entry_price_lookup(p), atr_pct_by_symbol.get(p.symbol), mult
        )
        if boundary is None:
            continue
        cur = current_sl_by_ticket.get(p.ticket, 0.0)
        if _sl_is_inside_boundary(p.direction, cur, boundary):
            continue
        actions.append(
            SafetyAction(
                kind=ActionKind.SET_STOP_LOSS,
                ticket=p.ticket,
                symbol=p.symbol,
                detail={
                    "sl": boundary,
                    "direction": p.direction,
                    "mult_atr": mult,
                    "previous_sl": cur,
                    "reason": "catastrophic_containment_boundary",
                },
            )
        )
    return actions


# ── Flatten with retry ─────────────────────────────────────────────


class FlattenOutcome(str, Enum):
    ALREADY_FLAT = "ALREADY_FLAT"
    FLATTENED = "FLATTENED"
    PARTIAL = "PARTIAL"
    FAILED_HALT = "FAILED_HALT"


CloseCallable = Callable[[int], bool]
ListCallable = Callable[[], list[dict[str, Any]]]


def flatten_with_retry(
    list_positions: ListCallable,
    close_position: CloseCallable,
    max_passes: int = 5,
    only_tickets: set[int] | None = None,
) -> tuple[FlattenOutcome, int]:
    """Close positions across multiple passes until flat or attempts exhausted.

    Each pass re-lists live broker state so partially failed closes are retried.
    Returns (outcome, closed_count). FAILED_HALT means manual intervention.
    """
    closed_total = 0
    for _ in range(max_passes):
        positions = list_positions()
        if only_tickets is not None:
            positions = [p for p in positions if p.get("ticket") in only_tickets]
        if not positions:
            return (
                FlattenOutcome.ALREADY_FLAT
                if closed_total == 0
                else FlattenOutcome.FLATTENED
            ), closed_total
        progressed = False
        for p in positions:
            ticket = p.get("ticket")
            if ticket is None:
                continue
            if close_position(int(ticket)):
                closed_total += 1
                progressed = True
        if not progressed:
            time.sleep(0.05)  # transient failure: brief backoff before next pass
    remaining = list_positions()
    if only_tickets is not None:
        remaining = [p for p in remaining if p.get("ticket") in only_tickets]
    if not remaining:
        return FlattenOutcome.FLATTENED, closed_total
    if closed_total > 0:
        return FlattenOutcome.PARTIAL, closed_total
    return FlattenOutcome.FAILED_HALT, closed_total


def live_actions_enabled(flag_path: str) -> bool:
    """Kill-switch-by-default: live mutations require the explicit flag file."""
    import os

    return os.path.exists(flag_path)
