from __future__ import annotations

from dataclasses import dataclass

import numpy as np


@dataclass(frozen=True)
class ExecutionConfig:
    base_spread_bps: float = 1.0
    spread_vol_slope: float = 1.0
    spread_max_bps: float = 10.0
    impact_model: str = "linear"
    impact_coeff: float = 0.01
    avg_daily_volume: float = 1_000_000
    base_gap_bps: float = 2.0
    gap_vol_slope: float = 0.5
    gap_max_bps: float = 20.0
    fill_vol_threshold: float = 2.0
    fill_prob_slope: float = 0.2
    min_fill_prob: float = 0.8
    delay_vol_threshold: float = 1.5
    delay_bars_max: int = 3
    latency_bps: float = 0.5
    vol_window: int = 20

    def compute_slippage_cost(self, vol_zscore: float) -> np.ndarray:
        spread_bps = min(self.base_spread_bps + self.spread_vol_slope * max(vol_zscore, 0), self.spread_max_bps)
        gap_bps = min(self.base_gap_bps + self.gap_vol_slope * max(vol_zscore, 0), self.gap_max_bps)
        return np.array([spread_bps, gap_bps])

    def compute_market_impact(self, position_notional: float) -> float:
        if self.avg_daily_volume <= 0:
            return 0.0
        return self.impact_coeff * (position_notional / self.avg_daily_volume)


@dataclass
class FillResult:
    fill_price: float = 0.0
    slippage_bps: float = 0.0
    fill_qty_ratio: float = 1.0
    latency_bars: int = 0
    gap_fill: bool = False
    partial_fill: bool = False


@dataclass
class SLTPResult:
    stop_loss: float = 0.0
    take_profit: float = 0.0
    trailing_activation_price: float | None = None
    method_used: str = ""


@dataclass
class TrailingResult:
    trailing_sl: float = 0.0
    activated: bool = False
    locked_profit: float = 0.0


@dataclass
class ScaleTier:
    fraction: float
    price: float
    filled: bool = False
    fill_price: float | None = None
