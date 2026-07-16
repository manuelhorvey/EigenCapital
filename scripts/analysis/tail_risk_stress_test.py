#!/usr/bin/env python3
"""
Tail-Risk Stress Test — Replay of August 2024 Yen Carry-Trade Unwind.

Replays all protective gates against the historic 21-trade losing streak
(Aug 5-30, 2024) to measure which gates would have prevented losses and
by how much.

Use after any retraining cycle to confirm gate effectiveness hasn't
changed.  The stress test uses the historical trade data so results
will be identical unless fresh trade data has been accumulated with
different model confidence values.

Usage:
    PYTHONPATH=$PYTHONPATH:. python scripts/analysis/tail_risk_stress_test.py
"""

from __future__ import annotations

import json
import logging
from collections import defaultdict
from datetime import datetime, timedelta
from pathlib import Path

import numpy as np
import pandas as pd

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
logger = logging.getLogger("tail_risk_stress_test")

PROJECT = Path(__file__).resolve().parent.parent.parent
DATA_DIR = PROJECT / "data"
YFINANCE_DIR = DATA_DIR / "yfinance_10yr"
TRADE_DATA = DATA_DIR / "processed" / "trade_lifecycle_results.json"

# Assets that suffered losses during the drawdown
AFFECTED_ASSETS = ["EURCHF", "USDJPY", "^DJI", "NZDCHF", "AUDJPY", "GC", "EURNZD", "GBPAUD"]


def load_vix_data() -> pd.Series | None:
    """Load VIX data from the cached macro parquet."""
    vix_path = YFINANCE_DIR / "macro_vix.parquet"
    if not vix_path.exists():
        logger.warning(f"VIX data not found at {vix_path}")
        return None
    df = pd.read_parquet(vix_path)
    if not isinstance(df.index, pd.DatetimeIndex):
        if "date" in df.columns:
            df.index = pd.to_datetime(df["date"])
        else:
            df.index = pd.to_datetime(df.index)
    close_col = "close" if "close" in df.columns else "Close" if "Close" in df.columns else df.columns[0]
    return df[close_col].dropna().sort_index()


def load_asset_ohlcv(asset: str) -> pd.DataFrame | None:
    """Load OHLCV data for an asset."""
    safe = asset.replace("^", "")
    path = YFINANCE_DIR / f"{safe}_ohlcv.parquet"
    if asset == "^DJI":
        path = YFINANCE_DIR / "^DJI_ohlcv.parquet"
    if not path.exists():
        return None
    df = pd.read_parquet(path)
    if not isinstance(df.index, pd.DatetimeIndex):
        if "date" in df.columns:
            df.index = pd.to_datetime(df["date"])
        else:
            df.index = pd.to_datetime(df.index)
    df = df.sort_index()
    return df


def load_trade_data() -> dict:
    """Load all trades and extract those during Aug 2024."""
    with open(TRADE_DATA) as f:
        d = json.load(f)

    trades_map = d.get("_trades", {})
    all_trades = []

    for asset_name, ts in trades_map.items():
        for t in ts:
            exit_d = str(t.get("exit_date", ""))[:10]
            entry_d = str(t.get("entry_date", ""))[:10]
            all_trades.append({
                "asset": asset_name,
                "r": t.get("r_multiple", 0),
                "exit_date": exit_d,
                "entry_date": entry_d,
                "side": t.get("side", "?"),
                "confidence": t.get("confidence", 0.0),
                "p_long": t.get("p_long", 0.5),
                "prob_long": t.get("prob_long", 0.5),
                "prob_short": t.get("prob_short", 0.5),
                "exit_reason": t.get("exit_reason", ""),
                "entry_price": t.get("entry_price", 0),
                "exit_price": t.get("exit_price", 0),
            })

    return all_trades


def compute_ma50_trend(df: pd.DataFrame) -> dict:
    """Compute MA50 and detect bull/bear regime on each date."""
    close = df["close"].dropna() if "close" in df.columns else df["Close"].dropna()
    if len(close) < 60:
        return {}

    ma50 = close.rolling(50).mean()
    result = {}
    for dt, c in close.items():
        m = ma50.get(dt)
        if pd.notna(m):
            result[dt.date()] = {
                "close": c,
                "ma50": m,
                "trend": "bull" if c > m else "bear",
            }
    return result


