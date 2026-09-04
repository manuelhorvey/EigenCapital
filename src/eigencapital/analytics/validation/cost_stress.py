"""Cost Stress Testing — how robust is performance to transaction costs?

A strategy that only works under optimistic costs is not a real edge.
We test: base, 1.5x, 2x, 3x, 5x cost levels.

Usage:
    result = cost_stress_test(
        base_sharpe=1.5,
        cost_multipliers=[1.0, 1.5, 2.0, 3.0, 5.0],
        sharpe_at_costs=[1.5, 1.2, 0.8, 0.3, -0.2],
    )
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List


@dataclass(frozen=True)
class CostStressLevel:
    """Result at a single cost level.

    Attributes:
        multiplier: Cost multiplier (1.0 = base, 2.0 = 2x costs)
        sharpe: Sharpe at this cost level
        total_return_pct: Total return percentage at this cost level
        is_profitable: Sharpe > 0
    """

    multiplier: float
    sharpe: float
    total_return_pct: float = 0.0
    is_profitable: bool = True

    def to_dict(self) -> Dict[str, Any]:
        return {
            "multiplier": self.multiplier,
            "sharpe": round(self.sharpe, 4),
            "total_return_pct": round(self.total_return_pct, 2),
            "is_profitable": self.is_profitable,
        }


@dataclass(frozen=True)
class CostStressResult:
    """Results of cost stress analysis.

    Attributes:
        levels: Results at each cost level
        base_sharpe: Sharpe at base costs
        breakeven_multiplier: Estimated cost multiplier where Sharpe = 0
        survives_1_5x: Profitable at 1.5x costs?
        survives_2x: Profitable at 2x costs?
        max_survivable_multiplier: Highest multiplier where Sharpe > 0
    """

    levels: List[CostStressLevel] = field(default_factory=list)
    base_sharpe: float = 0.0
    breakeven_multiplier: float = 0.0
    survives_1_5x: bool = False
    survives_2x: bool = False
    max_survivable_multiplier: float = 0.0

    def to_dict(self) -> Dict[str, Any]:
        return {
            "base_sharpe": round(self.base_sharpe, 4),
            "breakeven_multiplier": round(self.breakeven_multiplier, 2),
            "survives_1_5x": self.survives_1_5x,
            "survives_2x": self.survives_2x,
            "max_survivable_multiplier": round(self.max_survivable_multiplier, 2),
            "levels": [level.to_dict() for level in self.levels],
        }


def cost_stress_test(
    base_sharpe: float,
    cost_multipliers: List[float],
    sharpe_at_costs: List[float],
    total_returns_at_costs: List[float] | None = None,
) -> CostStressResult:
    """Perform cost stress analysis.

    Args:
        base_sharpe: Sharpe at base costs
        cost_multipliers: List of cost multipliers to test
        sharpe_at_costs: Sharpe at each cost level
        total_returns_at_costs: Total return % at each cost level (optional)

    Returns:
        CostStressResult with breakeven analysis
    """
    if not cost_multipliers or not sharpe_at_costs:
        return CostStressResult(base_sharpe=base_sharpe)

    levels = []
    max_profitable = 0.0

    for i, mult in enumerate(cost_multipliers):
        sharpe = sharpe_at_costs[i] if i < len(sharpe_at_costs) else 0.0
        total_ret = total_returns_at_costs[i] if total_returns_at_costs and i < len(total_returns_at_costs) else 0.0

        is_profitable = sharpe > 0
        if is_profitable:
            max_profitable = mult

        levels.append(
            CostStressLevel(
                multiplier=mult,
                sharpe=sharpe,
                total_return_pct=total_ret,
                is_profitable=is_profitable,
            )
        )

    # Find breakeven multiplier (linear interpolation)
    breakeven = 0.0
    for i in range(1, len(levels)):
        if levels[i - 1].sharpe > 0 and levels[i].sharpe <= 0:
            # Interpolate
            s1, s2 = levels[i - 1].sharpe, levels[i].sharpe
            m1, m2 = levels[i - 1].multiplier, levels[i].multiplier
            if s1 != s2:
                breakeven = m1 + (0 - s1) * (m2 - m1) / (s2 - s1)
            break
    else:
        # All profitable or all unprofitable
        if levels and levels[-1].sharpe > 0:
            breakeven = float("inf")

    survives_1_5 = any(level.multiplier == 1.5 and level.is_profitable for level in levels)
    survives_2 = any(level.multiplier == 2.0 and level.is_profitable for level in levels)

    return CostStressResult(
        levels=levels,
        base_sharpe=base_sharpe,
        breakeven_multiplier=breakeven,
        survives_1_5x=survives_1_5,
        survives_2x=survives_2,
        max_survivable_multiplier=max_profitable,
    )
