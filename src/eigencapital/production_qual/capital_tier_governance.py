"""Capital Tier Governance — controls progressive capital scaling.

Prevents an operator from arbitrarily changing capital levels.
Each tier requires explicit approval, configuration transition, and audit record.

Capital tiers are immutable after creation — changing tier limits requires
creating a new tier, not modifying an existing one.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Any, Dict, List, Optional


class TierStatus(str, Enum):
    CANDIDATE = "CANDIDATE"
    QUALIFIED = "QUALIFIED"
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"
    RETIRED = "RETIRED"


class PromotionVerdict(str, Enum):
    APPROVED = "APPROVED"
    BLOCKED = "BLOCKED"
    INSUFFICIENT_EVIDENCE = "INSUFFICIENT_EVIDENCE"


@dataclass(frozen=True)
class CapitalTier:
    """An immutable capital tier definition."""

    tier_id: str
    max_equity: float
    max_position_size: float
    max_order_notional: float
    max_concurrent_positions: int
    max_daily_loss: float
    max_drawdown_pct: float
    max_total_drawdown: float
    required_stable_days: int = 0
    required_zero_critical_incidents: bool = True
    created_at: str = ""

    def __post_init__(self) -> None:
        if not self.created_at:
            object.__setattr__(
                self, "created_at", datetime.now(timezone.utc).isoformat()
            )

    def compute_fingerprint(self) -> str:
        data = {
            "tier_id": self.tier_id,
            "max_equity": self.max_equity,
            "max_position_size": self.max_position_size,
            "max_order_notional": self.max_order_notional,
            "max_concurrent_positions": self.max_concurrent_positions,
            "max_daily_loss": self.max_daily_loss,
            "max_drawdown_pct": self.max_drawdown_pct,
            "max_total_drawdown": self.max_total_drawdown,
            "required_stable_days": self.required_stable_days,
        }
        payload = json.dumps(data, sort_keys=True).encode("utf-8")
        return hashlib.sha256(payload).hexdigest()[:16]


TIER_1_QUALIFICATION = CapitalTier(
    tier_id="T1-QUALIFICATION",
    max_equity=5_100.0,
    max_position_size=2_500.0,
    max_order_notional=2_500.0,
    max_concurrent_positions=19,
    max_daily_loss=250.0,
    max_drawdown_pct=20.0,
    max_total_drawdown=1_000.0,
)

TIER_2_PROVISIONAL = CapitalTier(
    tier_id="T2-PROVISIONAL",
    max_equity=10_100.0,
    max_position_size=2_500.0,
    max_order_notional=2_500.0,
    max_concurrent_positions=10,
    max_daily_loss=500.0,
    max_drawdown_pct=15.0,
    max_total_drawdown=2_000.0,
    required_stable_days=14,
)

TIER_3_CONTROLLED = CapitalTier(
    tier_id="T3-CONTROLLED",
    max_equity=25_100.0,
    max_position_size=5_000.0,
    max_order_notional=5_000.0,
    max_concurrent_positions=12,
    max_daily_loss=1_000.0,
    max_drawdown_pct=12.0,
    max_total_drawdown=5_000.0,
    required_stable_days=30,
)

TIER_4_SCALED = CapitalTier(
    tier_id="T4-SCALED",
    max_equity=50_100.0,
    max_position_size=8_000.0,
    max_order_notional=8_000.0,
    max_concurrent_positions=15,
    max_daily_loss=2_000.0,
    max_drawdown_pct=10.0,
    max_total_drawdown=10_000.0,
    required_stable_days=60,
)

TIER_5_INSTITUTIONAL = CapitalTier(
    tier_id="T5-INSTITUTIONAL",
    max_equity=100_100.0,
    max_position_size=15_000.0,
    max_order_notional=15_000.0,
    max_concurrent_positions=20,
    max_daily_loss=3_000.0,
    max_drawdown_pct=8.0,
    max_total_drawdown=15_000.0,
    required_stable_days=90,
)

ALL_TIERS: List[CapitalTier] = [
    TIER_1_QUALIFICATION,
    TIER_2_PROVISIONAL,
    TIER_3_CONTROLLED,
    TIER_4_SCALED,
    TIER_5_INSTITUTIONAL,
]


def get_tier_by_id(tier_id: str) -> Optional[CapitalTier]:
    for t in ALL_TIERS:
        if t.tier_id == tier_id:
            return t
    return None


@dataclass
class PromotionEvidence:
    stable_days: int = 0
    total_restarts: int = 0
    critical_incidents: int = 0
    reconciliation_failures: int = 0
    duplicate_orders: int = 0
    unauthorized_orders: int = 0
    max_drawdown_pct: float = 0.0
    max_daily_loss_pct: float = 0.0
    broker_stable: bool = True
    last_incident_days_ago: int = 0

    def to_dict(self) -> Dict[str, Any]:
        return {
            "stable_days": self.stable_days,
            "total_restarts": self.total_restarts,
            "critical_incidents": self.critical_incidents,
            "reconciliation_failures": self.reconciliation_failures,
            "duplicate_orders": self.duplicate_orders,
            "unauthorized_orders": self.unauthorized_orders,
            "max_drawdown_pct": self.max_drawdown_pct,
            "max_daily_loss_pct": self.max_daily_loss_pct,
            "broker_stable": self.broker_stable,
            "last_incident_days_ago": self.last_incident_days_ago,
        }


@dataclass
class PromotionVerdictResult:
    target_tier: str
    verdict: PromotionVerdict
    blocking_reasons: List[str] = field(default_factory=list)
    evidence: Optional[PromotionEvidence] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "target_tier": self.target_tier,
            "verdict": self.verdict.value,
            "blocking_reasons": self.blocking_reasons,
            "evidence": self.evidence.to_dict() if self.evidence else None,
        }


class CapitalTierGovernor:
    """Enforces progressive capital scaling."""

    def __init__(
        self,
        tiers: Optional[List[CapitalTier]] = None,
        persistence_dir: Optional[str] = None,
    ) -> None:
        self._tiers = tiers or ALL_TIERS
        self._persistence_dir = Path(persistence_dir) if persistence_dir else None
        self._active_tier: Optional[CapitalTier] = None
        self._audit_log: List[Dict[str, Any]] = []
        self._max_audit_entries = 100

    @property
    def active_tier(self) -> Optional[CapitalTier]:
        return self._active_tier

    def activate_tier(self, tier_id: str) -> CapitalTier:
        tier = get_tier_by_id(tier_id)
        if tier is None:
            raise ValueError(f"Unknown capital tier: {tier_id}")
        self._active_tier = tier
        self._audit_event("TIER_ACTIVATED", {"tier_id": tier_id})
        return tier

    def check_equity_against_tier(self, equity: float) -> bool:
        if self._active_tier is None:
            return False
        return equity <= self._active_tier.max_equity

    def evaluate_promotion(
        self,
        target_tier_id: str,
        evidence: PromotionEvidence,
    ) -> PromotionVerdictResult:
        target = get_tier_by_id(target_tier_id)
        if target is None:
            return PromotionVerdictResult(
                target_tier=target_tier_id,
                verdict=PromotionVerdict.BLOCKED,
                blocking_reasons=[f"Unknown tier: {target_tier_id}"],
            )

        reasons: List[str] = []

        if self._active_tier is not None:
            current_idx = next(
                (
                    i
                    for i, t in enumerate(self._tiers)
                    if t.tier_id == self._active_tier.tier_id
                ),
                -1,
            )
            target_idx = next(
                (i for i, t in enumerate(self._tiers) if t.tier_id == target_tier_id),
                -1,
            )
            if target_idx > current_idx + 1:
                reasons.append(
                    f"Cannot skip from {self._active_tier.tier_id} to {target_tier_id}"
                )

        if evidence.stable_days < target.required_stable_days:
            reasons.append(
                f"Need {target.required_stable_days} stable days, have {evidence.stable_days}"
            )

        if target.required_zero_critical_incidents and evidence.critical_incidents > 0:
            reasons.append(
                f"Require zero critical incidents, have {evidence.critical_incidents}"
            )

        if evidence.duplicate_orders > 0:
            reasons.append(f"Duplicate orders detected: {evidence.duplicate_orders}")

        if evidence.unauthorized_orders > 0:
            reasons.append(
                f"Unauthorized orders detected: {evidence.unauthorized_orders}"
            )

        if not evidence.broker_stable:
            reasons.append("Broker is not stable")

        if evidence.max_drawdown_pct > target.max_drawdown_pct:
            reasons.append(
                f"Historical drawdown {evidence.max_drawdown_pct:.1f}% "
                f"exceeds new tier limit {target.max_drawdown_pct:.1f}%"
            )

        verdict = (
            PromotionVerdict.APPROVED
            if not reasons
            else (
                PromotionVerdict.INSUFFICIENT_EVIDENCE
                if evidence.stable_days > 0
                else PromotionVerdict.BLOCKED
            )
        )

        result = PromotionVerdictResult(
            target_tier=target_tier_id,
            verdict=verdict,
            blocking_reasons=reasons,
            evidence=evidence,
        )
        self._audit_event("PROMOTION_EVALUATED", result.to_dict())
        return result

    def promote(self, target_tier_id: str, evidence: PromotionEvidence) -> bool:
        result = self.evaluate_promotion(target_tier_id, evidence)
        if result.verdict == PromotionVerdict.APPROVED:
            self.activate_tier(target_tier_id)
            return True
        return False

    def _audit_event(self, event_type: str, data: Dict[str, Any]) -> None:
        entry = {
            "event": event_type,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            **data,
        }
        self._audit_log.append(entry)
        if len(self._audit_log) > self._max_audit_entries:
            self._audit_log = self._audit_log[-self._max_audit_entries :]

    def get_audit_log(self) -> List[Dict[str, Any]]:
        return list(self._audit_log)

    def get_status(self) -> Dict[str, Any]:
        return {
            "active_tier": self._active_tier.tier_id if self._active_tier else None,
            "active_tier_fingerprint": self._active_tier.compute_fingerprint()
            if self._active_tier
            else None,
            "available_tiers": [t.tier_id for t in self._tiers],
            "audit_entries": len(self._audit_log),
        }
