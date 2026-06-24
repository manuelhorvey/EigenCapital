#!/usr/bin/env python3
"""Phase 2: Historical backtest sweep of trailing stop parameters.

Compares fixed SL/TP vs trailing stops with various activation/distance
multipliers on the same walk-forward framework used by sweep_sl.py.

Results are saved to data/research/trailing_sweep_results.json for Phase 3 analysis.
"""

import itertools, json, os, sys, logging
import pandas as pd
import numpy as np
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
logging.basicConfig(level=logging.WARNING, format="%(asctime)s [%(levelname)s] %(message)s")

import xgboost as xgb
from sklearn.model_selection import train_test_split

from features.registry import FEATURE_REGISTRY
from features.builder import build_features
from backtests import compute_per_fold_labels

from shared.volatility import compute_atr_pct
from backtests.trade_analysis import fetch_ohlcv, load_macro, _signals, aggregate

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
macro = load_macro()

# Test trailing params
TRAILING_ACTIVATIONS = [None, 0.3, 0.5, 0.8, 1.0]
TRAILING_DISTANCES = [0.5, 0.8, 1.0, 1.5]

# Assets to sweep (all 21 paper trading assets)
CANDIDATES = [
    ("AUDUSD", "AUDUSD=X"), ("AUDCHF", "AUDCHF=X"), ("AUDNZD", "AUDNZD=X"),
    ("CADCHF", "CADCHF=X"), ("ES", "ES=F"), ("EURCAD", "EURCAD=X"),
    ("EURCHF", "EURCHF=X"), ("EURNZD", "EURNZD=X"), ("EURUSD", "EURUSD=X"),
    ("GBPAUD", "GBPAUD=X"), ("GBPCAD", "GBPCAD=X"), ("GBPCHF", "GBPCHF=X"),
    ("GBPNZD", "GBPNZD=X"), ("GC", "GC=F"), ("NQ", "NQ=F"),
    ("NZDCAD", "NZDCAD=X"), ("NZDCHF", "NZDCHF=X"), ("NZDUSD", "NZDUSD=X"),
    ("USDCAD", "USDCAD=X"), ("USDCHF", "USDCHF=X"), ("^DJI", "^DJI"),
]

# Per-asset config from trade_analysis.py
SLTP_CFG = {
    "GC": {"sl": 1.0, "tp": 4.0}, "USDCHF": {"sl": 0.85, "tp": 3.0},
    "AUDCHF": {"sl": 2.75, "tp": 3.5}, "USDCAD": {"sl": 2.5, "tp": 2.03},
    "ES": {"sl": 2.0, "tp": 5.5}, "NQ": {"sl": 2.5, "tp": 5.0},
    "GBPCAD": {"sl": 2.5, "tp": 2.5}, "GBPNZD": {"sl": 3.0, "tp": 1.0},
    "NZDCAD": {"sl": 2.5, "tp": 4.0}, "^DJI": {"sl": 0.5, "tp": 4.0},
    "EURUSD": {"sl": 3.0, "tp": 1.5}, "NZDUSD": {"sl": 2.5, "tp": 1.5},
    "GBPAUD": {"sl": 1.0, "tp": 2.0}, "NZDCHF": {"sl": 1.0, "tp": 4.0},
    "CADCHF": {"sl": 1.0, "tp": 4.0}, "AUDUSD": {"sl": 1.5, "tp": 4.0},
    "AUDNZD": {"sl": 2.0, "tp": 1.0}, "EURCHF": {"sl": 1.0, "tp": 3.0},
    "EURCAD": {"sl": 1.0, "tp": 1.0}, "EURNZD": {"sl": 1.5, "tp": 2.5},
    "GBPCHF": {"sl": 1.0, "tp": 2.0},
}
MODEL_DEPTH = {
    "GC": 2, "USDCHF": 4, "AUDCHF": 2, "USDCAD": 5, "ES": 2,
    "NQ": 2, "GBPCAD": 2, "GBPNZD": 3, "NZDCAD": 2, "^DJI": 4,
    "EURUSD": 3, "NZDUSD": 5, "GBPAUD": 2, "NZDCHF": 2,
    "CADCHF": 2, "AUDUSD": 2, "AUDNZD": 2, "EURCHF": 4,
    "EURCAD": 3, "EURNZD": 3, "GBPCHF": 2,
}
REGIME_GEOM = {
    "low": {"sl": 0.80, "tp": 1.10},
    "mid": {"sl": 1.00, "tp": 1.00},
    "high": {"sl": 1.00, "tp": 1.00},
}
DEF_SL, DEF_TP = 1.0, 2.0
MAX_BARS = 60
MIN_TRADES = 10


