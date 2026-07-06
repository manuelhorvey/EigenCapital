import json
import os
import sys
from datetime import datetime

import pandas as pd

from eigencapital.domain.encoding import EigenCapitalJSONEncoder

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(__file__))))

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
STATE_PATH = os.path.join(BASE, "data", "live", "state.json")
HISTORY_PATH = os.path.join(BASE, "data", "live", "history.parquet")
REPORT_PATH = os.path.join(BASE, "data", "live", "dashboard.json")


def load_state():
    if os.path.exists(STATE_PATH):
        with open(STATE_PATH) as f:
            return json.load(f)
    return None


def load_history():
    if os.path.exists(HISTORY_PATH):
        return pd.read_parquet(HISTORY_PATH)
    return pd.DataFrame()


def save_history(hist):
    hist.to_parquet(HISTORY_PATH)


def compute_pnl_correlation(hist):
    if len(hist) < 10:
        return None
    cols = [c for c in ["XLF", "BTC", "NZDJPY"] if c in hist.columns]
    if len(cols) < 2:
        return None
    return hist[cols].corr()


def check_halts(state, hist):
    flags = []
    assets = state.get("assets", {})
    portfolio = state.get("portfolio", {})
    halt_config = state.get("halt_conditions", {})

    # Use halt conditions directly from engine state
    for name, asset_data in assets.items():
        halt = asset_data.get("halt", {})
        if halt.get("halted"):
            for reason in halt.get("reasons", []):
                flags.append({"asset": name, "type": "engine_halt", "reason": reason})

    # Portfolio-level execution state
    exec_state = portfolio.get("execution_state", "ACTIVE")
    if exec_state == "HALTED":
        flags.append({"asset": "PORTFOLIO", "type": "execution_state", "state": exec_state})

    # Signal drought (dashboard uses different threshold as early warning)
    drought_warning = halt_config.get("signal_drought", 30)
    early_warn = max(1, drought_warning - 7)
    for name in ["BTC", "NZDJPY", "CADJPY", "USDCAD", "GC", "EURAUD"]:
        asset = assets.get(name, {})
        metrics = asset.get("metrics", {})
        last_signal = metrics.get("last_signal_date")
        if last_signal:
            try:
                days_since = (datetime.now() - datetime.strptime(last_signal, "%Y-%m-%d")).days
                if days_since > early_warn:
                    flags.append(
                        {"asset": name, "type": "drought_warning", "current": days_since, "warning_at": early_warn}
                    )
            except ValueError:
                pass

    return flags


def print_daily(state, hist):
    print("\n" + "=" * 65)
    print(f"PAPER PORTFOLIO DASHBOARD — {datetime.now().strftime('%Y-%m-%d %H:%M')}")
    print("=" * 65)

    portfolio = state.get("portfolio", {})
    tv = portfolio.get("total_value", 0)
    tr = portfolio.get("total_return", 0)
    days = portfolio.get("days_running", 0)
    print(f"\nPortfolio: ${tv:,.2f}  Return: {tr:+.2f}%  Days: {days}")
    print(
        f"{'Asset':>8s}  {'Signal':>7s}  {'Conf':>5s}  {'Value':>10s}  {'Ret':>7s}  "
        f"{'DD':>6s}  {'PF':>5s}  {'WinR':>5s}  {'Trades':>6s}"
    )
    print("-" * 75)

    for name in ["XLF", "BTC", "NZDJPY"]:
        asset = state.get("assets", {}).get(name, {})
        metrics = asset.get("metrics", {})
        last = asset.get("last_signal", {})

        val = metrics.get("current_value", 0)
        ret = metrics.get("total_return", 0)
        dd = metrics.get("drawdown", 0)
        pf = metrics.get("profit_factor", 0)
        wr = metrics.get("win_rate", 0)
        nt = metrics.get("n_trades", 0)
        sig = last.get("signal", "-")
        conf = last.get("confidence", 0)

        sig_display = f"{sig:>4s}" if sig != "-" else " FLAT"
        pf_str = f"{pf:.2f}" if pf is not None else " N/A"
        wr_str = f"{wr:.1f}%" if wr is not None else " N/A"
        print(
            f"{name:>8s}  {sig_display:>7s}  {conf:>4.0f}%  ${val:>8,.2f}  "
            f"{ret:>+6.2f}%  {dd:>5.1f}%  {pf_str:>5s}  {wr_str:>5s}  {nt:>6d}"
        )

    # Halt check
    flags = check_halts(state, hist)
    if not flags:
        print("\n  ✅ All halt conditions clear")
    else:
        print(f"\n  ⚠ {len(flags)} halt condition(s) active")


def update_history(state):
    hist = load_history()
    today = datetime.now().strftime("%Y-%m-%d")
    row = {"date": today}
    for name in ["XLF", "BTC", "NZDJPY"]:
        asset = state.get("assets", {}).get(name, {})
        metrics = asset.get("metrics", {})
        row[f"{name}_value"] = metrics.get("current_value", 0)
        row[f"{name}_return"] = metrics.get("total_return", 0)
        row[f"{name}_dd"] = metrics.get("drawdown", 0)
        row[f"{name}_pf"] = metrics.get("profit_factor", 0)
        last = asset.get("last_signal", {})
        row[f"{name}_signal"] = last.get("signal", "FLAT")
        row[f"{name}_conf"] = last.get("confidence", 0)
    portfolio = state.get("portfolio", {})
    row["portfolio_value"] = portfolio.get("total_value", 0)
    row["portfolio_return"] = portfolio.get("total_return", 0)

    if today not in hist["date"].values if len(hist) > 0 else True:
        new_row = pd.DataFrame([row])
        hist = pd.concat([hist, new_row], ignore_index=True)
        save_history(hist)
    return hist


def run():
    state = load_state()
    if state is None:
        print("No state found. Run paper trading engine first.")
        return
    hist = update_history(state)
    print_daily(state, hist)
    # Save report
    report = {
        "timestamp": datetime.now().isoformat(),
        "state": state,
        "halts": check_halts(state, hist),
        "correlation": compute_pnl_correlation(hist),
        "rolling_pf": compute_rolling_pf(state),
    }
    with open(REPORT_PATH, "w") as f:
        json.dump(report, f, indent=2, cls=EigenCapitalJSONEncoder)
    print(f"\nReport saved to {REPORT_PATH}")


def compute_rolling_pf(state):
    """30-day rolling profit factor from trade history."""
    results = {}
    for name in ["XLF", "BTC", "NZDJPY"]:
        asset = state.get("assets", {}).get(name, {})
        metrics = asset.get("metrics", {})
        trades = metrics.get("trade_log", [])
        if len(trades) < 5:
            results[name] = None
            continue
        td = pd.DataFrame(trades[-30:])
        profits = td[td["pnl"] > 0]["pnl"].sum()
        losses = abs(td[td["pnl"] < 0]["pnl"].sum())
        results[name] = round(profits / losses, 2) if losses > 0 else None
    return results


if __name__ == "__main__":
    run()
