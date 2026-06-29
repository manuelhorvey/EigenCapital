from __future__ import annotations

import logging
from dataclasses import dataclass, field

logger = logging.getLogger("quantforge.sizing_chain")


@dataclass
class SizingInput:
    """Pure data — no references to AssetEngine or broker internals."""

    equity: float
    """Total equity for this path (paper $100K or MT5 broker balance)."""

    drawdown_pct: float
    """Current drawdown fraction (e.g. -0.03 = -3%)."""

    size_scalar: float = 1.0
    """Composite multiplier from governance, meta, kelly, etc. (paper path only)."""

    kelly_multiplier: float = 1.0
    """Kelly fraction cap (MT5 applies before position cap, paper in size_scalar)."""

    max_position_pct: float = 0.15
    max_risk_pct: float = 2.0
    min_viable_pct: float = 0.01

    drawdown_taper_start: float = -0.05
    drawdown_taper_end: float = -0.15
    drawdown_taper_min: float = 0.50

    entry_price: float = 0.0
    sl_distance: float = 0.0
    """Stop-loss distance from entry (absolute price difference)."""

    is_mt5: bool = False
    """If True, use MT5 sizing path (kelly + max_position_pct instead of size_scalar)."""


    """broker._quantity_to_lots or None."""
    ticker: str = ""


@dataclass
class SizingResult:
    notional: float = 0.0
    quantity: float = 0.0
    is_viable: bool = False
    skip_reason: str | None = None

    drawdown_taper: float = 1.0
    effective_cap: float = 0.0
    size_scalar_applied: float = 1.0
    kelly_applied: float = 1.0
    position_cap: float = 0.0
    risk_cap_used: float = 0.0
    min_viable_notional: float = 0.0
    chain_breakdown: dict = field(default_factory=dict)


class SizingChain:
    """Composable multiplicative guardrail chain.

    Separates the sizing computation from broker/engine internals.
    Two common configurations:

        paper_input = SizingInput(equity=100_000, ...)
        result = SizingChain.compute_paper(input, effective_cap, size_scalar)

        mt5_input = SizingInput(equity=broker_balance, is_mt5=True, ...)
        result = SizingChain.compute_mt5(input)
    """

    @staticmethod
    def drawdown_taper(
        current_dd: float,
        start_dd: float = -0.05,
        end_dd: float = -0.15,
        min_size: float = 0.50,
    ) -> float:
        if current_dd >= start_dd:
            return 1.0
        if current_dd <= end_dd:
            return min_size
        t = (current_dd - start_dd) / (end_dd - start_dd)
        return max(1.0 - t * (1.0 - min_size), min_size)

    @classmethod
    def compute(cls, inp: SizingInput) -> SizingResult:
        """Run the full sizing guardrail chain and return a SizingResult."""
        res = SizingResult()

        # 1 — Drawdown taper
        res.drawdown_taper = cls.drawdown_taper(
            inp.drawdown_pct,
            inp.drawdown_taper_start,
            inp.drawdown_taper_end,
            inp.drawdown_taper_min,
        )

        if inp.is_mt5:
            effective_cap = inp.equity
            res.effective_cap = effective_cap
            notional = effective_cap * inp.max_position_pct * res.drawdown_taper * inp.kelly_multiplier
            res.kelly_applied = inp.kelly_multiplier
            res.size_scalar_applied = inp.max_position_pct * res.drawdown_taper * inp.kelly_multiplier
        else:
            effective_cap = inp.equity
            res.effective_cap = effective_cap
            notional = effective_cap * inp.size_scalar
            res.size_scalar_applied = inp.size_scalar

        # 2 — Per-position equity cap
        max_pos_notional = inp.max_position_pct * inp.equity if inp.equity > 0 else float("inf")
        res.position_cap = max_pos_notional
        if notional > max_pos_notional:
            notional = max_pos_notional

        sl_dist = inp.sl_distance
        entry_price = inp.entry_price

        # 3 — Risk-per-trade cap
        max_risk_usd = inp.max_risk_pct / 100.0 * inp.equity if inp.equity > 0 else float("inf")
        min_viable_notional = inp.min_viable_pct * inp.equity if inp.equity > 0 else 0.0
        res.min_viable_notional = min_viable_notional

        risk_usd = sl_dist * (notional / entry_price) if sl_dist > 0 and entry_price > 0 else 0.0
        res.risk_cap_used = max_risk_usd if inp.equity > 0 else 0.0

        if inp.equity > 0 and risk_usd > max_risk_usd:
            capped_qty = max_risk_usd / sl_dist if sl_dist > 0 else 0.0
            capped_notional = capped_qty * entry_price
            if capped_notional < min_viable_notional:
                res.skip_reason = "below_min_viable"
                tag = "MT5" if inp.is_mt5 else ""
                logger.info(
                    "%s %s: entry skipped — risk cap (%.2f%%) would shrink position below min viable (%.2f%%)",
                    inp.ticker,
                    tag,
                    inp.max_risk_pct,
                    inp.min_viable_pct * 100,
                )
                return res
            notional = capped_notional

        res.notional = notional
        qty = max(notional / entry_price, 1e-6) if entry_price > 0 else 0.0

        res.quantity = qty
        res.is_viable = True

        res.chain_breakdown = {
            "drawdown_taper": round(res.drawdown_taper, 4),
            "effective_cap": round(res.effective_cap, 2),
            "size_scalar": round(res.size_scalar_applied, 4),
            "kelly": round(res.kelly_applied, 4),
            "position_cap": round(res.position_cap, 2),
            "risk_cap": round(res.risk_cap_used, 2),
            "final_notional": round(res.notional, 2),
            "quantity": round(res.quantity, 6),
        }

        return res
