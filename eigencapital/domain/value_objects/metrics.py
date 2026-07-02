from __future__ import annotations

import dataclasses
from dataclasses import dataclass, field


@dataclass
class PerformanceMetrics:
    total_return_pct: float | None = None
    mtm_return_pct: float | None = None
    drawdown_pct: float | None = None
    profit_factor: float | None = None
    win_rate: float | None = None
    total_trades: int | None = None
    total_signals: int | None = None
    mean_confidence: float | None = None
    mean_prob_long: float | None = None
    mean_prob_short: float | None = None
    current_price: float | None = None
    current_value: float | None = None
    sharpe_ratio: float | None = None
    sortino_ratio: float | None = None
    calmar_ratio: float | None = None

    def to_dict(self) -> dict:
        return {k: v for k, v in dataclasses.asdict(self).items() if v is not None}


@dataclass
class StabilityMetrics:
    jaccard_top_10: float = 0.0
    spearman_rank_corr: float = 0.0
    penalty: float = 0.0
    window_id: int = 0

    def to_dict(self) -> dict:
        return {k: v for k, v in dataclasses.asdict(self).items() if v is not None}


@dataclass
class DriftMetrics:
    psi_drift_detected: bool = False
    max_psi: float = 0.0
    drifted_features: list = field(default_factory=list)
    ks_drift_detected: bool = False
    model_stability_score: float = 0.0
    signal_stability_score: float = 0.0

    @property
    def is_stable(self) -> bool:
        return not self.psi_drift_detected and not self.ks_drift_detected and self.model_stability_score >= 0.5
