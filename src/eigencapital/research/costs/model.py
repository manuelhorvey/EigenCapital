"""Cost Model — explicit transaction cost contract.

Don't let the eventual backtester contain hardcoded costs.
Define them here, version them, and pass them explicitly.

Usage:
    cost_model = CostModel(
        model_id="realistic_v1",
        commission_per_contract=2.50,
        exchange_fee_per_contract=1.25,
        spread_ticks=1,
        slippage_ticks=0.5,
    )
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict


@dataclass(frozen=True)
class CostModel:
    """Versioned transaction cost model.

    Attributes:
        model_id: Unique identifier (e.g., "realistic_v1")
        version: Version string
        commission_per_contract: Fixed commission per contract/share
        exchange_fee_per_contract: Exchange/regulatory fee per unit
        spread_ticks: Expected spread in tick units
        slippage_ticks: Expected slippage in tick units
        market_impact_bps: Market impact in basis points (of notional)
        assumptions: Free-form assumptions dict
    """

    model_id: str
    version: str = "v1"
    commission_per_contract: float = 0.0
    exchange_fee_per_contract: float = 0.0
    spread_ticks: float = 0.0
    slippage_ticks: float = 0.0
    market_impact_bps: float = 0.0
    assumptions: Dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self.model_id:
            raise ValueError("model_id must be non-empty")
        for field_name in (
            "commission_per_contract",
            "exchange_fee_per_contract",
            "spread_ticks",
            "slippage_ticks",
            "market_impact_bps",
        ):
            val = getattr(self, field_name)
            if val < 0:
                raise ValueError(f"{field_name} must be >= 0, got {val}")

    def cost_per_contract(self, tick_value: float = 1.0) -> float:
        """Total fixed cost per contract in currency units."""
        spread_cost = self.spread_ticks * tick_value * 0.5
        slippage_cost = self.slippage_ticks * tick_value
        return self.commission_per_contract + self.exchange_fee_per_contract + spread_cost + slippage_cost

    def to_dict(self) -> Dict[str, Any]:
        """Deterministic serialization."""
        return {
            "model_id": self.model_id,
            "version": self.version,
            "commission_per_contract": self.commission_per_contract,
            "exchange_fee_per_contract": self.exchange_fee_per_contract,
            "spread_ticks": self.spread_ticks,
            "slippage_ticks": self.slippage_ticks,
            "market_impact_bps": self.market_impact_bps,
            "assumptions": dict(sorted(self.assumptions.items())),
        }

    @classmethod
    def from_dict(cls, d: Dict[str, Any]) -> CostModel:
        """Deserialize from dict."""
        return cls(**{k: v for k, v in d.items() if k in cls.__dataclass_fields__})


# Pre-defined cost models for common scenarios
ZERO_COST = CostModel(model_id="zero", commission_per_contract=0.0)
MODERATE_COST = CostModel(
    model_id="moderate_v1",
    commission_per_contract=2.50,
    exchange_fee_per_contract=1.25,
    spread_ticks=1,
    slippage_ticks=0.5,
)
STRESS_COST = CostModel(
    model_id="stress_v1",
    commission_per_contract=5.00,
    exchange_fee_per_contract=2.50,
    spread_ticks=2,
    slippage_ticks=1.0,
    market_impact_bps=2.0,
)
