#!/usr/bin/env python3
"""R4 Generate Fresh T=0 — immutable campaign boundary snapshot.

Captures the EXACT broker state, all fingerprints, risk policy,
and watchdog state as an immutable T=0 reference.

This becomes the single source of truth for the new campaign boundary.

Usage:
    python scripts/r4_generate_t0.py
    python scripts/r4_generate_t0.py --campaign-id R4-5K-20260827
"""
from __future__ import annotations

import hashlib
import json
import os
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict

sys.path.insert(0, "src")

import numpy as np

try:
    from mt5linux import MetaTrader5
except ImportError:
    MetaTrader5 = None

from eigencapital.config import load_config
from eigencapital.live.position_attribution import (
    classify_all,
    capacity_account,
    snapshot_hash,
    R4_MAGIC,
)
from eigencapital.production_qual.fingerprint_verifier import FingerprintVerifier
from eigencapital.live.watchdog import Watchdog, ProbeResult, WatchState


def generate_t0(campaign_id: str = "") -> Dict[str, Any]:
    """Capture the immutable T=0 snapshot."""
    now = datetime.now(timezone.utc)

    if not campaign_id:
        campaign_id = f"R4-5K-{now.strftime('%Y%m%d')}"

    # Connect to MT5
    mt5 = MetaTrader5(host="127.0.0.1", port=8001)
    if not mt5.initialize():
        raise ConnectionError(f"Cannot connect to MT5: {mt5.last_error()}")

    # Account state
    account = mt5.account_info()
    balance = float(account.balance)
    equity = float(account.equity)
    free_margin = float(getattr(account, "margin_free", 0) or getattr(account, "free_margin", 0) or 0)
    margin = float(getattr(account, "margin", 0) or 0)
    margin_level = float(getattr(account, "margin_level", 0) or 0)
    leverage = int(getattr(account, "leverage", 0) or 0)

    # Positions
    positions = list(mt5.positions_get() or [])
    classified = classify_all([
        {
            "ticket": p.ticket, "symbol": p.symbol, "type": p.type,
            "volume": p.volume, "magic": p.magic, "comment": p.comment,
            "profit": p.profit, "price_open": p.price_open,
            "sl": p.sl, "tp": p.tp,
        }
        for p in positions
    ])

    config = load_config("production")
    capacity = capacity_account(classified, config.capital.max_concurrent_positions)

    # Position details
    pos_details = []
    for p in positions:
        cls = [c for c in classified if c.ticket == p.ticket][0]
        pos_details.append({
            "ticket": p.ticket,
            "symbol": p.symbol,
            "direction": "LONG" if p.type == 0 else "SHORT",
            "volume": p.volume,
            "entry_price": p.price_open,
            "sl": p.sl,
            "tp": p.tp,
            "magic": p.magic,
            "comment": p.comment,
            "profit": p.profit,
            "classification": cls.pclass.value,
        })

    # Fingerprints
    verifier = FingerprintVerifier(config=config)
    fp_result = verifier.verify_all()

    # Compute config fingerprints
    manifest_fingerprint = verifier.frozen_manifest_fingerprint
    risk_fingerprint = verifier.frozen_risk_fingerprint
    live_risk_fingerprint = verifier.frozen_live_risk_fingerprint
    config_fingerprint = verifier._frozen_config_fp

    # Broker state hash
    broker_hash = snapshot_hash(
        [{"ticket": p.ticket, "symbol": p.symbol, "volume": p.volume,
          "type": p.type, "magic": p.magic} for p in positions],
        equity, free_margin,
    )

    # Watchdog initial state
    watchdog = Watchdog(
        stale_after_seconds=300,
        blind_after_seconds=900,
        contain_after_seconds=3600,
    )
    probe = ProbeResult(
        process_alive=True,
        trail_age_seconds=0.0,
        equity_read_ok=equity > 0,
        broker_reachable=True,
        evidence_hash=broker_hash,
    )
    wd_decision = watchdog.evaluate(probe)

    # R4 signal fingerprint (from config)
    from eigencapital.fidelity.r4_manifest import R4ConfigManifest
    manifest = R4ConfigManifest()
    r4_identity = manifest.compute_identity()

    # Build T=0
    t0 = {
        "campaign_id": campaign_id,
        "snapshot_timestamp": now.isoformat(),
        "account": {
            "id": int(account.login),
            "name": getattr(account, "name", ""),
            "server": getattr(account, "server", ""),
            "balance": balance,
            "equity": equity,
            "free_margin": free_margin,
            "margin": margin,
            "margin_level": margin_level,
            "leverage": leverage,
            "currency": "USD",
        },
        "positions": {
            "total": len(positions),
            "r4_count": capacity.r4_open_count,
            "foreign_count": len(capacity.foreign_positions),
            "max_concurrent": capacity.max_concurrent,
            "contamination": capacity.contaminated,
            "detail": pos_details,
        },
        "fingerprints": {
            "r4_identity": r4_identity,
            "manifest": manifest_fingerprint,
            "risk_policy": risk_fingerprint,
            "live_risk": live_risk_fingerprint,
            "config": config_fingerprint,
            "broker_state": broker_hash,
            "all_verified": fp_result.all_verified,
        },
        "risk_limits": {
            "max_drawdown_pct": config.live_risk.max_account_drawdown_pct,
            "daily_loss_limit": config.live_risk.max_daily_loss,
            "min_equity": config.live_risk.min_equity,
            "max_concurrent_positions": config.capital.max_concurrent_positions,
            "max_position_size": config.capital.max_position_size,
            "max_order_notional": config.capital.max_order_notional,
            "max_equity": config.capital.max_equity,
        },
        "watchdog": {
            "initial_state": wd_decision.state.value,
            "authorize_trading": wd_decision.authorize_trading,
            "stale_after_seconds": 300,
            "blind_after_seconds": 900,
            "contain_after_seconds": 3600,
        },
        "campaign_parameters": {
            "max_campaign_equity": config.capital.max_equity,
            "campaign_duration_days": config.capital.campaign_duration_days,
            "max_position_size": config.capital.max_position_size,
            "max_order_notional": config.capital.max_order_notional,
        },
    }

    # Compute immutable hash
    t0_hash = hashlib.sha256(
        json.dumps(t0, sort_keys=True, default=str).encode()
    ).hexdigest()
    t0["snapshot_hash"] = t0_hash

    mt5.shutdown()
    return t0