def simulate_regime_gate(trades: list[dict], trend_data: dict) -> tuple[list[dict], int, float]:
    """Simulate the regime transition gate.

    Gate logic (from apply_regime_transition_gate):
      1. Track last trend per asset (bull/bear based on close vs MA50)
      2. When trend changes, record transition_date
      3. Block entries for 30 days after transition
    """
    blocked = []
    allowed = []
    total_r_blocked = 0.0

    per_asset_state: dict[str, dict] = {}
    SUPPRESS_DAYS = 30

    for t in trades:
        asset = t["asset"]
        if asset not in per_asset_state:
            per_asset_state[asset] = {
                "last_trend": None,
                "transition_date": None,
            }
        state = per_asset_state[asset]

        # Get the trend on the entry date
        try:
            entry_dt = datetime.strptime(t["entry_date"], "%Y-%m-%d").date()
        except (ValueError, IndexError):
            allowed.append(t)
            continue

        # Find the trend regime on entry date
        entry_trend = None
        if asset in trend_data:
            # Find closest date <= entry_date
            asset_trends = trend_data[asset]
            closest = None
            for trend_date, vals in sorted(asset_trends.items()):
                if trend_date <= entry_dt:
                    closest = vals["trend"]
            entry_trend = closest

        if entry_trend is None:
            allowed.append(t)
            continue

        # Detect transition
        if state["last_trend"] is not None and entry_trend != state["last_trend"]:
            state["transition_date"] = entry_dt
            state["last_trend"] = entry_trend
        elif state["last_trend"] is None:
            state["last_trend"] = entry_trend

        # Check suppression period
        if state["transition_date"] is not None:
            days_since = (entry_dt - state["transition_date"]).days
            if 0 <= days_since < SUPPRESS_DAYS:
                blocked.append(t)
                total_r_blocked += t["r"]
                continue

        allowed.append(t)

    return allowed, len(blocked), total_r_blocked


def simulate_vix_gate(trades: list[dict], vix_data: pd.Series) -> tuple[list[dict], int, float]:
    """Simulate the VIX gate.

    Blocks entries when VIX > 30 (the CL=F threshold).
    Extended to all assets for this stress test.
    """
    blocked = []
    allowed = []
    total_r_blocked = 0.0
    THRESHOLD = 30.0
    STALE_DAYS = 5

    # Pre-process VIX: make tz-naive
    vix_local = vix_data.copy()
    if hasattr(vix_local.index, 'tz') and vix_local.index.tz is not None:
        vix_local.index = vix_local.index.tz_localize(None)
    vix_dates = vix_local.index.to_list()
    vix_values = vix_local.values

    for t in trades:
        try:
            entry_dt = pd.Timestamp(t["entry_date"]).tz_localize(None)
        except (ValueError, IndexError):
            allowed.append(t)
            continue

        # Find nearest VIX date <= entry date
        mask = [d for d in vix_dates if d <= entry_dt]
        if mask:
            nearest_date = mask[-1]
            nearest_idx = vix_dates.index(nearest_date)
            nearest_vix = vix_values[nearest_idx]
            days_old = (entry_dt - nearest_date).days
            if days_old > STALE_DAYS:
                allowed.append(t)
                continue
            if nearest_vix > THRESHOLD:
                blocked.append(t)
                total_r_blocked += t["r"]
                continue

        allowed.append(t)

    return allowed, len(blocked), total_r_blocked


def simulate_calibration_drift_gate(trades: list[dict]) -> tuple[list[dict], int, float]:
    """Simulate the calibration drift gate.

    Tracks a rolling 30-trade window of (confidence, was_win) per asset.
    When confidence - win_rate > 20pp, suppresses entries.
    """
    blocked = []
    allowed = []
    total_r_blocked = 0.0
    WINDOW = 30
    GAP_THRESHOLD = 0.20

    per_asset_records: dict[str, list[tuple[float, bool]]] = {}

    for t in sorted(trades, key=lambda x: x["exit_date"]):
        asset = t["asset"]
        confidence = t["confidence"] if t["confidence"] > 0 else max(t["prob_long"], t.get("prob_short", 0.5))
        was_win = t["r"] > 0

        if asset not in per_asset_records:
            per_asset_records[asset] = []

        records = per_asset_records[asset]

        # Check drift BEFORE trading
        gap = None
        if len(records) >= 10:
            mean_conf = sum(r[0] for r in records[-WINDOW:]) / min(len(records), WINDOW)
            mean_wr = sum(1 for r in records[-WINDOW:] if r[1]) / min(len(records), WINDOW)
            gap = mean_conf - mean_wr

        if gap is not None and gap > GAP_THRESHOLD:
            blocked.append(t)
            total_r_blocked += t["r"]
            records.append((confidence, was_win))
            continue

        allowed.append(t)
        records.append((confidence, was_win))

    return allowed, len(blocked), total_r_blocked


