#!/usr/bin/env python3
"""R4 Live Attestation — proves ownership, attribution, and quarantine.

Derives an honest attestation from actual broker state:
  - Every position classified (R4_BOT / MANUAL / FOREIGN)
  - Deal history attributed by magic
  - Quarantine behavior verified (foreign → block new entries)
  - No silent assertions — broker state is the source of truth

Usage:
    python scripts/r4_attestation.py
"""

from __future__ import annotations

import json
import os
import sys
from datetime import UTC, datetime
from typing import Any, Dict

sys.path.insert(0, "src")

try:
    from mt5linux import MetaTrader5
except ImportError:
    MetaTrader5 = None

from eigencapital.config import load_config
from eigencapital.live.position_attribution import (
    R4_MAGIC,
    capacity_account,
    classify_all,
    ledger_from_deals,
    snapshot_hash,
)
from eigencapital.production_qual.fingerprint_verifier import FingerprintVerifier


def generate_attestation() -> Dict[str, Any]:
    """Generate a live attestation from broker state."""
    now = datetime.now(UTC)

    mt5 = MetaTrader5(host="127.0.0.1", port=8001)
    if not mt5.initialize():
        raise ConnectionError(f"Cannot connect to MT5: {mt5.last_error()}")

    account = mt5.account_info()
    config = load_config("production")

    # ── Position classification ───────────────────────────────────
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

    capacity = capacity_account(classified, config.capital.max_concurrent_positions)

    # ── Deal attribution ──────────────────────────────────────────
    deals = mt5.history_deals_get(0)  # all deals
    deal_list = []
    if deals:
        for d in deals:
            deal_list.append(
                {
                    "ticket": d.ticket,
                    "order": d.order,
                    "time": str(d.time),
                    "type": d.type,
                    "entry": d.entry,
                    "magic": d.magic,
                    "volume": d.volume,
                    "price": d.price,
                    "profit": d.profit,
                    "commission": d.commission,
                    "swap": d.swap,
                    "symbol": d.symbol,
                    "comment": d.comment,
                }
            )

    ledger = ledger_from_deals(deal_list)

    # ── Fingerprint ───────────────────────────────────────────────
    verifier = FingerprintVerifier(config=config)
    fp_result = verifier.verify_all()

    # ── Broker state hash ─────────────────────────────────────────
    broker_hash = snapshot_hash(
        [
            {
                "ticket": p.ticket,
                "symbol": p.symbol,
                "volume": p.volume,
                "type": p.type,
                "magic": p.magic,
            }
            for p in positions
        ],
        float(account.equity),
        float(getattr(account, "margin_free", 0) or 0),
    )

    # ── Build attestation ─────────────────────────────────────────
    position_summary = []
    for p in positions:
        cls = [c for c in classified if c.ticket == p.ticket][0]
        position_summary.append(
            {
                "ticket": p.ticket,
                "symbol": p.symbol,
                "direction": "LONG" if p.type == 0 else "SHORT",
                "volume": p.volume,
                "magic": p.magic,
                "classification": cls.pclass.value,
                "profit": p.profit,
                "has_sl": p.sl > 0,
            }
        )

    r4_positions = [p for p in position_summary if p["classification"] == "R4_BOT"]
    foreign_positions = [p for p in position_summary if p["classification"] != "R4_BOT"]

    attestation = {
        "attestation_timestamp": now.isoformat(),
        "account_id": int(account.login),
        "balance": float(account.balance),
        "equity": float(account.equity),
        "free_margin": float(getattr(account, "margin_free", 0) or 0),
        "positions": {
            "total": len(positions),
            "r4_count": len(r4_positions),
            "foreign_count": len(foreign_positions),
            "detail": position_summary,
        },
        "ownership": {
            "all_r4_owned": len(foreign_positions) == 0,
            "r4_magic": R4_MAGIC,
            "attribution_method": "magic_number",
        },
        "quarantine": {
            "contamination_detected": capacity.contaminated,
            "new_entries_allowed": capacity.allow_new_entries,
            "self_rotation_allowed": capacity.allow_self_rotation,
            "foreign_positions": foreign_positions,
            "quarantine_rule": "foreign_positions → block_new_entries, allow_self_rotation",
        },
        "deal_attribution": {
            "total_deals": ledger.n_deals,
            "unattributable_deals": ledger.n_unattributable,
            "attestation_valid": ledger.attestation_valid,
            "by_owner": ledger.by_magic,
        },
        "fingerprint": {
            "all_verified": fp_result.all_verified,
            "checks": [c.to_dict() for c in fp_result.checks],
        },
        "broker_state_hash": broker_hash,
        "risk_limits_enforced": {
            "max_concurrent": config.capital.max_concurrent_positions,
            "max_position_size": config.capital.max_position_size,
            "max_daily_loss": config.live_risk.max_daily_loss,
        },
    }

    # Compute attestation hash
    attestation_hash = json.dumps(attestation, sort_keys=True, default=str)
    import hashlib

    attestation["attestation_hash"] = hashlib.sha256(attestation_hash.encode()).hexdigest()

    mt5.shutdown()
    return attestation


