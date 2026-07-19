#!/usr/bin/env python3
"""Poll paper trading dashboard every N hours and log to CSV.

Usage:
    # One-shot
    PYTHONPATH=$PYTHONPATH:. python scripts/monitor_paper_trading.py

    # Loop (every 6 hours)
    nohup python scripts/monitor_paper_trading.py --loop --interval 6 &
"""

import argparse
import csv
import json
import time
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

DASHBOARD_URL = "http://127.0.0.1:5000/state.json"
LOG_DIR = Path(Path(__file__).resolve().parent.parent, "data", "monitoring")
Path(LOG_DIR).mkdir(parents=True, exist_ok=True)
LOG_PATH = Path(LOG_DIR) / "paper_trade_monitor.csv"

# Assets under confidence calibration watch.
# Both show 92-96% confidence every cycle with insufficient trade history to
# assess whether this reflects genuine skill or miscalibration.
_CALIBRATION_WATCH_ASSETS = frozenset({"NZDCAD", "NZDUSD"})
_N_TRADES_MIN = 20  # minimum closed trades before calibration review triggers


def poll() -> dict:
    try:
        with urllib.request.urlopen(DASHBOARD_URL, timeout=10) as resp:
            return json.loads(resp.read())
    except Exception as e:  # noqa: BLE001
        return {"error": str(e)}


def append_row(row: dict):
    fieldnames = list(row.keys())
    exists = Path(LOG_PATH).exists()
    with open(LOG_PATH, "a", newline="") as f:
        w = csv.DictWriter(f, fieldnames=fieldnames)
        if not exists:
            w.writeheader()
        w.writerow(row)


def check_calibration(state: dict) -> list[str]:
    """Check NZDCAD/NZDUSD for sufficient trade history to evaluate calibration.

    Returns a list of human-readable alert/review messages (empty if none).
    """
    assets = state.get("assets", {})
    messages: list[str] = []
    for name in _CALIBRATION_WATCH_ASSETS:
        adata = assets.get(name, {})
        metrics = adata.get("metrics", {})
        n_trades = metrics.get("n_trades", 0)
        if n_trades >= _N_TRADES_MIN:
            mean_conf = metrics.get("mean_confidence", 0)
            win_rate = metrics.get("win_rate", 0)
            gap = mean_conf - win_rate
            if gap >= 15:
                messages.append(
                    f"CALIBRATION ALERT: {name} — overconfident "
                    f"(conf={mean_conf:.0f}% vs wr={win_rate:.0f}%, gap={gap:.0f}pp, N={n_trades})"
                )
            elif gap >= 10:
                messages.append(
                    f"CALIBRATION WATCH: {name} — borderline "
                    f"(conf={mean_conf:.0f}% vs wr={win_rate:.0f}%, gap={gap:.0f}pp, N={n_trades})"
                )
            else:
                messages.append(
                    f"CALIBRATION OK: {name} — confidence tracks win rate "
                    f"(conf={mean_conf:.0f}% vs wr={win_rate:.0f}%, gap={gap:.0f}pp, N={n_trades})"
                )
    return messages


def compute_metrics(state: dict) -> dict:
    now = datetime.now(timezone.utc).isoformat()
    portfolio = state.get("portfolio", {})
    assets = state.get("assets", {})

    # Signal distribution
    signals = {}
    confidences = []
    gate_overrides = 0
    flips = 0
    for name, s in assets.items():
        sig = s.get("last_signal", {})
        decision = sig.get("signal", "?")
        signals[decision] = signals.get(decision, 0) + 1
        conf = sig.get("confidence", 0)
        if isinstance(conf, (int, float)):
            confidences.append(conf)
        if s.get("gate_override", False):
            gate_overrides += 1
        if s.get("signal_flip", False):
            flips += 1

    n_assets = len(assets)
    mean_conf = sum(confidences) / max(len(confidences), 1)

    return {
        "timestamp": now,
        "n_assets": n_assets,
        "total_value": portfolio.get("total_value", 0),
        "unrealized_pnl": portfolio.get("unrealized_pnl", 0),
        "total_return": portfolio.get("total_return", 0),
        "open_positions": portfolio.get("open_positions", 0),
        "closed_trades": portfolio.get("closed_trades", 0),
        "portfolio_drawdown": portfolio.get("portfolio_drawdown", 0),
        "mean_confidence": round(mean_conf, 4),
        "gate_overrides": gate_overrides,
        "signal_flips": flips,
        "n_buy": signals.get("BUY", 0),
        "n_sell": signals.get("SELL", 0),
        "n_flat": signals.get("FLAT", 0),
        "n_hold": signals.get("HOLD", 0),
        "n_unknown": signals.get("?", 0),
        "errors": state.get("error", ""),
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--loop", action="store_true", help="Run in loop")
    parser.add_argument("--interval", type=int, default=6, help="Polling interval in hours")
    args = parser.parse_args()

    if args.loop:
        print(f"Monitoring every {args.interval}h. Log -> {LOG_PATH}")
        while True:
            state = poll()
            if "error" in state:
                print(f"[{datetime.now().isoformat()}] Error: {state['error']}")
            else:
                metrics = compute_metrics(state)
                append_row(metrics)
                print(
                    f"[{metrics['timestamp']}] value={metrics['total_value']:.0f} "
                    f"unrealized={metrics['unrealized_pnl']:.0f} "
                    f"conf={metrics['mean_confidence']:.3f} "
                    f"gate={metrics['gate_overrides']} flips={metrics['signal_flips']} "
                    f"B/S/F={metrics['n_buy']}/{metrics['n_sell']}/{metrics['n_flat']}"
                )
                for msg in check_calibration(state):
                    print(f"  {msg}")
            time.sleep(args.interval * 3600)
    else:
        state = poll()
        if "error" in state:
            print(f"Error: {state['error']}")
        else:
            metrics = compute_metrics(state)
            append_row(metrics)
            print(json.dumps(metrics, indent=2))
            for msg in check_calibration(state):
                print(f"  {msg}")
            print(f"\nLog -> {LOG_PATH}")


if __name__ == "__main__":
    main()
