"""
Walk-forward threshold comparison: train ONCE per fold, cache raw probabilities,
apply 0.45 and 0.40 thresholds post-hoc to the SAME predictions.

Usage: PYTHONPATH=$PYTHONPATH:. python scripts/analysis/threshold_validation.py
"""

import csv
import logging
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
logging.basicConfig(level=logging.WARNING)

import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402
import xgboost as xgb  # noqa: E402

from archive.deprecated._builder import build_features, compute_macro_derived  # noqa: E402
from features.registry import FEATURE_REGISTRY  # noqa: E402
from labels.triple_barrier import apply_triple_barrier  # noqa: E402
from scripts.training.train_all_assets import fetch_history  # noqa: E402

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

DASHBOARD_TICKERS = [
    "GC=F",
    "USDCHF=X",
    "USDCAD=X",
    "ES=F",
    "NQ=F",
    "GBPCAD=X",
    "NZDCAD=X",
    "^DJI",
    "NZDUSD=X",
    "GBPAUD=X",
    "NZDCHF=X",
    "CADCHF=X",
    "AUDUSD=X",
    "EURCHF=X",
    "EURCAD=X",
    "EURNZD=X",
    "GBPCHF=X",
    "GBPUSD=X",
    "EURAUD=X",
    "USDJPY=X",
    "GBPJPY=X",
]


def run_single_asset(ticker, macro, ref):
    df = fetch_history(ticker)
    contract = FEATURE_REGISTRY[ticker]
    fdf, feats = build_features(df, macro, ref, contract, compute_labels=False), list(contract.features)
    if len(fdf) < 500:
        return None

    close_series = df["close"].copy()
    if close_series.index.tz is not None:
        close_series.index = close_series.index.tz_localize(None)
    closes = close_series.reindex(fdf.index)
    returns = closes.pct_change().shift(-1)
    years = sorted(fdf.index.year.unique())

    pt_sl = contract.label_params.get("pt_sl", [2.0, 2.0])
    vb = contract.label_params.get("vertical_barrier", 20)

    all_records = []
    for cy in range(years[0] + 3, years[-1] + 1, 1):
        train_mask = fdf.index.year <= cy - 1
        oos_mask = fdf.index.year == cy
        X_train = fdf.loc[train_mask, feats]
        X_oos = fdf.loc[oos_mask, feats]
        if len(X_oos) == 0 or len(X_train) < 200:
            continue

        tc = closes.loc[train_mask]
        tee = min(len(closes), train_mask.sum() + vb)
        tl = apply_triple_barrier(closes.iloc[:tee].to_frame("close"), pt_sl=pt_sl, vertical_barrier=vb)
        if tl is None or tl.empty:
            continue
        yt = (tl.reindex(tc.index)["label"].dropna().astype(int) + 1).astype(int)
        tv = yt.index.intersection(X_train.index)
        X_train, y_train = X_train.loc[tv], yt.loc[tv]

        oc = closes.loc[oos_mask]
        oee = min(len(closes), oos_mask.sum() + vb + train_mask.sum())
        ol = apply_triple_barrier(
            closes.iloc[train_mask.sum() : oee].to_frame("close"), pt_sl=pt_sl, vertical_barrier=vb
        )
        if ol is None or ol.empty:
            continue
        yo = (ol.reindex(oc.index)["label"].dropna().astype(int) + 1).astype(int)
        ov = yo.index.intersection(X_oos.index)
        X_oos, y_oos = X_oos.loc[ov], yo.loc[ov]

        if len(y_oos) == 0 or len(y_train) < 200 or len(np.unique(y_train)) < 3:
            continue

        model = xgb.XGBClassifier(
            n_estimators=300,
            max_depth=2,
            learning_rate=0.02,
            objective="multi:softprob",
            num_class=3,
            random_state=42,
            n_jobs=1,
            tree_method="hist",
            verbosity=0,
        )
        model.fit(X_train, y_train, eval_set=[(X_oos, y_oos)], verbose=False)

        proba = model.predict_proba(X_oos)
        oos_ret = returns.loc[X_oos.index]
        for j in range(len(X_oos)):
            r = oos_ret.iloc[j]
            all_records.append(
                {
                    "window": cy,
                    "prob_long": proba[j, 2],
                    "prob_short": proba[j, 0],
                    "return": 0.0 if np.isnan(r) else r,
                }
            )
    return pd.DataFrame(all_records) if all_records else None


