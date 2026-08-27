"""R4 Dashboard — Real-time metrics display for the trading system.

Displays:
- Account equity, drawdown, daily P&L
- Position count and exposure
- Risk observation levels
- Recent alerts
- System health status

Usage:
    python scripts/r4_dashboard.py                    # one-shot
    python scripts/r4_dashboard.py --loop --interval 30  # refresh every 30s
    python scripts/r4_dashboard.py --json              # JSON output
"""

from __future__ import annotations

import json
import os
import sys
import time
from datetime import UTC, datetime

sys.path.insert(0, "src")

try:
    from mt5linux import MetaTrader5
except ImportError:
    MetaTrader5 = None

from eigencapital.config import load_config
from eigencapital.live.risk_observation import RiskObserver


def clear_screen():
    """Clear terminal screen."""
    os.system("cls" if os.name == "nt" else "clear")


def get_mt5_data():
    """Fetch current MT5 data."""
    if MetaTrader5 is None:
        return None

    try:
        mt5 = MetaTrader5(host="127.0.0.1", port=8001)
        if not mt5.initialize():
            return None

        account = mt5.account_info()
        positions = mt5.positions_get()
        pos_list = list(positions) if positions else []

        mt5.shutdown()

        return {
            "equity": account.equity if account else 0,
            "balance": account.balance if account else 0,
            "free_margin": getattr(account, "margin_free", 0) or 0,
            "positions": [
                {
                    "ticket": p.ticket,
                    "symbol": p.symbol,
                    "type": p.type,
                    "volume": p.volume,
                    "price_open": p.price_open,
                    "profit": p.profit,
                    "sl": p.sl,
                    "magic": p.magic,
                }
                for p in pos_list
            ],
            "position_count": len(pos_list),
        }
    except Exception:
        return None


def get_recent_alerts(n: int = 5):
    """Get recent alerts from the alert log."""
    alert_path = "reports/alerts.jsonl"
    if not os.path.exists(alert_path):
        return []

    alerts = []
    try:
        with open(alert_path) as f:
            for line in f:
                line = line.strip()
                if line:
                    try:
                        alerts.append(json.loads(line))
                    except json.JSONDecodeError:
                        pass
    except OSError:
        pass

    return alerts[-n:]


