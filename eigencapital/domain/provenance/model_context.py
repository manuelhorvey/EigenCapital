"""ModelContext — frozen snapshot of model inference at decision time.

Captures the model version, raw and calibrated probabilities, and
calibration metadata so that every decision can be traced back to
exactly what the model predicted and how that prediction was adjusted.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class ModelContext:
    model_version: str
    model_hash: str
    prob_long: float
    prob_short: float
    prob_neutral: float
    calibrated_prob_long: float | None = None
    calibrated_confidence: float | None = None
    calibration_applied: bool = False
    calibration_version: str = ""
    calibration_ece: float | None = None
    meta_label_proba: float | None = None
    meta_label_enabled: bool = False
    ensemble_base_weight: float | None = None
    ensemble_regime_weight: float | None = None
    regime_label: str = ""
    regime_long_prob: float | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "model_version": self.model_version,
            "model_hash": self.model_hash,
            "prob_long": self.prob_long,
            "prob_short": self.prob_short,
            "prob_neutral": self.prob_neutral,
            "calibrated_prob_long": self.calibrated_prob_long,
            "calibrated_confidence": self.calibrated_confidence,
            "calibration_applied": self.calibration_applied,
            "calibration_version": self.calibration_version,
            "calibration_ece": self.calibration_ece,
            "meta_label_proba": self.meta_label_proba,
            "meta_label_enabled": self.meta_label_enabled,
            "ensemble_base_weight": self.ensemble_base_weight,
            "ensemble_regime_weight": self.ensemble_regime_weight,
            "regime_label": self.regime_label,
            "regime_long_prob": self.regime_long_prob,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> ModelContext:
        return cls(**data)