def _simulate_trailing(sigs, close, high, low, name, slm, tpm, atr, regime,
                       trail_act=None, trail_dist=None):
    """Simulate trades with optional trailing stop.

    Parameters
    ----------
    trail_act : float or None
        Trailing activation multiplier on initial SL distance.
        None = no trailing (baseline, same as sweep_sl).
    trail_dist : float or None
        Trailing distance in ATR multiples once active.
    """
    trades = []
    in_pos = False
    pos = entry_px = sl = tp = 0.0
    entry_i = -1
    entry_sig = 0
    entry_dt = None
    entry_atr = 0.0
    hi_water = lo_water = 0.0
    sl_trailing_active = False
    best_price = 0.0

    for i in range(1, len(sigs)):
        cs = int(sigs["signal"].iloc[i])
        cc, ch, cl = float(close.iloc[i]), float(high.iloc[i]), float(low.iloc[i])
        dt = str(sigs.index[i].date())

        if in_pos:
            hi_water = max(hi_water, ch)
            lo_water = min(lo_water, cl)

            # Track best price for trailing
            if pos == 2:
                best_price = max(best_price, ch)
            else:
                best_price = min(best_price, cl)

            # Update trailing stop if active
            current_sl = sl
            if trail_act is not None and trail_dist is not None and not sl_trailing_active:
                if pos == 2:
                    move = (best_price - entry_px) / (entry_px - sl + 1e-9)
                    if move >= trail_act:
                        v = entry_atr
                        dist = v * trail_dist
                        sl = best_price - dist
                        sl_trailing_active = True
                else:
                    move = (entry_px - best_price) / (sl - entry_px + 1e-9)
                    if move >= trail_act:
                        v = entry_atr
                        dist = v * trail_dist
                        sl = best_price + dist
                        sl_trailing_active = True

            # Check SL/TP hit
            sl_hit = (pos == 2 and cl <= sl) or (pos == 0 and ch >= sl)
            tp_hit = (pos == 2 and ch >= tp) or (pos == 0 and cl <= tp)
            held = i - entry_i
            flip = cs != 1 and cs != entry_sig
            reason = None

            if sl_hit:
                reason = "sl"
                ep = sl
            elif tp_hit:
                reason = "tp"
                ep = tp
            elif flip:
                reason = "signal_flip"
                ep = cc
            elif held >= MAX_BARS:
                reason = "time_stop"
                ep = cc

            if reason:
                ret = (ep / entry_px - 1) if pos == 2 else (entry_px / ep - 1)
                risk = abs(entry_px - current_sl) / entry_px if current_sl > 0 else 0.01
                # MAE/MFE in price terms
                if pos == 2:
                    mae_r = (entry_px - lo_water) / (entry_px * risk) if risk else 0.0
                    mfe_r = (hi_water - entry_px) / (entry_px * risk) if risk else 0.0
                else:
                    mae_r = (hi_water - entry_px) / (entry_px * risk) if risk else 0.0
                    mfe_r = (entry_px - lo_water) / (entry_px * risk) if risk else 0.0
                trades.append({
                    "asset": name, "side": "long" if pos == 2 else "short",
                    "entry_price": round(entry_px, 6), "entry_date": str(entry_dt.date()),
                    "exit_price": round(ep, 6), "exit_date": dt, "exit_reason": reason,
                    "bars_held": held, "return": round(ret, 6),
                    "r_multiple": round(ret / risk, 4) if risk else 0.0,
                    "mae_r": round(mae_r, 4), "mfe_r": round(mfe_r, 4),
                    "sl_trailed": sl_trailing_active,
                })
                in_pos = False
                continue

        if not in_pos and cs != 1:
            in_pos = True
            pos = cs
            entry_sig = cs
            entry_px = cc
            entry_i = i
            entry_dt = sigs.index[i]
            v = max(float(atr.iloc[i]) if i < len(atr) else 0.01, 0.001)
            entry_atr = v
            rg = regime.iloc[i] if regime is not None else "mid"
            rg_sl = REGIME_GEOM.get(rg, {}).get("sl", 1.0)
            rg_tp = REGIME_GEOM.get(rg, {}).get("tp", 1.0)
            sl = entry_px * (1 - v * slm * rg_sl) if pos == 2 else entry_px * (1 + v * slm * rg_sl)
            tp = entry_px * (1 + v * tpm * rg_tp) if pos == 2 else entry_px * (1 - v * tpm * rg_tp)
            hi_water = ch
            lo_water = cl
            best_price = cc if pos == 2 else cc
            sl_trailing_active = False
    return trades