def apply_threshold(df, threshold):
    windows = {}
    for _, r in df.iterrows():
        yr = int(r["window"])
        if yr not in windows:
            windows[yr] = {"trades": 0, "wins": 0, "pnl": 0.0}
        signal = 1 if r["prob_long"] > threshold else (-1 if r["prob_short"] > threshold else 0)
        if signal != 0:
            windows[yr]["trades"] += 1
            pnl = signal * r["return"]
            windows[yr]["pnl"] += pnl
            if pnl > 0:
                windows[yr]["wins"] += 1

    rows = []
    for yr in sorted(windows.keys()):
        s = windows[yr]
        wr = s["wins"] / s["trades"] if s["trades"] > 0 else 0
        exp = s["pnl"] / s["trades"] if s["trades"] > 0 else 0
        win_pnl = s["pnl"] if s["pnl"] > 0 else 0
        loss_abs = abs(s["pnl"]) if s["pnl"] < 0 else 0
        pf = min(win_pnl / loss_abs, 100.0) if loss_abs > 1e-10 else 0.0
        rows.append(
            {
                "window": yr,
                "n_trades": s["trades"],
                "win_rate": wr,
                "expectancy": exp,
                "profit_factor": pf,
                "total_return": s["pnl"],
            }
        )
    return pd.DataFrame(rows)


def sharp(ret):
    if len(ret) < 2 or ret.std() == 0:
        return 0.0
    return ret.mean() / ret.std() * np.sqrt(252)


print("Loading macro and reference...")
macro = compute_macro_derived(pd.read_parquet(os.path.join(PROJECT_ROOT, "data", "processed", "macro_factors.parquet")))
ref = fetch_history("SPY", years=10)

all_comparisons = []

for ticker in DASHBOARD_TICKERS:
    name = ticker.replace("=X", "").replace("=F", "").replace("^", "")
    print(f"\n{'=' * 55}\n{name} ({ticker})...")

    records = run_single_asset(ticker, macro, ref)
    if records is None or len(records) == 0:
        print("  SKIPPED")
        continue
    n_folds = records["window"].nunique()
    print(f"  {len(records)} signals, {n_folds} folds")

    r45 = apply_threshold(records, 0.45)
    r40 = apply_threshold(records, 0.40)

    t45, t40 = r45["n_trades"].sum(), r40["n_trades"].sum()
    r45v, r40v = r45["total_return"].sum(), r40["total_return"].sum()
    wr45 = (r45["n_trades"] * r45["win_rate"]).sum() / t45 if t45 else 0
    wr40 = (r40["n_trades"] * r40["win_rate"]).sum() / t40 if t40 else 0
    pf45, pf40 = r45["profit_factor"].median(), r40["profit_factor"].median()
    sh45, sh40 = sharp(r45.set_index("window")["total_return"]), sharp(r40.set_index("window")["total_return"])

    avg_tpf = r40["n_trades"].mean()
    min_tpf = r40["n_trades"].min()
    has_10 = (r40["n_trades"] >= 10).any()
    conf = "BACKTESTABLE" if (avg_tpf >= 10 and has_10) else ("DIRECTIONAL" if avg_tpf >= 5 else "MONITOR_LIVE")

    all_comparisons.append(
        {
            "ticker": name,
            "conf": conf,
            "t045": t45,
            "t040": t40,
            "dt": t40 - t45,
            "wr045": wr45,
            "wr040": wr40,
            "dwr": wr40 - wr45,
            "pf045": pf45,
            "pf040": pf40,
            "dpf": pf40 - pf45,
            "sh045": sh45,
            "sh040": sh40,
            "dsh": sh40 - sh45,
            "r045": r45v,
            "r040": r40v,
            "dr": r40v - r45v,
            "n_windows": n_folds,
            "avg_tpf": round(avg_tpf, 1),
            "min_tpf": min_tpf,
        }
    )

    print(f"  [{conf}] Trades: {t45}->{t40} (Δ{'+' if t40 > t45 else ''}{t40 - t45})")
    print(f"  WR: {wr45:.1%}->{wr40:.1%}  PF: {pf45:.2f}->{pf40:.2f}  Sharpe: {sh45:.3f}->{sh40:.3f}")
    print(f"  TotalR: {r45v:+.4f}->{r40v:+.4f} (Δ{r40v - r45v:+.4f})")

