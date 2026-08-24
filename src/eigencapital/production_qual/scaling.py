"""Production Scaling — proves system remains safe at larger sizes.

Scaling fidelity: larger positions remain inside risk envelope.
Slippage doesn't deteriorate materially with size.
Actual costs remain within model.
No unexpected margin pressure.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from enum import Enum
from typing import Dict, List, Optional, Any


class ScaleLevel(str, Enum):
    """Capital scaling levels."""

    MICRO = "micro"           # $1,000 (Phase 1T)
    MINIMAL = "minimal"       # $5,000
    SMALL = "small"           # $25,000
    MODERATE = "moderate"     # $100,000
    STANDARD = "standard"     # $500,000
    FULL = "full"             # $1,000,000+


@dataclass(frozen=True)
class ScaleEnvelope:
    """Risk envelope for a specific capital level."""

    level: ScaleLevel
    max_equity: float
    max_position_size: float
    max_order_notional: float
    max_concurrent_positions: int
    max_daily_loss: float
    max_total_drawdown: float
    max_drawdown_pct: float
    max_spread: float
    max_slippage: float
    max_execution_divergence: float

    def compute_identity(self) -> str:
        data = {
            "level": self.level.value,
            "max_equity": self.max_equity,
            "max_position_size": self.max_position_size,
            "max_order_notional": self.max_order_notional,
            "max_concurrent_positions": self.max_concurrent_positions,
            "max_daily_loss": self.max_daily_loss,
            "max_total_drawdown": self.max_total_drawdown,
            "max_drawdown_pct": self.max_drawdown_pct,
        }
        payload = json.dumps(data, sort_keys=True).encode("utf-8")
        return hashlib.sha256(payload).hexdigest()


# Pre-registered scale envelopes
SCALE_ENVELOPES: Dict[ScaleLevel, ScaleEnvelope] = {
    ScaleLevel.MICRO: ScaleEnvelope(
        level=ScaleLevel.MICRO,
        max_equity=1000,
        max_position_size=100,
        max_order_notional=50,
        max_concurrent_positions=5,
        max_daily_loss=50,
        max_total_drawdown=200,
        max_drawdown_pct=0.20,
        max_spread=0.0020,
        max_slippage=0.0010,
        max_execution_divergence=0.005,
    ),
    ScaleLevel.MINIMAL: ScaleEnvelope(
        level=ScaleLevel.MINIMAL,
        max_equity=5000,
        max_position_size=500,
        max_order_notional=250,
        max_concurrent_positions=8,
        max_daily_loss=250,
        max_total_drawdown=1000,
        max_drawdown_pct=0.20,
        max_spread=0.0015,
        max_slippage=0.0008,
        max_execution_divergence=0.004,
    ),
    ScaleLevel.SMALL: ScaleEnvelope(
        level=ScaleLevel.SMALL,
        max_equity=25000,
        max_position_size=2500,
        max_order_notional=1250,
        max_concurrent_positions=10,
        max_daily_loss=1250,
        max_total_drawdown=5000,
        max_drawdown_pct=0.20,
        max_spread=0.0010,
        max_slippage=0.0005,
        max_execution_divergence=0.003,
    ),
    ScaleLevel.MODERATE: ScaleEnvelope(
        level=ScaleLevel.MODERATE,
        max_equity=100000,
        max_position_size=10000,
        max_order_notional=5000,
        max_concurrent_positions=12,
        max_daily_loss=5000,
        max_total_drawdown=20000,
        max_drawdown_pct=0.20,
        max_spread=0.0008,
        max_slippage=0.0003,
        max_execution_divergence=0.002,
    ),
}


@dataclass
class ScalingMetrics:
    """Metrics for evaluating scaling behavior."""

    slippage_at_micro: float = 0.0
    slippage_at_current: float = 0.0
    slippage_deterioration: float = 0.0  # ratio

    spread_at_micro: float = 0.0
    spread_at_current: float = 0.0
    spread_deterioration: float = 0.0

    fill_rate_at_micro: float = 1.0
    fill_rate_at_current: float = 1.0
    fill_rate_deterioration: float = 0.0

    margin_usage: float = 0.0  # margin / equity
    margin_pressure: bool = False

    position_risk_ratio: float = 0.0  # position risk / equity
    risk_proportional: bool = True

    def to_dict(self) -> Dict[str, Any]:
        return {
            "slippage_at_micro": self.slippage_at_micro,
            "slippage_at_current": self.slippage_at_current,
            "slippage_deterioration": self.slippage_deterioration,
            "spread_at_micro": self.spread_at_micro,
            "spread_at_current": self.spread_at_current,
            "spread_deterioration": self.spread_deterioration,
            "fill_rate_at_micro": self.fill_rate_at_micro,
            "fill_rate_at_current": self.fill_rate_at_current,
            "fill_rate_deterioration": self.fill_rate_deterioration,
            "margin_usage": self.margin_usage,
            "margin_pressure": self.margin_pressure,
            "position_risk_ratio": self.position_risk_ratio,
            "risk_proportional": self.risk_proportional,
        }


class ProductionScaleEvaluator:
    """Evaluates whether scaling remains inside validated envelope."""

    MAX_SLIPPAGE_DETERIORATION: float = 2.0  # max 2x slippage
    MAX_SPREAD_DETERIORATION: float = 2.0    # max 2x spread
    MIN_FILL_RATE_RETENTION: float = 0.90    # retain 90% of micro fill rate
    MAX_MARGIN_USAGE: float = 0.50           # max 50% margin usage

    def evaluate(
        self,
        current_level: ScaleLevel,
        metrics: ScalingMetrics,
    ) -> Dict[str, Any]:
        """Evaluate scaling metrics against pre-registered thresholds."""
        checks = {}

        # Slippage check
        checks["slippage"] = {
            "passed": metrics.slippage_deterioration <= self.MAX_SLIPPAGE_DETERIORATION,
            "deterioration": metrics.slippage_deterioration,
            "threshold": self.MAX_SLIPPAGE_DETERIORATION,
        }

        # Spread check
        checks["spread"] = {
            "passed": metrics.spread_deterioration <= self.MAX_SPREAD_DETERIORATION,
            "deterioration": metrics.spread_deterioration,
            "threshold": self.MAX_SPREAD_DETERIORATION,
        }

        # Fill rate check
        checks["fill_rate"] = {
            "passed": metrics.fill_rate_at_current >= self.MIN_FILL_RATE_RETENTION,
            "rate": metrics.fill_rate_at_current,
            "threshold": self.MIN_FILL_RATE_RETENTION,
        }

        # Margin check
        checks["margin"] = {
            "passed": not metrics.margin_pressure and metrics.margin_usage <= self.MAX_MARGIN_USAGE,
            "usage": metrics.margin_usage,
            "threshold": self.MAX_MARGIN_USAGE,
        }

        # Risk proportionality
        checks["risk_proportional"] = {
            "passed": metrics.risk_proportional,
            "ratio": metrics.position_risk_ratio,
        }

        all_passed = all(c["passed"] for c in checks.values())

        return {
            "level": current_level.value,
            "checks": checks,
            "all_passed": all_passed,
        }