def run_asset(name, ticker, contract, trail_act, trail_dist):
    """Run walk-forward backtest for one asset with given trailing params."""
    df = fetch_ohlcv(ticker)
    fdf = build_features(df, macro, None, contract, compute_labels=False)
    if fdf is None or fdf.empty:
        return None

    X = fdf[[c for c in contract.features if c in fdf.columns]]


    close = df["close"].reindex(X.index)
    high = df["high"].reindex(X.index)
    low = df["low"].reindex(X.index)

    atr = compute_atr_pct(df, 14).reindex(X.index).ffill()
    atr_pct = atr.rolling(252, min_periods=20).rank(pct=True).ffill()
    regime = atr_pct.fillna(0.5).apply(
        lambda p: {0: "low", 1: "mid", 2: "high"}.get(min(int(p * 3), 2), "mid")
    ).astype(str)

    slm = SLTP_CFG.get(name, {}).get("sl", DEF_SL)
    tpm = SLTP_CFG.get(name, {}).get("tp", DEF_TP)
    depth = MODEL_DEPTH.get(name, 2)

    all_trades = []
    for ty in range(2023, 2026):
        cut = pd.Timestamp(f"{ty}-01-01", tz="US/Eastern")
        eoy = pd.Timestamp(f"{ty}-12-31", tz="US/Eastern")
        train_mask = X.index < cut
        test_mask = (X.index >= cut) & (X.index <= eoy)
        if test_mask.sum() < 20:
            continue

        X_tr = X[train_mask]
        y_tr, y_te = compute_per_fold_labels(close, train_mask, test_mask, contract)
        X_te = X[test_mask]

        if len(X_tr) < 200:
            continue
        uq = set(y_tr.unique())
        if uq != {0, 1, 2}:
            continue

        mc = y_tr.value_counts().min()
        strat = y_tr if mc >= 2 else None
        X_tr2, X_ev, y_tr2, y_ev = train_test_split(
            X_tr, y_tr, test_size=0.2, random_state=42, stratify=strat
        )

        model = xgb.XGBClassifier(
            n_estimators=300, max_depth=depth, learning_rate=0.02,
            objective="multi:softprob", num_class=3, random_state=42,
            n_jobs=1, tree_method="hist", verbosity=0,
        )
        model.fit(X_tr2, y_tr2, eval_set=[(X_ev, y_ev)], verbose=False)
        proba = model.predict_proba(X_te)
        sigs = _signals(proba, X_te.index)
        tr = _simulate_trailing(
            sigs, close.reindex(X_te.index), high.reindex(X_te.index),
            low.reindex(X_te.index), name, slm, tpm, atr, regime,
            trail_act=trail_act, trail_dist=trail_dist,
        )
        all_trades.extend(tr)

    if len(all_trades) < MIN_TRADES:
        return None
    agg = aggregate(all_trades)
    return agg


def label(trail_act, trail_dist):
    if trail_act is None:
        return "baseline"
    return f"act{trail_act}_dist{trail_dist}"


