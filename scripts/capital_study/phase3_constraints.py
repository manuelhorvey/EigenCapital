#!/usr/bin/env python3
"""Phase 3 — Capacity Constraints Assessment.

Identifies practical capital deployment limits imposed by:
- Position sizing rules (15% max position, 2% risk per trade)
- Broker limitations (MT5 lot sizes)
- Margin requirements
- Liquidity assumptions
- Max concurrent positions (8)
- Max leverage (2.0x)
- Factor exposure limits (CHF 20%, AUD 25%, etc.)
- Execution quality / slippage
"""

from __future__ import annotations

import json
import logging
import sys
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT))

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger("eigencapital.capital_study.phase3")

OUTPUT_DIR = ROOT / "data" / "processed"
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

# Production config
BASE_CAPITAL = 100_000
MAX_POSITION_PCT = 0.15
MAX_RISK_PER_TRADE_PCT = 0.02
MAX_CONCURRENT = 8
MAX_LEVERAGE = 2.0
MIN_CONFIDENCE = 0.55

FACTOR_LIMITS = {
    "CHF": 0.20, "AUD": 0.25, "NZD": 0.25, "JPY": 0.25,
    "GOLD": 0.15, "FX_MAJOR": 0.40, "FX_CROSS": 0.40,
}

# Asset-to-factor mapping (from configs/domains/modes/production.yaml)
ASSET_FACTORS = {
    "GC": ["GOLD"],
    "USDCHF": ["CHF", "FX_MAJOR"],
    "USDCAD": ["FX_MAJOR"], "GBPCAD": ["FX_CROSS"],
    "NZDCAD": ["NZD", "FX_CROSS"], "NZDUSD": ["NZD", "FX_MAJOR"],
    "GBPAUD": ["AUD", "FX_CROSS"], "NZDCHF": ["NZD", "CHF", "FX_CROSS"],
    "CADCHF": ["CHF", "FX_CROSS"], "AUDUSD": ["AUD", "FX_MAJOR"],
    "EURCHF": ["CHF", "FX_MAJOR"], "EURCAD": ["FX_CROSS"],
    "EURNZD": ["NZD", "FX_CROSS"], "GBPCHF": ["CHF", "FX_CROSS"],
    "GBPUSD": ["FX_MAJOR"], "EURAUD": ["AUD", "FX_CROSS"],
    "BTCUSD": [], "^DJI": [],
    "AUDJPY": ["AUD", "JPY", "FX_CROSS"],
    "NZDJPY": ["NZD", "JPY", "FX_CROSS"],
    "GBPJPY": ["JPY", "FX_CROSS"],
    "USDJPY": ["JPY", "FX_MAJOR"],
}


def analyze_capital_level(capital: float, label: str) -> dict:
    """Compute binding constraints at a given capital level."""
    max_position_notional = capital * MAX_POSITION_PCT
    max_total_notional = capital * MAX_LEVERAGE
    max_concurrent_notional = MAX_CONCURRENT * max_position_notional

    # Factor capacity: how much can we allocate to each group
    factor_capacity = {}
    for factor, limit in FACTOR_LIMITS.items():
        factor_capacity[factor] = capital * limit

    # CHF factor: restricted to 20%, but only ~3 CHF assets
    chf_assets = [a for a, f in ASSET_FACTORS.items() if "CHF" in f]
    chf_capacity_per_asset = capital * FACTOR_LIMITS["CHF"] / max(len(chf_assets), 1)

    # Slippage analysis
    slippage_rms = 0.0174  # from live estimate
    slippage_cost_per_trade = slippage_rms * max_position_notional
    slippage_pct_of_capital = slippage_cost_per_trade / capital if capital > 0 else 0.0

    # MT5 lot constraints
    # Min lot = 0.01 for FX, notional ≈ $1,150 for EURUSD
    min_lot_notional = 1150
    trades_blocked_by_min_lot = max_position_notional < min_lot_notional

    # Constraint knees: capital levels where each starts binding
    knees = {}
    # Max concurrent & max position: knee = capital where max_concurrent_notional >= max_total_notional
    if max_concurrent_notional >= max_total_notional:
        knees["max_concurrent_vs_leverage"] = "leverage_binding"
    else:
        knee_leverage = max_concurrent_notional / MAX_LEVERAGE
        knees["max_concurrent_vs_leverage"] = f"concurrent_binding_above_{knee_leverage:,.0f}"

    # Factor CHF capacity
    chf_knee = max_total_notional / FACTOR_LIMITS.get("CHF", 1.0)
    knees["chf_factor_capacity"] = f"${chf_capacity_per_asset:,.0f}_per_CHF_asset"

    return {
        "scenario": label,
        "capital": capital,
        "max_position_notional": round(max_position_notional, 2),
        "max_total_notional": round(max_total_notional, 2),
        "max_concurrent_notional": round(max_concurrent_notional, 2),
        "max_risk_per_trade": round(capital * MAX_RISK_PER_TRADE_PCT, 2),
        "factor_capacities": {
            k: round(v, 2) for k, v in factor_capacity.items()
        },
        "chf_assets": chf_assets,
        "chf_capacity_per_asset": round(chf_capacity_per_asset, 2),
        "slippage": {
            "rms_pct": slippage_rms,
            "cost_per_full_position": round(slippage_cost_per_trade, 2),
            "cost_pct_of_capital": round(slippage_pct_of_capital * 100, 4),
        },
        "mt5_min_lot_blocked": trades_blocked_by_min_lot,
        "binding_constraints": [] if max_concurrent_notional >= max_total_notional else ["max_concurrent"],
        "primary_constraint": (
            "max_leverage" if max_total_notional <= max_concurrent_notional else "max_concurrent"
        ),
    }


