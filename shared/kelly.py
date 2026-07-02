"""Fractional Kelly sizing — converts calibrated probability + barriers into position size multiplier.

This is P2 in the portfolio maturity framework (sizing transformation layer).
Kelly criterion is the provably optimal growth-optimal betting strategy for
sequential binary bets with known probabilities.

Formula (standard Kelly for binary bets with asymmetric payoffs):
    f* = p - q * sl_mult / tp_mult

    where:
        f* = full Kelly fraction (fraction of capital to risk)
        p  = calibrated P(TP hit)
        q  = 1 - p
        tp_mult = take profit multiplier (R units gained on win)
        sl_mult = stop loss multiplier (R units lost on loss)

Fractional Kelly:
    f = f* * fraction  (typically fraction=0.25 for quarter-Kelly)

Edge check:
    edge = p * tp_mult - q * sl_mult  (expected return in R)
    If edge <= min_edge, no edge -> skip trade.

Usage:
    from shared.kelly import compute_kelly_size

    adjusted = compute_kelly_size(
        base_size=0.05,
        prob_long=0.65,
        tp_mult=2.0,
        sl_mult=1.0,
        fraction=0.25,
    )
"""

from __future__ import annotations

import logging

logger = logging.getLogger("eigencapital.kelly")


def compute_edge(prob_long: float, tp_mult: float, sl_mult: float) -> float:
    """Compute expected return (edge) in R-multiples.

    Args:
        prob_long: P(TP hit) in [0, 1]
        tp_mult: TP multiplier (R units gained on TP hit)
        sl_mult: SL multiplier (R units lost on SL hit)

    Returns:
        Expected return in R units. Negative means no edge.
    """
    q = 1.0 - prob_long
    return prob_long * tp_mult - q * sl_mult


def compute_kelly_fraction(prob_long: float, tp_mult: float, sl_mult: float) -> float:
    """Compute full Kelly fraction f*.

    f* = p - q * sl / tp

    Equivalent to standard Kelly for binary bet with asymmetric payoff:
        f* = (b * p - q) / b   where b = tp_mult / sl_mult

    Returns:
        Kelly fraction. Returns 0.0 if no edge (negative or zero).
    """
    if not (0.0 < prob_long < 1.0):
        return 0.0
    q = 1.0 - prob_long
    edge = prob_long * tp_mult - q * sl_mult
    if edge <= 0:
        return 0.0
    b = tp_mult / sl_mult
    return max(0.0, (b * prob_long - q) / b)


def compute_kelly_multiplier(
    prob_long: float,
    tp_mult: float,
    sl_mult: float,
    fraction: float = 0.25,
    max_cap: float = 1.0,
    min_edge: float = 0.0,
) -> float:
    """Compute Kelly multiplier for a position.

    The multiplier is applied to the base position size from the sizing
    strategy. Returns 0.0 if no edge (trade should be skipped).

    Args:
        prob_long: Calibrated P(TP hit) in [0, 1]
        tp_mult: TP multiplier
        sl_mult: SL multiplier
        fraction: Kelly fraction (0.25 = quarter Kelly). Must be in (0, 1].
        max_cap: Maximum multiplier cap. Must be in (0, inf).
        min_edge: Minimum edge (expected R) required to trade.

    Returns:
        Multiplier in [0, max_cap]. 0 means skip the trade.
    """
    edge = compute_edge(prob_long, tp_mult, sl_mult)
    if edge < min_edge:
        return 0.0
    kelly_f = compute_kelly_fraction(prob_long, tp_mult, sl_mult)
    if kelly_f <= 0:
        return 0.0
    return min(kelly_f * fraction, max_cap)


def compute_kelly_size(
    base_size: float,
    prob_long: float,
    tp_mult: float,
    sl_mult: float,
    fraction: float = 0.25,
    max_cap: float = 1.0,
    min_edge: float = 0.0,
) -> float:
    """Compute Kelly-adjusted position size.

    Args:
        base_size: Base position size from the sizing strategy.
        prob_long: Calibrated P(TP hit) in [0, 1].
        tp_mult: TP multiplier.
        sl_mult: SL multiplier.
        fraction: Kelly fraction (default 0.25 = quarter Kelly).
        max_cap: Maximum multiplier cap (default 1.0 = no increase).
        min_edge: Minimum edge in R to trade (default 0.0).

    Returns:
        Adjusted position size. Returns 0.0 if no edge.
    """
    multiplier = compute_kelly_multiplier(prob_long, tp_mult, sl_mult, fraction, max_cap, min_edge)
    return base_size * multiplier


def edge_description(prob_long: float, tp_mult: float, sl_mult: float) -> str:
    """Human-readable edge description for logging."""
    edge = compute_edge(prob_long, tp_mult, sl_mult)
    kelly = compute_kelly_fraction(prob_long, tp_mult, sl_mult)
    return f"edge={edge:.4f}R, kelly_f={kelly:.4f}, prob={prob_long:.3f}, tp={tp_mult:.1f}, sl={sl_mult:.1f}"
