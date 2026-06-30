from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

import pandas as pd


class SignalType(str, Enum):
    BUY = "BUY"
    SELL = "SELL"
    FLAT = "FLAT"

    @classmethod
    def from_label(cls, label: int) -> SignalType:
        mapping = {1: cls.BUY, -1: cls.SELL, 0: cls.FLAT}
        return mapping.get(label, cls.FLAT)

    @classmethod
    def from_string(cls, value: str) -> SignalType:
        mapping = {"BUY": cls.BUY, "SELL": cls.SELL, "FLAT": cls.FLAT, "LONG": cls.BUY, "SHORT": cls.SELL}
        return mapping.get(value.upper(), cls.FLAT)


@dataclass
class SignalResult:
    signal_type: SignalType
    confidence_pct: float
    label: int
    prob_long: float = 0.0
    prob_short: float = 0.0
    prob_neutral: float = 0.0
    position_size: float = 0.0
    timestamp: str = ""

    @classmethod
    def from_dataframe_row(cls, row: pd.Series) -> SignalResult:
        return cls(
            signal_type=SignalType.from_label(int(row.get("label", 0))),
            confidence_pct=float(row.get("confidence", 0.0)),
            label=int(row.get("label", 0)),
            prob_long=float(row.get("prob_long", 0.0)),
            prob_short=float(row.get("prob_short", 0.0)),
            prob_neutral=float(row.get("prob_neutral", 0.0)),
            position_size=float(row.get("position_size", 0.0)),
        )

    @property
    def direction(self) -> int:
        if self.signal_type == SignalType.BUY:
            return 1
        if self.signal_type == SignalType.SELL:
            return -1
        return 0


@dataclass
class TradeDecision:
    asset: str
    signal: SignalType
    label: int
    confidence: float
    prob_long: float
    prob_short: float
    prob_neutral: float
    close_price: float
    timestamp: str
    position_size: float
    archetype: str = "UNKNOWN"
    feature_hash: str = ""

    @property
    def direction(self) -> int:
        if self.signal == SignalType.BUY:
            return 1
        if self.signal == SignalType.SELL:
            return -1
        return 0

    @property
    def is_actionable(self) -> bool:
        return self.signal != SignalType.FLAT

    def to_dict(self) -> dict:
        return {
            "asset": self.asset,
            "signal": self.signal.value,
            "label": self.label,
            "confidence": self.confidence,
            "prob_long": self.prob_long,
            "prob_short": self.prob_short,
            "prob_neutral": self.prob_neutral,
            "close_price": self.close_price,
            "timestamp": self.timestamp,
            "position_size": self.position_size,
            "archetype": self.archetype,
            "feature_hash": self.feature_hash,
        }
