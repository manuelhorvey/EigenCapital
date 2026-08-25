"""Instrument Eligibility — broker-derived tradable universe at capital scale.

Computes the actual minimum tradable notional for each R4 symbol
from live MT5 contract specifications, then classifies each as
ELIGIBLE or INELIGIBLE against the campaign position limit.

This makes the distinction explicit:
  Research universe (15 symbols) ≠ Executable universe (broker-constrained)

The exclusion is mechanical, not hand-picked:
  min_tradable_notional = volume_min × current_ask × trade_contract_size

If min_tradable_notional > max_position_size → INELIGIBLE.

Usage:
    python scripts/instrument_eligibility.py [--position-limit 1500]
"""

from __future__ import annotations

import json
import os
import sys
from typing import Any, Dict, List

sys.path.insert(0, "src")

from mt5linux import MetaTrader5

R4_UNIVERSE = [
    "US30", "AUDJPY", "AUDUSD", "AUDCHF", "AUDCAD",
    "NZDJPY", "GBPJPY", "AUDNZD", "NZDUSD", "NZDCHF",
    "NZDCAD", "GBPUSD", "GBPCHF", "GBPCAD", "CHFJPY",
    "EURJPY", "USDJPY", "CADJPY", "XAUUSD", "EURUSD",
    "EURCHF", "USDCHF", "EURCAD", "USDCAD", "CADCHF",
    "GBPNZD", "EURGBP", "EURNZD", "GBPAUD", "EURAUD",
    "BTCUSD",
]

ASSET_CLASSES = {
    "US30": "indices", "AUDJPY": "forex", "AUDUSD": "forex",
    "AUDCHF": "forex", "AUDCAD": "forex", "NZDJPY": "forex",
    "GBPJPY": "forex", "AUDNZD": "forex", "NZDUSD": "forex",
    "NZDCHF": "forex", "NZDCAD": "forex", "GBPUSD": "forex",
    "GBPCHF": "forex", "GBPCAD": "forex", "CHFJPY": "forex",
    "EURJPY": "forex", "USDJPY": "forex", "CADJPY": "forex",
    "XAUUSD": "metals", "EURUSD": "forex", "EURCHF": "forex",
    "USDCHF": "forex", "EURCAD": "forex", "USDCAD": "forex",
    "CADCHF": "forex", "GBPNZD": "forex", "EURGBP": "forex",
    "EURNZD": "forex", "GBPAUD": "forex", "EURAUD": "forex",
    "BTCUSD": "crypto",
}


def check_eligibility(mt5, position_limit: float) -> Dict[str, Any]:
    """Check each symbol's eligibility against the position limit."""
    results = []

    for sym in R4_UNIVERSE:
        mt5.symbol_select(sym, True)
        info = mt5.symbol_info(sym)
        tick = mt5.symbol_info_tick(sym)

        if info is None or tick is None:
            results.append({
                "symbol": sym,
                "asset_class": ASSET_CLASSES.get(sym, "unknown"),
                "eligible": False,
                "reason": "symbol not available on broker",
                "min_volume": 0,
                "current_ask": 0,
                "contract_size": 0,
                "min_notional": 0,
                "position_limit": position_limit,
            })
            continue

        min_vol = info.volume_min
        ask = tick.ask
        cs = info.trade_contract_size
        min_notional = min_vol * ask * cs

        eligible = min_notional <= position_limit
        reason = (
            f"min lot {min_vol} × {ask:.5f} × {cs:,.0f} = ${min_notional:,.2f}"
            + (f" ≤ ${position_limit:,.0f}" if eligible else f" > ${position_limit:,.0f}")
        )

        results.append({
            "symbol": sym,
            "asset_class": ASSET_CLASSES.get(sym, "unknown"),
            "eligible": eligible,
            "reason": reason,
            "min_volume": min_vol,
            "volume_step": info.volume_step,
            "current_ask": ask,
            "current_bid": tick.bid,
            "spread": info.spread,
            "contract_size": cs,
            "digits": info.digits,
            "min_notional": round(min_notional, 2),
            "position_limit": position_limit,
        })

    return {
        "position_limit": position_limit,
        "total_symbols": len(R4_UNIVERSE),
        "eligible_count": sum(1 for r in results if r["eligible"]),
        "ineligible_count": sum(1 for r in results if not r["eligible"]),
        "symbols": results,
    }


