"""R4 Live Monitor — watches audit trail and broker state for alerts.

Monitors:
  - Position changes (new entries, exits, modifications)
  - Risk gate triggers (BLOCK, CRITICAL)
  - Regime changes (ON ↔ OFF)
  - Equity/drawdown changes
  - Process health (loop alive/dead)

Alert channels:
  - Telegram (instant, mobile)
  - Local file (always works)
  - stdout (for debugging)

Usage:
    python scripts/r4_monitor.py                    # one-shot check
    python scripts/r4_monitor.py --loop             # continuous monitoring
    python scripts/r4_monitor.py --loop --interval 60  # every 60s
    python scripts/r4_monitor.py --telegram         # send Telegram alerts
    python scripts/r4_monitor.py --status           # show current status

Setup Telegram:
    1. Create bot via @BotFather → get BOT_TOKEN
    2. Send message to bot → get CHAT_ID from updates
    3. Set env vars: R4_TELEGRAM_BOT_TOKEN, R4_TELEGRAM_CHAT_ID
"""

from __future__ import annotations

import json
import os
import signal
import sys
import time
import urllib.request
import urllib.parse
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from mt5linux import MetaTrader5

# ── Configuration ──────────────────────────────────────────────────

AUDIT_DIR = Path("reports/r4_loop")
AUDIT_FILE = AUDIT_DIR / "decisions.jsonl"
MONITOR_LOG = AUDIT_DIR / "monitor.jsonl"
POSITIONS_FILE = AUDIT_DIR / "last_positions.json"

TELEGRAM_BOT_TOKEN = os.environ.get("R4_TELEGRAM_BOT_TOKEN", "")
TELEGRAM_CHAT_ID = os.environ.get("R4_TELEGRAM_CHAT_ID", "")

# ── Globals ────────────────────────────────────────────────────────

_shutdown = False


def _handle_signal(sig, frame):
    global _shutdown
    _shutdown = True


signal.signal(signal.SIGINT, _handle_signal)
signal.signal(signal.SIGTERM, _handle_signal)


# ── Helpers ────────────────────────────────────────────────────────

def log(msg: str) -> None:
    ts = datetime.now(timezone.utc).strftime("%H:%M:%S")
    print(f"  [{ts}] {msg}", flush=True)


def monitor_record(record: Dict[str, Any]) -> None:
    AUDIT_DIR.mkdir(parents=True, exist_ok=True)
    record["timestamp"] = datetime.now(timezone.utc).isoformat()
    with open(MONITOR_LOG, "a") as f:
        f.write(json.dumps(record, default=str) + "\n")


def send_telegram(text: str) -> bool:
    """Send message via Telegram bot. Returns True on success."""
    if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
        return False

    try:
        url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
        data = json.dumps({
            "chat_id": TELEGRAM_CHAT_ID,
            "text": text,
            "parse_mode": "HTML",
        }).encode()
        req = urllib.request.Request(url, data=data, headers={"Content-Type": "application/json"})
        resp = urllib.request.urlopen(req, timeout=10)
        return resp.status == 200
    except Exception as e:
        log(f"⚠️  Telegram failed: {e}")
        return False


def alert(title: str, body: str, level: str = "INFO") -> None:
    """Send alert to all channels."""
    icon = {"INFO": "ℹ️", "WARN": "⚠️", "CRITICAL": "🔴", "TRADE": "📊"}.get(level, "📢")
    full_msg = f"{icon} **{title}**\n{body}"

    # Always log locally
    monitor_record({"level": level, "title": title, "body": body})

    # stdout
    log(f"{icon} {title}: {body}")

    # Telegram
    if TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID:
        send_telegram(full_msg)


# ── State Tracking ─────────────────────────────────────────────────

def load_last_positions() -> Dict[str, Dict[str, Any]]:
    """Load last known positions from disk."""
    if POSITIONS_FILE.exists():
        with open(POSITIONS_FILE) as f:
            return json.load(f)
    return {}


def save_positions(positions: Dict[str, Dict[str, Any]]) -> None:
    """Save current positions to disk."""
    POSITIONS_FILE.parent.mkdir(parents=True, exist_ok=True)
    with open(POSITIONS_FILE, "w") as f:
        json.dump(positions, f, indent=2, default=str)