def main():
    args = sys.argv[1:]
    campaign_id = ""
    for i, a in enumerate(args):
        if a == "--campaign-id" and i + 1 < len(args):
            campaign_id = args[i + 1]

    print("=" * 70)
    print("  R4 FRESH T=0 SNAPSHOT GENERATOR")
    print("=" * 70)

    t0 = generate_t0(campaign_id)

    print(f"\nCampaign: {t0['campaign_id']}")
    print(f"Timestamp: {t0['snapshot_timestamp']}")
    print(f"Account: {t0['account']['id']} | Balance: ${t0['account']['balance']:,.2f} | Equity: ${t0['account']['equity']:,.2f}")
    print(f"Positions: {t0['positions']['total']} ({t0['positions']['r4_count']} R4, {t0['positions']['foreign_count']} foreign)")
    print(f"Fingerprints: {'✅ all verified' if t0['fingerprints']['all_verified'] else '❌ MISMATCH'}")
    print(f"Watchdog: {t0['watchdog']['initial_state']}")
    print(f"Contamination: {'⚠️ YES' if t0['positions']['contamination'] else '✅ NO'}")
    print(f"Snapshot Hash: {t0['snapshot_hash'][:32]}...")

    # List positions
    print("\nPositions at T=0:")
    for p in t0["positions"]["detail"]:
        icon = "🟢" if p["classification"] == "R4_BOT" else "🔴"
        sl_str = f"{p['sl']:.5f}" if p['sl'] > 0 else "NONE"
        print(f"  {icon} #{p['ticket']} {p['symbol']} {p['direction']} {p['volume']:.2f} @ {p['entry_price']:.5f} SL={sl_str} [{p['classification']}]")

    # Save
    os.makedirs("reports/r4_qualification", exist_ok=True)
    path = f"reports/r4_qualification/T0_{t0['campaign_id']}_{t0['snapshot_hash'][:12]}.json"
    with open(path, "w") as f:
        json.dump(t0, f, indent=2, default=str)
    print(f"\nSaved: {path}")

    print(f"\n{'=' * 70}")
    print(f"  T=0 CAPTURED — immutable campaign boundary established")
    print(f"{'=' * 70}")


if __name__ == "__main__":
    main()