def main():
    print("=" * 70)
    print("  R4 LIVE ATTESTATION")
    print("  Proves ownership, attribution, and quarantine behavior")
    print("=" * 70)

    att = generate_attestation()

    print(f"\nAccount: {att['account_id']}")
    print(f"Balance: ${att['balance']:,.2f} | Equity: ${att['equity']:,.2f}")
    print(
        f"Positions: {att['positions']['total']} ({att['positions']['r4_count']} R4, {att['positions']['foreign_count']} foreign)"
    )
    print(f"Ownership: {'✅ all R4-owned' if att['ownership']['all_r4_owned'] else '⚠️ FOREIGN POSITIONS PRESENT'}")
    print(f"Quarantine: {'⚠️ CONTAMINATED' if att['quarantine']['contamination_detected'] else '✅ clean'}")
    print(
        f"Deal Attribution: {'✅ valid' if att['deal_attribution']['attestation_valid'] else '⚠️ unattributable deals'}"
    )
    print(f"Fingerprint: {'✅ verified' if att['fingerprint']['all_verified'] else '❌ MISMATCH'}")

    if att["positions"]["foreign_count"] > 0:
        print("\n⚠️ FOREIGN POSITIONS DETECTED:")
        for fp in att["quarantine"]["foreign_positions"]:
            print(f"  🔴 #{fp['ticket']} {fp['symbol']} magic={fp['magic']} — QUARANTINED")

    # Position listing
    print("\nPosition Classification:")
    for p in att["positions"]["detail"]:
        icon = "🟢" if p["classification"] == "R4_BOT" else "🔴"
        sl_icon = "✅" if p["has_sl"] else "⚠️"
        print(
            f"  {icon} #{p['ticket']} {p['symbol']} {p['direction']} {p['volume']:.2f} [{p['classification']}] SL={sl_icon} P&L=${p['profit']:.2f}"
        )

    # Deal attribution summary
    print(f"\nDeal Attribution ({att['deal_attribution']['total_deals']} deals):")
    for owner, agg in att["deal_attribution"]["by_owner"].items():
        print(f"  {owner}: {agg['deals']} deals, P&L=${agg['realized_pnl']:.2f}")

    print(f"\nAttestation Hash: {att['attestation_hash'][:32]}...")

    # Save
    os.makedirs("reports/r4_qualification", exist_ok=True)
    ts = datetime.now(UTC).strftime("%Y%m%d_%H%M%S")
    path = f"reports/r4_qualification/attestation_{ts}.json"
    with open(path, "w") as f:
        json.dump(att, f, indent=2, default=str)
    print(f"\nSaved: {path}")

    print(f"\n{'=' * 70}")
    if att["ownership"]["all_r4_owned"] and att["fingerprint"]["all_verified"]:
        print("  ATTESTATION: VALID — system state is clean and attributed")
    else:
        print("  ATTESTATION: ISSUES DETECTED — review above")
    print(f"{'=' * 70}")


if __name__ == "__main__":
    main()
