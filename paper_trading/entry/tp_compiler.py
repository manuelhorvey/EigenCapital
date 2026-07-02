import logging

from paper_trading.entry.decision import MarketStructureState, TPGeometry, ValidityState

logger = logging.getLogger("eigencapital.paper_trading.tp_compiler")

# Maximum reward-to-risk ratio — prevents absurd TP distances from
# stacked convexity × regime × sl_mult multipliers.
# At 5.0 R:R even MOMENTUM_IGNITION (base convexity 6.0) gets capped.
MAX_RR = 5.0


def _load_tp_config() -> tuple[dict[str, float], dict[str, float]]:
    from paper_trading.config_manager import get_config

    cfg = get_config().defaults.get("tp_compiler", {})
    archetype_convexity = {
        "BREAKOUT_TEST": cfg.get("breakout_test_convexity", 5.0),
        "BREAKOUT": cfg.get("breakout_convexity", 5.0),
        "TREND_PULLBACK": cfg.get("trend_pullback_convexity", 4.0),
        "MEAN_REVERSION": cfg.get("mean_reversion_convexity", 3.0),
        "VOL_EXPANSION": cfg.get("vol_expansion_convexity", 4.5),
        "MOMENTUM_IGNITION": cfg.get("momentum_ignition_convexity", 6.0),
        "UNKNOWN": cfg.get("unknown_convexity", 3.0),
    }
    regime_multipliers = {
        "GREEN": cfg.get("regime_green", 1.0),
        "YELLOW": cfg.get("regime_yellow", 0.9),
        "RED": cfg.get("regime_red", 0.8),
        "calm": cfg.get("regime_calm", 1.0),
        "range": cfg.get("regime_range", 0.9),
        "trend": cfg.get("regime_trend", 1.2),
        "volatile": cfg.get("regime_volatile", 1.1),
        "crisis": cfg.get("regime_crisis", 0.6),
    }
    return archetype_convexity, regime_multipliers


def compute_take_profit(
    entry_price: float,
    sl_distance: float,
    regime: str | ValidityState,
    archetype: str,
    structure: MarketStructureState,
    tp_mult_override: float = 1.0,
) -> TPGeometry:
    """
    Pure functional compiler for reward geometry.
    Locked at entry, zero path dependency.
    """
    # 1. Resolve Convexity
    archetype_convexity, regime_multipliers = _load_tp_config()
    convexity = archetype_convexity.get(archetype.upper(), 1.0)

    # 2. Resolve Regime Multiplier
    # Allow passing either ValidityState or raw string from diagnostics
    reg_key = regime.value if isinstance(regime, ValidityState) else str(regime).lower()
    reg_mult = regime_multipliers.get(reg_key, 1.0)

    # 3. Final TP Distance Calculation
    # tp_distance = f(sl_distance) * multiplier * config_override
    tp_distance = sl_distance * convexity * reg_mult * tp_mult_override
    # Cap at MAX_RR to prevent absurdly wide TP from stacked multipliers
    capped_distance = sl_distance * MAX_RR
    if tp_distance > capped_distance:
        logger.debug(
            "capped TP %.2fR -> %.2fR (convexity=%.1f reg_mult=%.1f override=%.1f)",
            tp_distance / sl_distance,
            MAX_RR,
            convexity,
            reg_mult,
            tp_mult_override,
        )
        tp_distance = capped_distance

    # 4. Generate Scale-Out Tiers
    tiers = _generate_scale_out_profile(archetype, convexity)

    return TPGeometry(
        tp_distance=round(tp_distance, 6),
        scale_out_tiers=tiers,
        convexity_score=convexity,
        metadata={
            "archetype": archetype,
            "regime": reg_key,
            "reg_mult": reg_mult,
            "base_sl_dist": sl_distance,
            "tp_mult_override": tp_mult_override,
        },
    )


def _generate_scale_out_profile(archetype: str, convexity: float) -> list[tuple[float, float]]:
    """
    Deterministic execution schedule based on convexity.
    Returns list of (fraction_of_remaining, r_multiplier_of_tp_distance).
    """
    archetype = archetype.upper()

    # Low Convexity (Frontloaded): Capture quick reverts
    if convexity < 1.1 or archetype == "MEAN_REVERSION":
        return [
            (0.50, 0.50),  # Take 50% early
            (0.30, 0.80),  # Take 30% at 0.8R
            (0.20, 1.00),  # Take 20% at 1.0R
        ]

    # High Convexity (Backloaded): Let the tail run
    if convexity >= 1.5 or archetype in ["MOMENTUM_IGNITION", "BREAKOUT"]:
        return [
            (0.20, 0.50),  # Take 20% at 0.5R (breakeven trigger)
            (0.30, 1.00),  # Take 30% at 1.0R
            (0.50, 1.50),  # Take 50% at 1.5R (tail expansion)
        ]

    # Balanced (Trend Pullback)
    return [(1 / 3, 0.50), (1 / 3, 1.00), (1 / 3, 1.50)]
