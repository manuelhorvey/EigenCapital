"""Configuration for the cross-asset trend strategy.

Parameters are deliberately simple and economically plausible.
No ML. No optimization marathon. No asset-specific magic numbers.
"""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json


@dataclass(frozen=True)
class TrendConfig:
    """Configuration for the cross-asset trend strategy.

    Attributes:
        lookback_period: Number of bars for trend calculation
        entry_threshold: Z-score threshold for entry signal
        exit_threshold: Z-score threshold for exit signal
        volatility_lookback: Bars for volatility estimation
        risk_target: Target volatility for position sizing
        max_position_size: Maximum position size per instrument
    """

    lookback_period: int = 63  # ~3 months daily
    entry_threshold: float = 1.0  # Z-score for entry
    exit_threshold: float = 0.0  # Z-score for exit (mean reversion)
    volatility_lookback: int = 21  # ~1 month daily
    risk_target: float = 0.10  # 10% annualized volatility target
    max_position_size: float = 1.0  # Maximum 1 contract per instrument

    def __post_init__(self) -> None:
        if self.lookback_period <= 0:
            raise ValueError("lookback_period must be > 0")
        if self.volatility_lookback <= 0:
            raise ValueError("volatility_lookback must be > 0")
        if self.risk_target <= 0:
            raise ValueError("risk_target must be > 0")
        if self.max_position_size <= 0:
            raise ValueError("max_position_size must be > 0")

    def to_dict(self) -> dict:
        """Deterministic serialization."""
        return {
            "lookback_period": self.lookback_period,
            "entry_threshold": self.entry_threshold,
            "exit_threshold": self.exit_threshold,
            "volatility_lookback": self.volatility_lookback,
            "risk_target": self.risk_target,
            "max_position_size": self.max_position_size,
        }

    def config_hash(self) -> str:
        """Deterministic hash of configuration parameters."""
        data = json.dumps(self.to_dict(), sort_keys=True)
        return hashlib.sha256(data.encode("utf-8")).hexdigest()