def render_dashboard(data: dict | None, observer: RiskObserver):
    """Render the dashboard to stdout."""
    now = datetime.now(UTC).strftime("%Y-%m-%d %H:%M:%S UTC")

    if data is None:
        print(f"\n  [{now}] ❌ Cannot connect to MT5 — bridge may be down\n")
        return

    # Run risk observations
    risk_state = observer.observe(
        equity=data["equity"],
        balance=data["balance"],
        free_margin=data["free_margin"],
        positions=data["positions"],
        daily_pnl=0.0,  # Would need daily start equity
    )

    # Streaming metrics
    metrics = observer.get_streaming_metrics()

    # Recent alerts
    alerts = get_recent_alerts(5)

    # Render
    print("\033[2J\033[H")  # Clear screen
    print("=" * 60)
    print("  EIGENCAPITAL R4 DASHBOARD")
    print("=" * 60)
    print(f"  {now}")
    print()

    # Account
    print("  ACCOUNT")
    print(f"    Equity:      ${data['equity']:>10,.2f}")
    print(f"    Balance:     ${data['balance']:>10,.2f}")
    print(f"    Free Margin: ${data['free_margin']:>10,.2f}")
    print()

    # Risk State
    level_icon = {
        "NORMAL": "🟢",
        "WARNING": "🟡",
        "CRITICAL": "🔴",
        "ELEVATED": "🟠",
        "HALT": "⛔",
    }
    icon = level_icon.get(risk_state.overall_level, "❓")
    print(f"  RISK STATE: {icon} {risk_state.overall_level}")
    if risk_state.critical_dimensions:
        print(f"    Critical: {', '.join(risk_state.critical_dimensions)}")
    if risk_state.warning_dimensions:
        print(f"    Warning:  {', '.join(risk_state.warning_dimensions)}")
    print()

    # Key Metrics
    print("  KEY METRICS")
    dd = metrics.get("drawdown", 0) * 100
    dd_limit = metrics.get("drawdown_limit", 0.1) * 100
    print(f"    Drawdown:        {dd:>6.2f}% / {dd_limit:.0f}%")
    dl = metrics.get("daily_loss", 0)
    dl_limit = metrics.get("daily_loss_limit", 250)
    print(f"    Daily Loss:      ${dl:>8.2f} / ${dl_limit:.0f}")
    print(f"    Positions:       {metrics.get('position_count', 0):>3d} / {metrics.get('position_limit', 19)}")
    print(f"    Gross Exposure:  {metrics.get('gross_exposure', 0) * 100:>6.1f}%")
    print(f"    Margin Used:     {metrics.get('margin_utilization', 0) * 100:>6.1f}%")
    print(f"    Concentration:   {metrics.get('concentration', 0) * 100:>6.1f}%")
    print(f"    Unprotected SL:  {metrics.get('sl_unprotected', 0):>3d}")
    print()

    # Positions
    print(f"  POSITIONS ({data['position_count']})")
    for pos in data["positions"][:10]:
        side = "BUY " if pos["type"] == 0 else "SELL"
        sl_mark = "✅" if pos["sl"] > 0 else "❌"
        print(f"    {pos['symbol']:10s} {side} {pos['volume']:5.2f} @ {pos['price_open']:.5f}  P&L: {pos['profit']:>8.2f}  SL:{sl_mark}")
    if data["position_count"] > 10:
        print(f"    ... and {data['position_count'] - 10} more")
    print()

    # Recent Alerts
    print("  RECENT ALERTS")
    if alerts:
        for alert in alerts[-5:]:
            ts = alert.get("timestamp", "?")[:19]
            sev = alert.get("severity", "?")
            cat = alert.get("category", "?")
            msg = alert.get("message", "?")[:50]
            print(f"    [{ts}] {sev:8s} {cat:14s} {msg}")
    else:
        print("    No recent alerts")
    print()

    print("=" * 60)


def render_json(data: dict | None, observer: RiskObserver):
    """Render dashboard as JSON."""
    if data is None:
        print(json.dumps({"status": "error", "message": "Cannot connect to MT5"}))
        return

    risk_state = observer.observe(
        equity=data["equity"],
        balance=data["balance"],
        free_margin=data["free_margin"],
        positions=data["positions"],
        daily_pnl=0.0,
    )

    metrics = observer.get_streaming_metrics()
    alerts = get_recent_alerts(10)

    output = {
        "timestamp": datetime.now(UTC).isoformat(),
        "account": {
            "equity": data["equity"],
            "balance": data["balance"],
            "free_margin": data["free_margin"],
        },
        "risk": risk_state.to_dict(),
        "metrics": metrics,
        "position_count": data["position_count"],
        "recent_alerts": alerts,
    }

    print(json.dumps(output, indent=2, default=str))


def main():
    args = sys.argv[1:]
    loop_mode = "--loop" in args
    json_mode = "--json" in args

    interval = 30
    for i, a in enumerate(args):
        if a == "--interval" and i + 1 < len(args):
            interval = int(args[i + 1])

    _config = load_config(os.environ.get("EIGENCAPITAL_ENV", "production"))
    _lr = _config.live_risk

    observer = RiskObserver(
        max_daily_loss=_lr.max_daily_loss,
        max_drawdown_pct=_lr.max_account_drawdown_pct,
        min_equity=_lr.min_equity,
    )

    if loop_mode:
        while True:
            data = get_mt5_data()
            if json_mode:
                render_json(data, observer)
            else:
                render_dashboard(data, observer)
            time.sleep(interval)
    else:
        data = get_mt5_data()
        if json_mode:
            render_json(data, observer)
        else:
            render_dashboard(data, observer)


if __name__ == "__main__":
    main()