def main():
    results = []

    for name, ticker in CANDIDATES:
        contract = FEATURE_REGISTRY.get(ticker)
        if contract is None:
            print(f"SKIP {name}: no contract", flush=True)
            continue

        print(f"\n{'='*60}", flush=True)
        print(f"{name} ({ticker})", flush=True)
        print(f"{'='*60}", flush=True)

        asset_results = []

        # Baseline: no trailing
        agg = run_asset(name, ticker, contract, trail_act=None, trail_dist=None)
        if agg is None:
            print(f"  BASELINE: NO TRADES", flush=True)
            continue
        o = agg.get("overall", {})
        baseline_r = o.get("avg_r", 0)
        baseline_pf = o.get("profit_factor", 0)
        baseline_wr = o.get("win_rate", 0)
        baseline_n = agg["n_trades"]
        asset_results.append({
            "config": "baseline", "trail_act": None, "trail_dist": None,
            "pf": round(baseline_pf, 3), "avg_r": round(baseline_r, 4),
            "win_rate": round(baseline_wr, 4), "n": baseline_n,
        })
        print(f"  BASELINE: PF={baseline_pf:.3f} avgR={baseline_r:+.4f} WR={baseline_wr:.1%} n={baseline_n}", flush=True)

        # Trailing sweeps
        for act, dist in itertools.product(TRAILING_ACTIVATIONS, TRAILING_DISTANCES):
            if act is None:
                continue
            agg = run_asset(name, ticker, contract, trail_act=act, trail_dist=dist)
            if agg is None:
                continue
            o = agg.get("overall", {})
            pf = o.get("profit_factor", 0)
            ar = o.get("avg_r", 0)
            wr = o.get("win_rate", 0)
            n = agg["n_trades"]
            delta_r = ar - baseline_r
            marker = " <<<" if delta_r > 0.02 else ""
            asset_results.append({
                "config": label(act, dist),
                "trail_act": act, "trail_dist": dist,
                "pf": round(pf, 3), "avg_r": round(ar, 4),
                "win_rate": round(wr, 4), "delta_r": round(delta_r, 4),
                "n": n,
            })
            print(f"  {label(act, dist):>18s}: PF={pf:.3f} avgR={ar:+.4f} ΔR={delta_r:+.4f} WR={wr:.1%} n={n}{marker}", flush=True)

        if asset_results:
            best = max(asset_results[1:], key=lambda x: x["avg_r"]) if len(asset_results) > 1 else asset_results[0]
            print(f"\n  >> BEST: {best['config']}: avgR={best['avg_r']:+.4f} PF={best['pf']:.3f}", flush=True)
            results.append({
                "asset": name, "ticker": ticker,
                "baseline": asset_results[0],
                "trailing_sweep": asset_results[1:],
                "best": best,
            })

    # Print summary table
    print(f"\n{'='*80}", flush=True)
    print("TRAILING SWEEP SUMMARY", flush=True)
    print(f"{'='*80}", flush=True)
    print(f"{'Asset':10s} {'Baseline_R':>10s} {'Best_R':>10s} {'ΔR':>8s} {'Best_Config':>20s} {'Best_PF':>8s}", flush=True)
    print("-" * 70, flush=True)
    for r in sorted(results, key=lambda x: -x["best"]["avg_r"]):
        bl = r["baseline"]
        best = r["best"]
        delta = best["avg_r"] - bl["avg_r"]
        print(f"{r['asset']:10s} {bl['avg_r']:>+10.4f} {best['avg_r']:>+10.4f} {delta:>+8.4f} {best['config']:>20s} {best['pf']:>8.3f}", flush=True)

    # Save results
    out_dir = os.path.join(BASE_DIR, "..", "data", "research")
    os.makedirs(out_dir, exist_ok=True)
    out_path = os.path.join(out_dir, "trailing_sweep_results.json")
    with open(out_path, "w") as f:
        json.dump(results, f, indent=2)
    print(f"\nResults saved to {out_path}", flush=True)


if __name__ == "__main__":
    main()