def simulate_confidence_gate(trades: list[dict]) -> tuple[list[dict], int, float]:
    """Simulate the direction-conditional confidence gate.

    BUY threshold: 0.45 (min_confidence_buy)
    SELL threshold: 0.55 (min_confidence_sell)
    """
    blocked = []
    allowed = []
    total_r_blocked = 0.0
    BUY_TH = 0.45
    SELL_TH = 0.55

    for t in trades:
        side = t["side"]
        confidence = t["confidence"] if t["confidence"] > 0 else max(t["prob_long"], t.get("prob_short", 0.5))

        if side == "BUY":
            threshold = BUY_TH
        elif side == "SELL":
            threshold = SELL_TH
        else:
            allowed.append(t)
            continue

        # Invert for SELL — confidence for SELL = 1 - p_long
        if side == "SELL":
            effective_conf = 1.0 - t.get("p_long", 0.5)
        else:
            effective_conf = t.get("p_long", 0.5)

        if effective_conf < threshold:
            blocked.append(t)
            total_r_blocked += t["r"]
            continue

        allowed.append(t)

    return allowed, len(blocked), total_r_blocked


def simulate_drawdown_circuit_breaker(
    trades: list[dict], starting_capital: float = 500.0
) -> tuple[list[dict], int, float, float]:
    """Simulate the -8% drawdown circuit breaker.

    Tracks running equity.  When cumulative PnL drops below -8% of
    peak equity, all subsequent trades are blocked.
    """
    blocked = []
    allowed = []
    total_r_blocked = 0.0
    threshold = 0.08

    risk_per_trade = 0.01
    equity = starting_capital
    peak = starting_capital
    halted = False

    for t in trades:
        if halted:
            blocked.append(t)
            total_r_blocked += t["r"]
            continue

        dollar_loss = t["r"] * equity * risk_per_trade
        equity += dollar_loss
        if equity > peak:
            peak = equity

        dd_pct = (peak - equity) / peak if peak > 0 else 0

        if dd_pct >= threshold:
            halted = True
            blocked.append(t)
            total_r_blocked += t["r"]
            continue

        allowed.append(t)

    return allowed, len(blocked), total_r_blocked, equity


def compute_risk_reduction(trades: list[dict], starting_capital: float = 500.0, risk_pct: float = 0.01) -> float:
    """Compute final equity with a given risk-per-trade percentage."""
    equity = starting_capital
    for t in trades:
        dollar_pnl = t["r"] * equity * risk_pct
        equity += dollar_pnl
        if equity < 0:
            equity = 0
            break
    return equity