print()
print("=" * 110)
print("FINAL SUMMARY: THRESHOLD 0.45 vs 0.40")
print("=" * 110)
print(
    f"{'Asset':>8s}  {'Conf':>14s}  {'T045':>5s}  {'T040':>5s}  {'DT':>4s}  {'WR045':>6s}  {'WR040':>6s}  {'PF045':>6s}  {'PF040':>6s}  {'R045':>8s}  {'R040':>8s}  {'DR':>8s}"  # noqa: E501
)  # noqa: E501
print("-" * 110)
for c in all_comparisons:
    print(
        f"{c['ticker']:>8s}  {c['conf']:>14s}  {c['t045']:>5d}  {c['t040']:>5d}  {c['dt']:>+3d}  {c['wr045']:>5.1%}  {c['wr040']:>5.1%}  {c['pf045']:>5.2f}  {c['pf040']:>5.2f}  {c['r045']:>+7.4f}  {c['r040']:>+7.4f}  {c['dr']:>+7.4f}"  # noqa: E501
    )  # noqa: E501

adopt, keep, mix = [], [], []
for c in all_comparisons:
    nm = c["ticker"]
    if c["conf"] == "MONITOR_LIVE":
        print(f"  {nm}: MONITOR_LIVE ({c['avg_tpf']} avg tpf) — KEEP 0.45, deploy with monitoring")
        keep.append(c)
    elif c["conf"] == "DIRECTIONAL":
        if c["dr"] > 0 and c["dpf"] > -0.2:
            print(f"  {nm}: DIRECTIONAL, DR>0 — ADOPT 0.40")
            adopt.append(c)
        else:
            print(f"  {nm}: DIRECTIONAL, DR={c['dr']:+.4f} — KEEP 0.45")
            keep.append(c)
    else:  # BACKTESTABLE
        if c["dr"] > 0 and c["dpf"] > -0.2 and c["dwr"] > -0.05:
            print(f"  {nm}: BACKTESTABLE, strong — ADOPT 0.40")
            adopt.append(c)
        elif c["dr"] < 0 and c["dpf"] < -0.1:
            print(f"  {nm}: BACKTESTABLE, degrades — KEEP 0.45")
            keep.append(c)
        else:
            print(f"  {nm}: BACKTESTABLE, mixed — deploy w/ monitoring")
            mix.append(c)

# Proper print
print()
print("=" * 50)
print("RECOMMENDATIONS:")
print(f"  ADOPT 0.40: {len(adopt)} — {[c['ticker'] for c in adopt]}")
print(f"  KEEP 0.45:  {len(keep)} — {[c['ticker'] for c in keep]}")
print(f"  MIXED:      {len(mix)} — {[c['ticker'] for c in mix]}")

# Save
out = os.path.join(PROJECT_ROOT, "scripts", "data", "processed", "threshold_comparison.csv")
os.makedirs(os.path.dirname(out), exist_ok=True)
if all_comparisons:
    with open(out, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(all_comparisons[0].keys()))
        w.writeheader()
        w.writerows(all_comparisons)
    print(f"\nSaved to {out}")