def format_report(result: Dict[str, Any]) -> str:
    """Format eligibility as readable report."""
    lines = [
        "# Capital-Scale Instrument Eligibility",
        "",
        f"**Position Limit:** ${result['position_limit']:,.0f}",
        f"**Eligible:** {result['eligible_count']}/{result['total_symbols']}",
        f"**Ineligible:** {result['ineligible_count']}/{result['total_symbols']}",
        "",
        "## Eligible Instruments",
        "",
        "| Symbol | Asset Class | Min Vol | Ask | Contract | Min Notional | Status |",
        "|---|---|---|---|---|---|---|",
    ]

    for s in result["symbols"]:
        if s["eligible"]:
            lines.append(
                f"| {s['symbol']} | {s['asset_class']} | {s['min_volume']} | "
                f"{s['current_ask']:.5f} | {s['contract_size']:,.0f} | "
                f"${s['min_notional']:,.2f} | ✅ ELIGIBLE |"
            )

    lines.extend([
        "",
        "## Ineligible Instruments",
        "",
        "| Symbol | Asset Class | Min Vol | Ask | Contract | Min Notional | Reason |",
        "|---|---|---|---|---|---|---|",
    ])

    for s in result["symbols"]:
        if not s["eligible"]:
            lines.append(
                f"| {s['symbol']} | {s['asset_class']} | {s['min_volume']} | "
                f"{s['current_ask']:.5f} | {s['contract_size']:,.0f} | "
                f"${s['min_notional']:,.2f} | ❌ {s['reason']} |"
            )

    lines.extend([
        "",
        "## Key Insight",
        "",
        "**Research universe ≠ executable universe at every capital scale.**",
        "The $5K MINIMAL campaign can only trade instruments whose minimum",
        "tradable notional fits within the position limit. This is",
        "broker-derived, not hand-picked.",
    ])

    return "\n".join(lines)


def main() -> None:
    position_limit = 1_500.0
    for i, a in enumerate(sys.argv[1:]):
        if a == "--position-limit" and i + 1 < len(sys.argv):
            position_limit = float(sys.argv[i + 2])

    print("=" * 60)
    print("  INSTRUMENT ELIGIBILITY CHECK")
    print(f"  Position limit: ${position_limit:,.0f}")
    print("=" * 60)

    mt5 = MetaTrader5(host="127.0.0.1", port=8001)
    if not mt5.initialize():
        print(f"  ❌ Cannot connect: {mt5.last_error()}")
        return

    result = check_eligibility(mt5, position_limit)
    mt5.shutdown()

    # Print results
    print(f"\n  Eligible: {result['eligible_count']}/{result['total_symbols']}")
    print(f"  Ineligible: {result['ineligible_count']}/{result['total_symbols']}\n")

    for s in result["symbols"]:
        icon = "✅" if s["eligible"] else "❌"
        print(f"  {icon} {s['symbol']:<10} {s['asset_class']:<10} "
              f"min_notional=${s['min_notional']:>10,.2f}  {s['reason']}")

    # Save
    os.makedirs("reports", exist_ok=True)

    with open("reports/instrument_eligibility.json", "w") as f:
        json.dump(result, f, indent=2, default=str)

    with open("reports/instrument_eligibility.md", "w") as f:
        f.write(format_report(result))

    print(f"\n  Saved: reports/instrument_eligibility.json")
    print(f"  Saved: reports/instrument_eligibility.md")


if __name__ == "__main__":
    main()
