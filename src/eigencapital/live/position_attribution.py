"""Position attribution & foreign-position quarantine.

C2 of the P0 Safety Remediation campaign. Findings addressed:
  - magic=0 / unknown positions consumed R4 capacity and starved rotation (P0-3)
  - the PQ artifact asserted "Manual trades: 0" while broker state held
    unattributable positions

Design:
  - every position/deal receives exactly one classification
  - only R4_BOT (magic == R4_MAGIC) counts toward capacity
  - any FOREIGN position sets contaminated=True -> new entries BLOCKED,
    self-rotation (closing R4's own positions) still permitted so the bot can
    defend itself
  - attestation is DERIVED from broker evidence; it can never report zero
    manual trades when unattributed positions exist
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from enum import Enum
from typing import Any

R4_MAGIC = 20260825
R4_COMMENT_PREFIX = "R4"


class PositionClass(str, Enum):
    R4_BOT = "R4_BOT"
    MANUAL_MAGIC_0 = "MANUAL_MAGIC_0"
    FOREIGN_MAGIC_UNKNOWN = "FOREIGN_MAGIC_UNKNOWN"


@dataclass(frozen=True)
class ClassifiedPosition:
    ticket: int | None
    symbol: str
    direction: str
    volume: float
    magic: int
    comment: str
    profit: float
    pclass: PositionClass

    def to_dict(self) -> dict[str, Any]:
        return {
            "ticket": self.ticket,
            "symbol": self.symbol,
            "direction": self.direction,
            "volume": self.volume,
            "magic": self.magic,
            "comment": self.comment,
            "profit": self.profit,
            "pclass": self.pclass.value,
        }


def classify_position(pos: dict[str, Any]) -> ClassifiedPosition:
    magic_raw = pos.get("magic")
    magic = int(magic_raw) if magic_raw is not None else 0
    if magic == R4_MAGIC:
        pclass = PositionClass.R4_BOT
    elif magic == 0:
        pclass = PositionClass.MANUAL_MAGIC_0
    else:
        pclass = PositionClass.FOREIGN_MAGIC_UNKNOWN

    type_raw = pos.get("type")
    direction = "LONG" if (int(type_raw) if type_raw is not None else 0) == 0 else "SHORT"

    volume_raw = pos.get("volume")
    volume = float(volume_raw) if volume_raw is not None else 0.0

    profit_raw = pos.get("profit")
    profit = float(profit_raw) if profit_raw is not None else 0.0

    return ClassifiedPosition(
        ticket=pos.get("ticket"),
        symbol=str(pos.get("symbol", "?")),
        direction=direction,
        volume=volume,
        magic=magic,
        comment=str(pos.get("comment", "")),
        profit=profit,
        pclass=pclass,
    )


def classify_all(positions: list[dict[str, Any]]) -> list[ClassifiedPosition]:
    """Every position gets exactly one class — no exceptions, no silent drops."""
    return [classify_position(p) for p in positions]


@dataclass(frozen=True)
class CapacityVerdict:
    r4_open_count: int
    max_concurrent: int
    contaminated: bool
    foreign_positions: list[dict[str, Any]]
    allow_new_entries: bool
    allow_self_rotation: bool
    reason: str
    pending_order_count: int = 0  # P2-014: pending orders reduce effective capacity


def capacity_account(
    classified: list[ClassifiedPosition],
    max_concurrent: int,
    pending_orders: list[dict[str, Any]] | None = None,
) -> CapacityVerdict:
    """Capacity counts R4-owned positions + pending orders. Foreign presence quarantines.

    P2-014: Pending orders now reduce effective capacity to prevent over-ordering
    when broker connectivity hiccups leave stale pending orders.
    """
    r4 = [p for p in classified if p.pclass == PositionClass.R4_BOT]
    foreign = [p.to_dict() for p in classified if p.pclass != PositionClass.R4_BOT]
    # P2-014: Count pending R4 orders as occupying capacity slots
    pending_r4 = [o for o in (pending_orders or []) if o.get("magic") == R4_MAGIC]
    effective_count = len(r4) + len(pending_r4)
    contaminated = len(foreign) > 0
    if contaminated:
        return CapacityVerdict(
            r4_open_count=len(r4),
            max_concurrent=max_concurrent,
            contaminated=True,
            foreign_positions=foreign,
            allow_new_entries=False,
            allow_self_rotation=True,
            reason=(
                f"QUARANTINE: {len(foreign)} non-R4 position(s) present "
                f"(magic!= {R4_MAGIC}); new entries blocked; self-rotation allowed"
            ),
            pending_order_count=len(pending_r4),
        )
    over = effective_count > max_concurrent
    return CapacityVerdict(
        r4_open_count=len(r4),
        max_concurrent=max_concurrent,
        contaminated=False,
        foreign_positions=[],
        allow_new_entries=effective_count < max_concurrent and not over,
        allow_self_rotation=True,
        reason=(
            f"{len(r4)}/{max_concurrent} R4 positions"
            + (f" + {len(pending_r4)} pending" if pending_r4 else "")
            + (" — ALREADY BREACHED" if over else "")
        ),
        pending_order_count=len(pending_r4),
    )


def snapshot_hash(positions: list[dict[str, Any]], equity: float | None, free_margin: float | None) -> str:
    """Broker-state evidence hash bound into every risk decision (A7)."""
    material = json.dumps(
        {
            "positions": sorted(json.dumps(p, sort_keys=True, default=str) for p in positions),
            "equity": equity,
            "free_margin": free_margin,
        },
        sort_keys=True,
    )
    return hashlib.sha256(material.encode()).hexdigest()[:16]


# ── Deal-level attribution ledger ──────────────────────────────────


@dataclass(frozen=True)
class AttributionLedger:
    by_magic: dict[str, dict[str, float]]
    n_deals: int
    n_unattributable: int
    attestation_valid: bool
    detail: str = ""
    rows: list[dict[str, Any]] = field(default_factory=list)


def ledger_from_deals(deals: list[dict[str, Any]], known_magics: dict[int, str] | None = None) -> AttributionLedger:
    """Build realized-P&L attribution per magic from broker deal history.

    Attestation is honest by construction: `manual_trades` is whatever the
    broker shows, never an assertion. Any deal whose magic cannot be mapped
    increments n_unattributable and invalidates the attestation.
    """
    known = {R4_MAGIC: "R4_BOT"}
    if known_magics:
        known.update(known_magics)
    by_magic: dict[str, dict[str, float]] = {}
    unattr = 0
    rows: list[dict[str, Any]] = []
    for d in deals:
        magic_raw = d.get("magic")
        magic = int(magic_raw) if magic_raw is not None else 0
        owner = known.get(magic)
        bucket = owner if owner else (f"MAGIC_{magic}" if magic != 0 else "UNATTRIBUTED_MAGIC_0")
        if owner is None:
            unattr += 1
        agg = by_magic.setdefault(bucket, {"deals": 0, "realized_pnl": 0.0})
        agg["deals"] += 1
        profit_raw = d.get("profit")
        commission_raw = d.get("commission")
        swap_raw = d.get("swap")
        pnl = (
            (float(profit_raw) if profit_raw is not None else 0.0)
            + (float(commission_raw) if commission_raw is not None else 0.0)
            + (float(swap_raw) if swap_raw is not None else 0.0)
        )
        agg["realized_pnl"] += pnl
        rows.append(
            {
                "ticket": d.get("ticket"),
                "symbol": d.get("symbol"),
                "dir": d.get("dir"),
                "volume": d.get("volume"),
                "pnl": round(pnl, 2),
                "magic": magic,
                "owner": bucket,
            }
        )
    for agg in by_magic.values():
        agg["realized_pnl"] = round(agg["realized_pnl"], 2)
    return AttributionLedger(
        by_magic=by_magic,
        n_deals=len(deals),
        n_unattributable=unattr,
        attestation_valid=(unattr == 0),
        detail=(
            "attestation derived from broker deals; unattributable deals exist"
            if unattr
            else "all deals attributed to known owners"
        ),
        rows=rows,
    )
