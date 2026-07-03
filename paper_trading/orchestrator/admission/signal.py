"""AdmissionSignal — what every trade must provide to be considered for admission."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum

from eigencapital.domain.time import utc_now


class PositionSide(str, Enum):
    LONG = "long"
    SHORT = "short"
    NONE = "none"


@dataclass(frozen=True)
class AdmissionSignal:
    """The admission contract — every signal must provide these fields
    to be eligible for ranking and execution.

    Created AFTER the decision pipeline's pre-entry stages (gates, confidence,
    conviction), BEFORE sizing and execution. Once constructed, the signal is
    immutable through the admission process."""

    # ── Identity ──
    asset: str
    side: PositionSide

    # ── Sizing inputs (pre-computed, pre-budget) ──
    entry_price: float
    stop_loss: float
    take_profit: float
    sl_distance_pct: float
    tp_distance_pct: float
    notional_requested: float
    risk_usd: float

    # ── Scoring inputs ──
    calibrated_prob: float
    expected_value_r: float
    tp_sl_ratio: float
    regime_confidence: float

    # ── Deferred entry support ──
    deferred_cycles: int = 0
    original_entry_price: float | None = None

    # ── Metadata ──
    feature_hash: str = ""
    generated_at: datetime = field(default_factory=lambda: utc_now())