def get_broker_positions(mt5) -> Dict[str, Dict[str, Any]]:
    """Get current broker positions as dict keyed by symbol."""
    positions = mt5.positions_get()
    pos_list = list(positions) if positions else []
    result = {}
    for p in pos_list:
        key = f"{p.symbol}_{p.type}_{p.ticket}"  # unique key
        result[key] = {
            "symbol": p.symbol,
            "volume": p.volume,
            "type": p.type,
            "direction": "LONG" if p.type == 0 else "SHORT",
            "price_open": p.price_open,
            "sl": p.sl,
            "tp": p.tp,
            "profit": p.profit,
            "ticket": p.ticket,
            "magic": p.magic,
            "comment": p.comment,
        }
    return result


def diff_positions(
    old: Dict[str, Dict], new: Dict[str, Dict]
) -> Tuple[List[str], List[str], List[str]]:
    """Compare old and new positions. Returns (added, removed, modified)."""
    added = []
    removed = []
    modified = []

    old_keys = set(old.keys())
    new_keys = set(new.keys())

    for key in new_keys - old_keys:
        p = new[key]
        added.append(f"{p['direction']} {p['volume']:.2f} {p['symbol']}")

    for key in old_keys - new_keys:
        p = old[key]
        removed.append(f"{p['direction']} {p['volume']:.2f} {p['symbol']}")

    for key in old_keys & new_keys:
        old_p = old[key]
        new_p = new[key]
        # Only alert on structural changes, not P&L noise
        if (old_p["volume"] != new_p["volume"] or
            old_p["sl"] != new_p["sl"] or
            old_p["tp"] != new_p["tp"]):
            modified.append(f"{new_p['symbol']} vol={new_p['volume']:.2f} sl={new_p['sl']} tp={new_p['tp']}")

    return added, removed, modified


# ── Monitoring Checks ──────────────────────────────────────────────

def check_positions(mt5) -> None:
    """Check for position changes and alert."""
    current = get_broker_positions(mt5)
    last = load_last_positions()

    added, removed, modified = diff_positions(last, current)

    if added:
        alert("POSITION OPENED", "\n".join(f"  → {a}" for a in added), "TRADE")

    if removed:
        alert("POSITION CLOSED", "\n".join(f"  ✕ {r}" for r in removed), "TRADE")

    if modified:
        alert("POSITION MODIFIED", "\n".join(f"  ~ {m}" for m in modified), "INFO")

    save_positions(current)


def check_risk_gates() -> None:
    """Check latest audit trail entries for risk gate triggers."""
    if not AUDIT_FILE.exists():
        return

    # Read last 10 lines
    lines = AUDIT_FILE.read_text().strip().split("\n")
    if not lines:
        return

    for line in lines[-5:]:
        try:
            entry = json.loads(line)
        except json.JSONDecodeError:
            continue

        event = entry.get("event", "")

        if event == "risk_critical":
            gates = entry.get("gates", [])
            critical = [g for g in gates if g.get("result") == "CRITICAL"]
            for g in critical:
                alert(
                    "RISK CRITICAL",
                    f"Gate: {g.get('gate', '?')}\nReason: {g.get('message', '?')}",
                    "CRITICAL",
                )

        elif event == "risk_blocked":
            gates = entry.get("gates", [])
            blocked = [g for g in gates if g.get("result") == "BLOCK"]
            for g in blocked:
                alert(
                    "RISK BLOCKED",
                    f"Gate: {g.get('gate', '?')}\nReason: {g.get('message', '?')}",
                    "WARN",
                )

        elif event == "concurrency_limit":
            alert(
                "CONCURRENCY LIMIT",
                f"Positions: {entry.get('positions', '?')}/{entry.get('limit', '?')}",
                "WARN",
            )

        elif event == "emergency_flatten":
            alert(
                "EMERGENCY FLATTEN",
                f"Closed: {entry.get('closed', 0)}, Failed: {entry.get('failed', 0)}",
                "CRITICAL",
            )

        elif event == "error":
            alert(
                "CYCLE ERROR",
                f"Error: {entry.get('error', '?')}",
                "CRITICAL",
            )


