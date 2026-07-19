#!/usr/bin/env python3
"""Clean forced signal_flip trades from NQ and ^DJI from all persisted state."""

import json
import sqlite3
from pathlib import Path

BASE = Path(__file__).resolve().parent.parent
LIVE = Path(BASE) / "data" / "live"

TARGET_ASSETS = {"NQ", "^DJI"}

# ── 1. Clean state.json ────────────────────────────────────────────────
state_path = Path(LIVE) / "state.json"
with open(state_path) as f:
    state = json.load(f)

for name in TARGET_ASSETS:
    area = state.get("assets", {}).get(name, {})
    metrics = area.get("metrics", {})
    if not metrics:
        continue

    # Remove signal_flip trade_log entries from metrics
    old_len = len(metrics.get("trade_log", []))
    metrics["trade_log"] = [t for t in metrics["trade_log"] if t.get("reason") != "signal_flip"]
    removed = old_len - len(metrics["trade_log"])

    # Reset exit_reasons
    metrics["exit_reasons"] = {
        "tp_rate": 0.0,
        "sl_rate": 0.0,
        "signal_flip_rate": 0.0,
        "avg_r": 0.0,
    }

    # Reset n_trades
    metrics["n_trades"] = len(metrics["trade_log"])

    # Reset trade-dependent metrics
    metrics["profit_factor"] = 0.0
    metrics["win_rate"] = 0.0

    print(f"{name} metrics: removed {removed} signal_flip trades, n_trades={metrics['n_trades']}")

# Also clean trade_log inside open_positions (restored on restart)
for name in TARGET_ASSETS:
    op = state.get("open_positions", {}).get(name)
    if op is None:
        continue
    old_tl = list(op.get("trade_log", []))
    op["trade_log"] = [t for t in old_tl if t.get("reason") != "signal_flip"]
    removed = len(old_tl) - len(op["trade_log"])
    if removed:
        print(f"{name} open_positions: removed {removed} signal_flip trades")

# Recalculate portfolio closed_trades
total_closed = sum(len(a.get("metrics", {}).get("trade_log", [])) for a in state.get("assets", {}).values())
state.setdefault("portfolio", {})["closed_trades"] = total_closed
print(f"portfolio closed_trades set to {total_closed}")

with open(state_path, "w") as f:
    json.dump(state, f, indent=2)
print("✅ state.json cleaned")

# ── 2. Clean state.db (trades table) ───────────────────────────────────
db_path = Path(LIVE) / "state.db"
conn = sqlite3.connect(db_path)
cursor = conn.cursor()

placeholders = ",".join("?" for _ in TARGET_ASSETS)
cursor.execute(
    f"DELETE FROM trades WHERE asset IN ({placeholders}) AND reason = 'signal_flip'",
    tuple(TARGET_ASSETS),
)
deleted = cursor.rowcount

# Reset auto-increment sequence if table is now empty
remaining = cursor.execute("SELECT COUNT(*) FROM trades").fetchone()[0]
if remaining == 0:
    cursor.execute("DELETE FROM sqlite_sequence WHERE name = 'trades'")

conn.commit()
conn.close()
print(f"✅ state.db: deleted {deleted} signal_flip trade rows, {remaining} remaining")

# ── 3. Clean trade_outcomes.json ───────────────────────────────────────
outcomes_path = Path(LIVE) / "trade_outcomes.json"
if Path(outcomes_path).exists():
    # Re-read the cleaned state to compute fresh outcomes
    with open(state_path) as f:
        state = json.load(f)

    by_asset = []
    overall_flips = 0
    overall_trades = 0
    for name, adata in state.get("assets", {}).items():
        m = adata.get("metrics", {})
        tl = m.get("trade_log", [])
        if not tl:
            continue
        reasons = [t.get("reason", "unknown") for t in tl]
        n = len(reasons)
        overall_trades += n
        overall_flips += reasons.count("signal_flip")
        profits = sum(t.get("pnl", 0) for t in tl if t.get("pnl", 0) > 0)
        losses = abs(sum(t.get("pnl", 0) for t in tl if t.get("pnl", 0) < 0))
        by_asset.append(
            {
                "asset": name,
                "n_trades": n,
                "tp_rate": round(reasons.count("tp") / n, 4),
                "sl_rate": round(reasons.count("sl") / n, 4),
                "signal_flip_rate": round(reasons.count("signal_flip") / n, 4),
                "avg_r": round(sum(t.get("realized_r", 0) for t in tl) / n, 4),
                "win_rate": round(len([t for t in tl if t.get("pnl", 0) > 0]) / n, 4),
                "profit_factor": profits / losses if losses > 0 else (float("inf") if profits > 0 else 0),
            }
        )

    outcomes = {
        "overall": {
            "tp_rate": 0.0
            if overall_trades == 0
            else round(sum(a["tp_rate"] * a["n_trades"] for a in by_asset) / overall_trades, 4),  # noqa: E501
            "sl_rate": 0.0
            if overall_trades == 0
            else round(sum(a["sl_rate"] * a["n_trades"] for a in by_asset) / overall_trades, 4),  # noqa: E501
            "signal_flip_rate": 0.0 if overall_trades == 0 else round(overall_flips / overall_trades, 4),
            "avg_r": 0.0
            if not by_asset
            else round(sum(a["avg_r"] * a["n_trades"] for a in by_asset) / overall_trades, 4),  # noqa: E501
            "win_rate": 0.0
            if not by_asset
            else round(sum(a["win_rate"] * a["n_trades"] for a in by_asset) / overall_trades, 4),  # noqa: E501
            "profit_factor": None if not by_asset else by_asset[0]["profit_factor"],
        },
        "by_asset": by_asset,
        "updated_at": json.load(open(outcomes_path)).get("updated_at", ""),  # noqa: SIM115
    }

    # Ensure overall rates are 0 if no trades at all
    if overall_trades == 0:
        outcomes["overall"] = {
            "tp_rate": 0.0,
            "sl_rate": 0.0,
            "signal_flip_rate": 0.0,
            "avg_r": 0.0,
            "win_rate": 0.0,
            "profit_factor": None,
        }
        outcomes["by_asset"] = []

    with open(outcomes_path, "w") as f:
        json.dump(outcomes, f, indent=2)
    print(f"✅ trade_outcomes.json cleaned ({overall_trades} total trades across all assets)")

print("Done.")