def main():
    print("=" * 72)
    print("  TAIL-RISK STRESS TEST: August 2024 Yen Carry-Trade Unwind")
    print("=" * 72)
    print()

    # ── 1. Load data ──
    logger.info("Loading trade data...")
    all_trades = load_trade_data()
    drawdown_trades = [t for t in all_trades if "2024-08-05" <= t["exit_date"] <= "2024-08-30"]
    print(f"\n  Total trades in system: {len(all_trades)}")
    print(f"  Trades during drawdown (Aug 5-30): {len(drawdown_trades)}")
    print(f"  Total R lost: {sum(t['r'] for t in drawdown_trades):+.2f}")
    print(f"  Win rate: {sum(1 for t in drawdown_trades if t['r'] > 0)}/{len(drawdown_trades)} "
          f"({sum(1 for t in drawdown_trades if t['r'] > 0)/len(drawdown_trades)*100:.1f}%)")
    print()

    # ── 2. Per-asset breakdown ──
    print("  ── Per-Asset Breakdown ──")
    print(f"  {'Asset':>10} {'Trades':>7} {'Total R':>8} {'Avg R':>7} {'Side':>6}")
    print(f"  {'-'*10} {'-'*7} {'-'*8} {'-'*7} {'-'*6}")
    per_asset = defaultdict(list)
    for t in drawdown_trades:
        per_asset[t["asset"]].append(t)
    for asset in sorted(per_asset, key=lambda a: sum(t["r"] for t in per_asset[a])):
        ts = per_asset[asset]
        tr = sum(t["r"] for t in ts)
        avg = tr / len(ts)
        sides = defaultdict(int)
        for t in ts:
            sides[t["side"]] += 1
        side_str = "/".join(f"{k}={v}" for k, v in sorted(sides.items()))
        print(f"  {asset:>10} {len(ts):>7} {tr:>+8.2f} {avg:>+7.2f} {side_str}")
    print()

    # ── 3. Load VIX data ──
    vix = load_vix_data()
    if vix is not None:
        vix_aug = vix["2024-07-01":"2024-09-30"]
        print(f"  VIX data loaded: {len(vix_aug)} data points (Jul-Sep 2024)")
        for dt in ["2024-07-31", "2024-08-05", "2024-08-12", "2024-08-19", "2024-08-21", "2024-08-26", "2024-08-30"]:
            if dt in vix_aug.index:
                print(f"    {dt}: VIX = {vix_aug[dt]:.1f}")
        print()
    else:
        print("  ⚠ VIX data not available — VIX gate simulation skipped")
        print()

    # ── 4. Compute MA50 trend for each affected asset ──
    trend_data = {}
    for asset in AFFECTED_ASSETS:
        ohlcv = load_asset_ohlcv(asset)
        if ohlcv is not None:
            trends = compute_ma50_trend(ohlcv)
            if trends:
                trend_data[asset] = trends
                print(f"  {asset}: MA50 trend computed ({len(trends)} data points)")

    print(f"\n  Trend data loaded for {len(trend_data)}/{len(AFFECTED_ASSETS)} assets\n")

    # ── 5. Run gate simulations ──
    print("=" * 72)
    print("  GATE SIMULATION RESULTS")
    print("=" * 72)
    print()

    results = {}

    # 5a. Regime transition gate
    if trend_data:
        allowed, n_blocked, r_blocked = simulate_regime_gate(drawdown_trades, trend_data)
        results["regime_transition"] = {
            "blocked": n_blocked,
            "r_blocked": r_blocked,
            "remaining_r": sum(t["r"] for t in allowed),
            "remaining_trades": len(allowed),
            "pct_blocked": n_blocked / len(drawdown_trades) * 100,
        }
        print(f"  ├─ Regime Transition Gate")
        print(f"  │  Blocked: {n_blocked}/{len(drawdown_trades)} trades ({n_blocked/len(drawdown_trades)*100:.0f}%)")
        print(f"  │  R prevented: {r_blocked:+.2f}")
        print(f"  │  Remaining R: {sum(t['r'] for t in allowed):+.2f}")
    else:
        print(f"  ├─ Regime Transition Gate: SKIPPED (no trend data)")

    # 5b. VIX gate
    if vix is not None:
        allowed, n_blocked, r_blocked = simulate_vix_gate(drawdown_trades, vix)
        results["vix_gate"] = {
            "blocked": n_blocked,
            "r_blocked": r_blocked,
            "remaining_r": sum(t["r"] for t in allowed),
            "remaining_trades": len(allowed),
            "pct_blocked": n_blocked / len(drawdown_trades) * 100,
        }
        print(f"  ├─ VIX Gate (VIX > 30)")
        print(f"  │  Blocked: {n_blocked}/{len(drawdown_trades)} trades ({n_blocked/len(drawdown_trades)*100:.0f}%)")
        print(f"  │  R prevented: {r_blocked:+.2f}")
        print(f"  │  Remaining R: {sum(t['r'] for t in allowed):+.2f}")
    else:
        print(f"  ├─ VIX Gate: SKIPPED (no VIX data)")

    # 5c. Calibration drift gate
    allowed, n_blocked, r_blocked = simulate_calibration_drift_gate(drawdown_trades)
    results["calibration_drift"] = {
        "blocked": n_blocked,
        "r_blocked": r_blocked,
        "remaining_r": sum(t["r"] for t in allowed),
        "remaining_trades": len(allowed),
        "pct_blocked": n_blocked / len(drawdown_trades) * 100,
    }
    print(f"  ├─ Calibration Drift Gate (30-trade window, 20pp gap)")
    print(f"  │  Blocked: {n_blocked}/{len(drawdown_trades)} trades ({n_blocked/len(drawdown_trades)*100:.0f}%)")
    print(f"  │  R prevented: {r_blocked:+.2f}")
    print(f"  │  Remaining R: {sum(t['r'] for t in allowed):+.2f}")

    # 5d. Confidence gate
    allowed, n_blocked, r_blocked = simulate_confidence_gate(drawdown_trades)
    results["confidence_gate"] = {
        "blocked": n_blocked,
        "r_blocked": r_blocked,
        "remaining_r": sum(t["r"] for t in allowed),
        "remaining_trades": len(allowed),
        "pct_blocked": n_blocked / len(drawdown_trades) * 100,
    }
    print(f"  ├─ Directional Confidence Gate (BUY >= 0.45, SELL >= 0.55)")
    print(f"  │  Blocked: {n_blocked}/{len(drawdown_trades)} trades ({n_blocked/len(drawdown_trades)*100:.0f}%)")
    print(f"  │  R prevented: {r_blocked:+.2f}")
    print(f"  │  Remaining R: {sum(t['r'] for t in allowed):+.2f}")

    # 5e. Drawdown circuit breaker
    allowed, n_blocked, r_blocked, final_eq = simulate_drawdown_circuit_breaker(drawdown_trades, 500.0)
    results["circuit_breaker"] = {
        "blocked": n_blocked,
        "r_blocked": r_blocked,
        "remaining_r": sum(t["r"] for t in allowed),
        "remaining_trades": len(allowed),
        "pct_blocked": n_blocked / len(drawdown_trades) * 100,
        "final_equity": final_eq,
    }
    print(f"  ├─ Drawdown Circuit Breaker (-8% from peak, 1.0% risk)")
    print(f"  │  Blocked: {n_blocked}/{len(drawdown_trades)} trades ({n_blocked/len(drawdown_trades)*100:.0f}%)")
    print(f"  │  R prevented: {r_blocked:+.2f}")
    print(f"  │  Final equity: ${final_eq:.2f}")
    print()

    # ── 6. Combined gate simulation ──
    print("  ── Combined Gate Simulation (all gates active) ──")
    remaining = list(drawdown_trades)

    gate_order = [
        ("Regime Transition", simulate_regime_gate, {"trend_data": trend_data} if trend_data else None),
        ("VIX Gate (>30)", simulate_vix_gate, vix),
        ("Calibration Drift", simulate_calibration_drift_gate, None),
        ("Confidence Gate", simulate_confidence_gate, None),
    ]

    total_blocked_all = 0
    total_r_prevented = 0.0

    for gate_name, gate_fn, gate_data in gate_order:
        if gate_data is None:
            remaining, nb, rp = gate_fn(remaining)
        elif isinstance(gate_data, dict):
            remaining, nb, rp = gate_fn(remaining, **gate_data)
        else:
            remaining, nb, rp = gate_fn(remaining, gate_data)
        total_blocked_all += nb
        total_r_prevented += rp
        print(f"    {gate_name:<25} blocked {nb:>2} trades ({rp:>+.2f}R prevented)")

    # Apply circuit breaker last
    remaining, cb_blocked, cb_r, cb_equity = simulate_drawdown_circuit_breaker(remaining, 500.0)
    total_blocked_all += cb_blocked
    total_r_prevented += cb_r
    print(f"    Circuit Breaker           blocked {cb_blocked:>2} trades ({cb_r:>+.2f}R prevented)")
    print()
    print(f"    Total blocked by all gates: {total_blocked_all}/{len(drawdown_trades)} trades")
    print(f"    Total R prevented: {total_r_prevented:+.2f}")
    print(f"    Remaining R: {sum(t['r'] for t in remaining):+.2f} across {len(remaining)} trades")
    print()

    # ── 7. Risk reduction comparison ──
    print("  ── Risk Reduction Simulation ($500 start) ──")
    eq_2pct = compute_risk_reduction(drawdown_trades, 500.0, 0.02)
    eq_1pct = compute_risk_reduction(drawdown_trades, 500.0, 0.01)
    eq_05pct = compute_risk_reduction(drawdown_trades, 500.0, 0.005)
    print(f"    {'Risk':>12} {'Final Equity':>14} {'Loss %':>8}")
    print(f"    {'-'*12} {'-'*14} {'-'*8}")
    print(f"    {'2.0% (old)':>12} ${eq_2pct:>10.2f} {(500-eq_2pct)/500*100:>7.1f}%")
    print(f"    {'1.0% (new)':>12} ${eq_1pct:>10.2f} {(500-eq_1pct)/500*100:>7.1f}%")
    print(f"    {'0.5%':>12} ${eq_05pct:>10.2f} {(500-eq_05pct)/500*100:>7.1f}%")
    print()

    eq_combined = compute_risk_reduction(remaining, 500.0, 0.01)
    print(f"    All gates + 1.0% risk: ${eq_combined:.2f} ({(500-eq_combined)/500*100:.1f}% loss)")
    print()

    # ── 8. Per-asset gate effectiveness ──
    print("  ── Per-Asset Gate Effectiveness ──")
    for asset in sorted(per_asset):
        asset_trades = per_asset[asset]
        asset_r = sum(t["r"] for t in asset_trades)
        n = len(asset_trades)
        sides = defaultdict(int)
        for t in asset_trades:
            sides[t["side"]] += 1
        side_str = "/".join(f"{k}={v}" for k, v in sorted(sides.items()))

        if vix is not None:
            _, nb_vix, rp_vix = simulate_vix_gate(asset_trades, vix)
        else:
            nb_vix, rp_vix = 0, 0.0

        if trend_data:
            _, nb_reg, rp_reg = simulate_regime_gate(asset_trades, trend_data)
        else:
            nb_reg, rp_reg = 0, 0.0

        print(f"    {asset:>10}: {n:>2} trades, {asset_r:>+.2f}R total, {side_str}")
        if nb_vix > 0 or nb_reg > 0:
            print(f"             VIX blocks {nb_vix:>2} ({rp_vix:>+.2f}R) | Regime blocks {nb_reg:>2} ({rp_reg:>+.2f}R)")

    # ── 9. Summary ──
    print()
    print("=" * 72)
    print("  VERDICT")
    print("=" * 72)
    print()

    original_loss = sum(t["r"] for t in drawdown_trades)
    after_all = sum(t["r"] for t in remaining)

    prevention_pct = (abs(original_loss) - abs(after_all)) / abs(original_loss) * 100 if original_loss < 0 else 0

    print(f"  Original drawdown loss:     {original_loss:>+.2f}R  (-$217 at 2.0% risk)")
    print(f"  After all gates + 1.0% risk: {after_all:>+.2f}R  (-${500 - eq_combined:.2f})")
    print(f"  Loss prevented:             {prevention_pct:.0f}%")
    print()

    if prevention_pct >= 80:
        print("  ✅ EXCELLENT — gates would have prevented >=80% of drawdown losses")
    elif prevention_pct >= 50:
        print("  ⚠️ MODERATE — gates would have prevented >=50% of drawdown losses")
    elif prevention_pct >= 25:
        print("  ⚠️ WEAK — gates would have prevented <50% of drawdown losses")
    else:
        print("  ❌ INSUFFICIENT — gates failed to prevent meaningful losses")
    print()

    gate_effectiveness = {}
    for gate, data in results.items():
        if "r_blocked" in data:
            gate_effectiveness[gate] = abs(data["r_blocked"])
    if gate_effectiveness:
        best_gate = max(gate_effectiveness, key=gate_effectiveness.get)
        print(f"  Most effective single gate: {best_gate} "
              f"(prevented {abs(results[best_gate]['r_blocked']):+.2f}R)")
        print()

    print(f"  With 1.0% risk (current config):")
    print(f"    Loss during drawdown:         ${500 - eq_1pct:.2f} ({(500-eq_1pct)/500*100:.1f}%)")
    print(f"    With all gates + 1.0% risk:   ${500 - eq_combined:.2f} ({(500-eq_combined)/500*100:.1f}%)")
    print()

    if vix is not None:
        vix_drawdown = vix["2024-08-01":"2024-09-30"]
        vix_above_30 = (vix_drawdown > 30).sum()
        print(f"  VIX during drawdown period:")
        print(f"    Days with VIX > 30: {vix_above_30}/{len(vix_drawdown)}")
        print(f"    Peak VIX: {vix_drawdown.max():.1f}")
        print(f"    VIX mean: {vix_drawdown.mean():.1f}")
    print()

    if trend_data:
        print(f"  MA50 crossing chronology:")
        for asset in AFFECTED_ASSETS:
            if asset in trend_data:
                trends = trend_data[asset]
                bear_crossings = []
                prev_trend = None
                for dt in sorted(trends):
                    cur = trends[dt]["trend"]
                    if prev_trend is not None and cur != prev_trend and cur == "bear":
                        bear_crossings.append((dt, trends[dt]["close"], trends[dt]["ma50"]))
                    prev_trend = cur
                if bear_crossings:
                    last_bear = bear_crossings[-1]
                    expiry = last_bear[0] + timedelta(days=30)
                    print(f"    {asset}: last bear cross {last_bear[0]} (suppression until {expiry})")
                    if expiry < datetime(2024, 8, 21).date():
                        print(f"           ❌ Suppression expired BEFORE drawdown")
                    else:
                        print(f"           ✅ Would have covered drawdown")

    print("\n" + "=" * 72)


if __name__ == "__main__":
    main()
