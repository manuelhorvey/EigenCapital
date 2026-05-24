"""Partial profit-taking (scale-out) engine.

Splits a position into tiers that are closed incrementally as price
moves favourably.  After the first tier is taken, the remaining
position's stop is moved to breakeven.

Default tiers (configurable per asset):
  - Tier 1: 33 % at 50 % of original TP → lock breakeven on remainder
  - Tier 2: 33 % at 100 % of original TP
  - Tier 3: 34 % runs with trailing stop (or original TP if trailing
    not active)
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field

logger = logging.getLogger("quantforge.scale_out")


@dataclass
class ScaleOutTier:
    fraction: float
    price: float
    filled: bool = False
    fill_price: float | None = None
    pnl_realized: float = 0.0


@dataclass
class ScaleOutPlan:
    tiers: list[ScaleOutTier] = field(default_factory=list)
    entry_price: float = 0.0
    breakeven_activated: bool = False
    breakeven_price: float | None = None
    remaining_fraction: float = 1.0


class ScaleOutEngine:
    """Manages partial profit taking with breakeven stop.

    Parameters
    ----------
    tiers : list[tuple[float, float]]
        List of (fraction, price_multiplier) pairs.  Each tier closes
        ``fraction`` of the remaining position when price reaches
        ``entry ± price_multiplier * (TP - entry)``.
    activate_breakeven_after : int
        Index of tier after which the remaining stop is moved to
        breakeven (default 0 = after first tier).
    """

    def __init__(
        self,
        tiers: list[tuple[float, float]] | None = None,
        activate_breakeven_after: int = 0,
        trailing_after_tier: int | None = None,
    ):
        if tiers is None:
            tiers = [(1 / 3, 0.50), (1 / 3, 1.00), (1 / 3, 1.50)]
        self.tier_specs = tiers
        self.activate_breakeven_after = activate_breakeven_after
        self.trailing_after_tier = trailing_after_tier

        total = sum(f for f, _ in tiers)
        if abs(total - 1.0) > 1e-6:
            raise ValueError(f"Scale-out tiers must sum to 1.0, got {total:.4f}")

    def build_plan(
        self,
        side: str,
        entry_price: float,
        take_profit: float,
    ) -> ScaleOutPlan:
        """Create a scale-out plan from entry and TP price."""
        tp_total = abs(take_profit - entry_price)
        tiers = []
        for fraction, pct in self.tier_specs:
            price = entry_price + tp_total * pct if side == "long" else entry_price - tp_total * pct
            tiers.append(ScaleOutTier(fraction=fraction, price=price))
        return ScaleOutPlan(tiers=tiers, entry_price=entry_price, remaining_fraction=1.0)

    def check_tiers(
        self,
        plan: ScaleOutPlan,
        side: str,
        current_price: float,
        current_value: float,
        position_size: float,
        exposure_mult: float,
    ) -> list[dict]:
        """Check which unfilled tiers have been reached.

        Returns a list of trade dicts to execute (one per filled tier).
        Each dict contains ``fraction``, ``reason``, ``pnl``.
        """
        fills = []
        for tier in plan.tiers:
            if tier.filled:
                continue

            hit = current_price >= tier.price if side == "long" else current_price <= tier.price
            if not hit:
                continue

            tier.filled = True
            tier.fill_price = current_price
            entry_px = plan.entry_price
            pnl_frac = (current_price / entry_px - 1) if side == "long" else (entry_px / current_price - 1)
            tier_pnl = current_value * pnl_frac * position_size * exposure_mult * tier.fraction
            tier.pnl_realized = tier_pnl
            plan.remaining_fraction -= tier.fraction

            fills.append(
                {
                    "fraction": tier.fraction,
                    "fill_price": current_price,
                    "pnl": tier_pnl,
                    "reason": f"scale_out_tier_{_tier_index(plan, tier) + 1}",
                }
            )

        # Activate breakeven on the remainder
        n_filled = sum(1 for t in plan.tiers if t.filled)
        if n_filled > self.activate_breakeven_after and not plan.breakeven_activated and plan.remaining_fraction > 0:
            plan.breakeven_activated = True
            plan.breakeven_price = plan.entry_price
            fills.append(
                {
                    "fraction": 0.0,
                    "reason": "breakeven_stop_activated",
                    "breakeven_price": plan.entry_price,
                }
            )

        # Activate trailing on the remainder after a configurable tier index
        if self.trailing_after_tier is not None and plan.remaining_fraction > 0 and n_filled > self.trailing_after_tier:
            fills.append(
                {
                    "fraction": 0.0,
                    "reason": "trailing_activated",
                }
            )

        return fills

    def remaining_targets(self, plan: ScaleOutPlan) -> list[float]:
        """Return the target prices of unfilled tiers."""
        return [t.price for t in plan.tiers if not t.filled]


def _tier_index(plan: ScaleOutPlan, tier: ScaleOutTier) -> int:
    for i, t in enumerate(plan.tiers):
        if t is tier:
            return i
    return -1


def build_scale_out_from_config(asset_config: dict) -> ScaleOutEngine | None:
    """Construct engine from YAML config.  Returns None if disabled."""
    so_cfg = asset_config.get("scale_out")
    if not so_cfg or not so_cfg.get("enabled", False):
        return None
    tiers = so_cfg.get("tiers", [(1 / 3, 0.50), (1 / 3, 1.00), (1 / 3, 1.50)])
    activate_after = so_cfg.get("activate_breakeven_after", 0)
    trailing_after = so_cfg.get("trailing_after_tier")
    parsed = []
    for t in tiers:
        if isinstance(t, dict):
            parsed.append((t["fraction"], t["multiplier"]))
        else:
            parsed.append(t)
    return ScaleOutEngine(
        tiers=parsed,
        activate_breakeven_after=activate_after,
        trailing_after_tier=trailing_after,
    )
