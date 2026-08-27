#!/usr/bin/env python3
"""R4 Qualification Monitor — captures live evidence metrics.

Runs periodically to build the evidence table for the $5K qualification.
Tracks: entry slippage, spread, MAE/MFE, holding duration, P&L, etc.

Usage:
    python scripts/r4_qualification_monitor.py          # one-shot snapshot
    python scripts/r4_qualification_monitor.py --loop   # continuous
"""

from __future__ import annotations

import json
import os
import sys
import time
from datetime import datetime, timezone
from typing import Any, Dict

sys.path.insert(0, "src")

try:
    from mt5linux import MetaTrader5
except ImportError:
    MetaTrader5 = None

from eigencapital.live.position_attribution import classify_all, R4_MAGIC

EVIDENCE_DIR = "reports/r4_qualification/evidence"
EVIDENCE_FILE = os.path.join(EVIDENCE_DIR, "position_evidence.jsonl")


def capture_evidence() -> Dict[str, Any]:
    """Capture current state of all R4 positions for evidence tracking."""
    mt5 = MetaTrader5(host="127.0.0.1", port=8001)
    if not mt5.initialize():
        return {"error": "Cannot connect to MT5"}

    account = mt5.account_info()
    positions = list(mt5.positions_get() or [])
    classified = classify_all(
        [
            {
                "ticket": p.ticket,
                "symbol": p.symbol,
                "type": p.type,
                "volume": p.volume,
                "magic": p.magic,
                "comment": p.comment,
                "profit": p.profit,
                "price_open": p.price_open,
                "sl": p.sl,
                "tp": p.tp,
            }
            for p in positions
        ]
    )

    r4_positions = [p for p in positions if p.magic == R4_MAGIC]
    now = datetime.now(timezone.utc)

    evidence = {
        "timestamp": now.isoformat(),
        "account": {
            "equity": float(account.equity) if account else 0,
            "balance": float(account.balance) if account else 0,
            "free_margin": float(getattr(account, "margin_free", 0) or 0),
        },
        "positions": {
            "total": len(positions),
            "r4_count": len(r4_positions),
            "foreign_count": sum(1 for c in classified if c.pclass.value != "R4_BOT"),
        },
        "position_detail": [],
    }

    # Get current prices for MAE/MFE calculation
    for p in r4_positions:
        tick = mt5.symbol_info_tick(p.symbol)
        current_price = tick.ask if tick else p.price_open

        # MAE/MFE from entry
        direction = "LONG" if p.type == 0 else "SHORT"
        if direction == "LONG":
            mae_price = min(p.price_open, current_price)  # worst price
            mfe_price = max(p.price_open, current_price)  # best price
        else:
            mae_price = max(p.price_open, current_price)
            mfe_price = min(p.price_open, current_price)

        # Convert to % from entry
        mae_pct = abs(mae_price - p.price_open) / p.price_open * 100
        mfe_pct = abs(mfe_price - p.price_open) / p.price_open * 100

        # SL distance
        sl_distance_pct = (
            abs(p.sl - p.price_open) / p.price_open * 100 if p.sl > 0 else 0
        )

        # Loss at SL
        contract_size = 100000  # default forex
        info = mt5.symbol_info(p.symbol)
        if info:
            contract_size = info.trade_contract_size
        loss_at_sl = (
            sl_distance_pct / 100 * p.volume * contract_size * p.price_open
            if p.sl > 0
            else 0
        )

        # Spread
        spread_pts = info.spread if info else 0

        # Holding duration (approximate from order history)
        deals = mt5.history_deals_get(ticket=p.ticket)
        entry_time = ""
        if deals and len(deals) > 0:
            entry_time = str(deals[0].time)

        pos_detail = {
            "ticket": p.ticket,
            "symbol": p.symbol,
            "direction": direction,
            "volume": p.volume,
            "entry_price": p.price_open,
            "current_price": current_price,
            "sl": p.sl,
            "sl_distance_pct": round(sl_distance_pct, 2),
            "loss_at_sl": round(loss_at_sl, 2),
            "mae_pct": round(mae_pct, 2),
            "mfe_pct": round(mfe_pct, 2),
            "profit": round(p.profit, 2),
            "spread_pts": spread_pts,
            "entry_time": entry_time,
        }
        evidence["position_detail"].append(pos_detail)

    # Portfolio-level risk
    total_loss_at_sl = sum(p["loss_at_sl"] for p in evidence["position_detail"])
    total_profit = sum(p["profit"] for p in evidence["position_detail"])
    avg_sl_distance = (
        sum(p["sl_distance_pct"] for p in evidence["position_detail"])
        / len(evidence["position_detail"])
        if evidence["position_detail"]
        else 0
    )

    evidence["portfolio_risk"] = {
        "total_loss_at_sl": round(total_loss_at_sl, 2),
        "total_loss_at_sl_pct": round(
            total_loss_at_sl / evidence["account"]["equity"] * 100, 2
        )
        if evidence["account"]["equity"] > 0
        else 0,
        "total_unrealized_pnl": round(total_profit, 2),
        "avg_sl_distance_pct": round(avg_sl_distance, 2),
        "max_single_loss_at_sl": round(
            max(p["loss_at_sl"] for p in evidence["position_detail"]), 2
        )
        if evidence["position_detail"]
        else 0,
        "daily_loss_budget_remaining": round(
            250 - abs(min(0, total_profit)), 2
        ),  # rough estimate
    }

    mt5.shutdown()
    return evidence