def check_equity(mt5) -> None:
    """Check equity for significant changes."""
    account = mt5.account_info()
    if not account:
        return

    equity = account.equity

    # Load last equity
    last_equity_file = AUDIT_DIR / "last_equity.json"
    last_equity = 5_010.94  # T=0 default

    if last_equity_file.exists():
        with open(last_equity_file) as f:
            data = json.load(f)
            last_equity = data.get("equity", 5_010.94)

    # Alert if equity changed by more than $10
    if abs(equity - last_equity) > 10:
        change = equity - last_equity
        alert(
            "EQUITY CHANGE",
            f"${last_equity:,.2f} → ${equity:,.2f} ({change:+,.2f})",
            "INFO",
        )

    # Save current equity
    with open(last_equity_file, "w") as f:
        json.dump({"equity": equity, "timestamp": datetime.now(timezone.utc).isoformat()}, f)


def check_regime() -> None:
    """Check if regime changed since last check."""
    import numpy as np
    import pandas as pd

    # Load last regime state
    regime_file = AUDIT_DIR / "last_regime.json"
    last_regime = None

    if regime_file.exists():
        with open(regime_file) as f:
            data = json.load(f)
            last_regime = data.get("regime_on")

    # Quick regime check
    mt5 = MetaTrader5(host="127.0.0.1", port=8001)
    if not mt5.initialize():
        return

    try:
        SYMBOLS = ["EURUSD", "GBPUSD", "AUDUSD", "USDCAD", "USDCHF", "BTCUSD"]
        data = {}
        for sym in SYMBOLS:
            mt5.symbol_select(sym, True)
            rates = mt5.copy_rates_from_pos(sym, mt5.TIMEFRAME_D1, 0, 60)
            if rates is not None and len(rates) > 0:
                df = pd.DataFrame(rates)
                df["time"] = pd.to_datetime(df["time"], unit="s")
                df = df.set_index("time")
                data[sym] = df["close"]

        if len(data) < 3:
            return

        returns_df = pd.DataFrame({sym: df.pct_change() for sym, df in data.items()}).dropna(how="all").ffill().fillna(0)
        avg_vol = returns_df.rolling(20).std().mean(axis=1) * np.sqrt(252)
        risk_median = avg_vol.expanding().median()
        regime_on = bool(avg_vol.iloc[-1] < risk_median.iloc[-1])

        # Alert on regime change
        if last_regime is not None and regime_on != last_regime:
            state = "ON → OFF" if last_regime else "OFF → ON"
            alert(
                "REGIME CHANGE",
                f"Regime {state}\nVol: {avg_vol.iloc[-1]:.1%} vs median {risk_median.iloc[-1]:.1%}",
                "WARN" if not regime_on else "INFO",
            )

        # Save current regime
        with open(regime_file, "w") as f:
            json.dump({
                "regime_on": regime_on,
                "vol": float(avg_vol.iloc[-1]),
                "median": float(risk_median.iloc[-1]),
                "timestamp": datetime.now(timezone.utc).isoformat(),
            }, f)

    finally:
        mt5.shutdown()


def check_loop_health() -> None:
    """Check if the rebalance loop process is alive."""
    import subprocess
    try:
        result = subprocess.run(
            ["pgrep", "-f", "r4_rebalance_loop"],
            capture_output=True, text=True, timeout=5
        )
        alive = result.returncode == 0
    except Exception:
        alive = False

    # Load last state
    health_file = AUDIT_DIR / "last_health.json"
    last_alive = True

    if health_file.exists():
        with open(health_file) as f:
            data = json.load(f)
            last_alive = data.get("alive", True)

    # Alert on state change
    if not alive and last_alive:
        alert("LOOP DIED", "r4_rebalance_loop process is not running!", "CRITICAL")
    elif alive and not last_alive:
        alert("LOOP RECOVERED", "r4_rebalance_loop process is running again", "INFO")

    with open(health_file, "w") as f:
        json.dump({
            "alive": alive,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }, f)


# ── Status Display ─────────────────────────────────────────────────