def main():
    scenarios = [100_000, 125_000, 150_000, 200_000, 300_000, 600_000, 1_000_000]
    labels = ["baseline", "plus_25pct", "plus_50pct", "plus_100pct", "plus_200pct", "plus_500pct", "plus_1000pct"]

    results = []
    for capital, label in zip(scenarios, labels):
        r = analyze_capital_level(capital, label)
        results.append(r)
        logger.info(
            "  %s ($%d): max_position=$%.0f max_total=$%.0f CHF_cap=$%.0f/%s",
            label, capital,
            r["max_position_notional"], r["max_total_notional"],
            r["chf_capacity_per_asset"], r["primary_constraint"],
        )

    # Find the "knee" — where constraints start to bind materially
    # Max position notional vs. avg FX position size ($115K for EURUSD min lot)
    avg_fx_position = 115_000  # rough avg notional for one FX position
    capital_for_one_fx_position = avg_fx_position / MAX_POSITION_PCT
    capital_for_one_chf_position = capital_for_one_fx_position / len(
        [a for a, f in ASSET_FACTORS.items() if "CHF" in f]
    )

    output = {
        "scenarios": results,
        "constraint_knees": {
            "one_fx_position_knee": round(capital_for_one_fx_position),
            "one_chf_position_knee": round(capital_for_one_chf_position * len(
                [a for a, f in ASSET_FACTORS.items() if "CHF" in f]
            )),
            "leverage_binding_at": "Never_binding_under_current_config" if 1_000_000 * MAX_LEVERAGE > MAX_CONCURRENT * 1_000_000 * MAX_POSITION_PCT else "800000",
            "concurrent_binding_knee": "Always_binding_above_8_positions",
        },
        "hard_limits": {
            "max_leverage": MAX_LEVERAGE,
            "max_concurrent_positions": MAX_CONCURRENT,
            "max_position_pct": MAX_POSITION_PCT,
            "max_risk_per_trade_pct": MAX_RISK_PER_TRADE_PCT,
            "min_confidence": MIN_CONFIDENCE,
            "factor_limits": FACTOR_LIMITS,
        },
        "interpretation": (
            "Under the current config, max_concurrent=8 and max_position_pct=0.15 "
            "are the primary scaling constraints. At $1M capital, each of 8 positions "
            "can be up to $150K, totaling $1.2M — within the $2M leverage budget. "
            "The CHF factor limit (20%) caps CHF-exposed assets. Slippage at 1.74% RMS "
            "is manageable but would cost ~$2,610 per full position at $1M (0.26% of capital). "
            "MT5 min lot ($1,150) is not a binding constraint at any level."
        ),
    }

    path = OUTPUT_DIR / "phase3_constraints.json"
    with open(path, "w") as f:
        json.dump(output, f, indent=2)
    logger.info("Constraints analysis → %s", path)

    print("\n" + "=" * 72)
    print("PHASE 3 — CAPACITY CONSTRAINTS")
    print("=" * 72)
    print(f"{'Scenario':<20s} {'Capital':>10s} {'Max Position':>12s} {'Max Total':>12s} {'CHF/Asset':>10s} {'Primary':>14s}")
    print("-" * 72)
    for r in results:
        print(f"{r['scenario']:<20s} ${r['capital']:>8,d} ${r['max_position_notional']:>9,.0f} ${r['max_total_notional']:>9,.0f} ${r['chf_capacity_per_asset']:>7,.0f} {r['primary_constraint']:>14s}")
    print("-" * 72)
    for k, v in output["constraint_knees"].items():
        print(f"  {k:40s}: {v}")
    print("=" * 72)


if __name__ == "__main__":
    main()