def save_evidence(evidence: Dict[str, Any]) -> None:
    """Append evidence to JSONL file."""
    os.makedirs(EVIDENCE_DIR, exist_ok=True)
    with open(EVIDENCE_FILE, "a") as f:
        f.write(json.dumps(evidence, default=str) + "\n")


def print_evidence(evidence: Dict[str, Any]) -> None:
    """Print evidence in readable format."""
    print(f"\n{'=' * 70}")
    print("  R4 QUALIFICATION EVIDENCE SNAPSHOT")
    print(f"  {evidence['timestamp']}")
    print(f"{'=' * 70}")

    acc = evidence["account"]
    print(
        f"\nAccount: Equity=${acc['equity']:,.2f} | Balance=${acc['balance']:,.2f} | Free=${acc['free_margin']:,.2f}"
    )

    pos = evidence["positions"]
    print(
        f"Positions: {pos['total']} total ({pos['r4_count']} R4, {pos['foreign_count']} foreign)"
    )

    print(
        f"\n{'Ticket':<12} {'Symbol':<10} {'Dir':<6} {'Entry':>10} {'Current':>10} {'SL':>10} {'SL Dist':>8} {'Loss@SL':>10} {'MAE':>8} {'MFE':>8} {'P&L':>10}"
    )
    print("-" * 106)

    for p in evidence["position_detail"]:
        print(
            f"#{p['ticket']:<11} {p['symbol']:<10} {p['direction']:<6} "
            f"{p['entry_price']:>10.5f} {p['current_price']:>10.5f} "
            f"{p['sl']:>10.5f} {p['sl_distance_pct']:>7.2f}% "
            f"${p['loss_at_sl']:>9,.2f} {p['mae_pct']:>7.2f}% {p['mfe_pct']:>7.2f}% "
            f"${p['profit']:>9,.2f}"
        )

    risk = evidence["portfolio_risk"]
    print("\nPortfolio Risk:")
    print(
        f"  Total loss-at-SL: ${risk['total_loss_at_sl']:,.2f} ({risk['total_loss_at_sl_pct']:.2f}% of equity)"
    )
    print(f"  Total unrealized P&L: ${risk['total_unrealized_pnl']:,.2f}")
    print(f"  Avg SL distance: {risk['avg_sl_distance_pct']:.2f}%")
    print(f"  Max single loss-at-SL: ${risk['max_single_loss_at_sl']:,.2f}")
    print(f"{'=' * 70}")


def main():
    loop = "--loop" in sys.argv
    interval = 3600  # hourly
    for i, a in enumerate(sys.argv):
        if a == "--interval" and i + 1 < len(sys.argv):
            interval = int(sys.argv[i + 1])

    while True:
        evidence = capture_evidence()
        if "error" not in evidence:
            print_evidence(evidence)
            save_evidence(evidence)
        else:
            print(f"Error: {evidence['error']}")

        if not loop:
            break

        print(f"\nNext capture in {interval}s...")
        time.sleep(interval)


if __name__ == "__main__":
    main()