def show_status(mt5) -> None:
    """Show current monitoring status."""
    account = mt5.account_info()
    positions = mt5.positions_get()
    pos_list = list(positions) if positions else []

    print("=" * 50)
    print("  R4 MONITOR STATUS")
    print("=" * 50)
    print()
    print("ACCOUNT:")
    print(f"  Equity:    ${account.equity:,.2f}")
    print(f"  Positions: {len(pos_list)}")
    print()

    if pos_list:
        print("POSITIONS:")
        for p in pos_list:
            d = "LONG" if p.type == 0 else "SHORT"
            print(f"  {d:5s} {p.symbol:8s} {p.volume:.2f} lots @ {p.price_open:.5f} pnl={p.profit:+.2f}")
        print()

    # Regime
    regime_file = AUDIT_DIR / "last_regime.json"
    if regime_file.exists():
        with open(regime_file) as f:
            data = json.load(f)
        regime = "ON ✅" if data.get("regime_on") else "OFF ⛔"
        print(f"REGIME: {regime} (vol {data.get('vol', 0):.1%} vs median {data.get('median', 0):.1%})")
    else:
        print("REGIME: unknown (no check yet)")
    print()

    # Loop health
    import subprocess
    try:
        result = subprocess.run(
            ["pgrep", "-f", "r4_rebalance_loop"],
            capture_output=True, text=True, timeout=5
        )
        alive = result.returncode == 0
    except Exception:
        alive = False

    print(f"LOOP: {'RUNNING ✅' if alive else 'DEAD ⛔'}")
    print()

    # Recent alerts
    if MONITOR_LOG.exists():
        lines = MONITOR_LOG.read_text().strip().split("\n")
        recent = lines[-5:] if lines else []
        if recent:
            print("RECENT ALERTS:")
            for line in recent:
                try:
                    entry = json.loads(line)
                    ts = entry.get("timestamp", "?")[:19]
                    level = entry.get("level", "?")
                    title = entry.get("title", "?")
                    print(f"  {ts} [{level}] {title}")
                except json.JSONDecodeError:
                    pass
            print()

    print("=" * 50)


# ── Main Loop ──────────────────────────────────────────────────────

def run_check(mt5) -> None:
    """Run all monitoring checks."""
    check_positions(mt5)
    check_risk_gates()
    check_equity(mt5)
    check_regime()
    check_loop_health()


def main() -> None:
    args = sys.argv[1:]
    loop_mode = "--loop" in args
    show_status_mode = "--status" in args

    interval = 300  # default 5 minutes
    for i, a in enumerate(args):
        if a == "--interval" and i + 1 < len(args):
            interval = int(args[i + 1])

    # Telegram setup check
    if "--telegram" in args:
        if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
            print("⚠️  Telegram not configured. Set R4_TELEGRAM_BOT_TOKEN and R4_TELEGRAM_CHAT_ID")
            print("   1. Create bot via @BotFather → get BOT_TOKEN")
            print("   2. Send message to bot → get CHAT_ID from /getUpdates")
            print("   3. export R4_TELEGRAM_BOT_TOKEN=...")
            print("   4. export R4_TELEGRAM_CHAT_ID=...")
            return
        log("Telegram alerts enabled")

    mt5 = MetaTrader5(host="127.0.0.1", port=8001)
    if not mt5.initialize():
        print(f"❌ Cannot connect: {mt5.last_error()}")
        return

    if show_status_mode:
        show_status(mt5)
        mt5.shutdown()
        return

    print("=" * 50, flush=True)
    print("  R4 MONITOR", flush=True)
    print(f"  Mode: {'LOOP' if loop_mode else 'ONE-SHOT'} | Interval: {interval}s", flush=True)
    print(f"  Telegram: {'enabled' if TELEGRAM_BOT_TOKEN else 'disabled'}", flush=True)
    print("=" * 50, flush=True)

    # Initial check
    run_check(mt5)

    if not loop_mode:
        mt5.shutdown()
        return

    while not _shutdown:
        time.sleep(interval)
        if _shutdown:
            break
        try:
            # Reconnect each cycle (MT5 connection may stale)
            mt5.shutdown()
            if not mt5.initialize():
                alert("MT5 DISCONNECTED", "Cannot reconnect to MT5", "CRITICAL")
                time.sleep(30)
                continue
            run_check(mt5)
        except Exception as e:
            alert("MONITOR ERROR", str(e), "CRITICAL")

    mt5.shutdown()
    log("Monitor stopped.")


if __name__ == "__main__":
    main()
