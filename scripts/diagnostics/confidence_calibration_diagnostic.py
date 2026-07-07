#!/usr/bin/env python3
"""Option A — reconstruct a direction-conditional confidence and re-bucket.

C-03 follow-up: the live 'confidence' is max(prob_long, prob_short), and in
the calibrated path prob_short is artificially set to 1 - cal_p_long, which
collides with prob_long on the high side. The original diagnostic on
walk-forward parquets (using max(p_long, 1-p_long)) shows flat-to-inverted
discrimination on the BUY side.

This script computes a *direction-conditional* confidence: when a BUY trade
was taken, confidence = P(label=1 | taken-BUY-prediction) using an
isotonic/matched stratifier on the model's raw p_long. We then re-bucket
and compare to the original (broken-projection) diagnostic.

Usage:
    PYTHONPATH=$PYTHONPATH:. python scripts/diagnostics/confidence_calibration_diagnostic.py
    PYTHONPATH=$PYTHONPATH:. python scripts/diagnostics/confidence_calibration_diagnostic.py --tag retrained
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd
from sklearn.isotonic import IsotonicRegression

ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT))

BASE = ROOT / "scripts" / "walkforward"
OUT_DIR = ROOT / "data" / "processed"

SELL_ONLY = {"CADCHF", "NZDCHF", "EURAUD"}


def load_all_tag(tag: str) -> pd.DataFrame:
    files = sorted(BASE.glob(f"*_wf_signals_{tag}.parquet"))
    if not files:
        raise FileNotFoundError(f"No *_wf_signals_{tag}.parquet files in {BASE}")
    print(f"Loading {len(files)} signal parquets (tag={tag})")
    dfs = []
    for f in files:
        df = pd.read_parquet(f)
        aname = f.name.split("_wf_signals")[0]
        df["asset_name"] = aname
        df["in_sell_only"] = aname in SELL_ONLY
        dfs.append(df)
    return pd.concat(dfs, ignore_index=True)


def fit_calibrators(data: pd.DataFrame) -> dict:
    """Per-asset isotonic regression; falls back to a global isotonic for
    assets with too few samples (<60).
    """
    import warnings

    out = {}
    p_long_all = data["p_long"].values
    label_all = data["label"].astype(int).values
    try:
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            ir_global = IsotonicRegression(out_of_bounds="clip", y_min=0.01, y_max=0.99)
            ir_global.fit(p_long_all, label_all)
    except (ValueError, TypeError):
        ir_global = None

    for aname, sub in data.groupby("asset_name"):
        if len(sub) >= 60:
            try:
                with warnings.catch_warnings():
                    warnings.simplefilter("ignore")
                    ir = IsotonicRegression(out_of_bounds="clip", y_min=0.01, y_max=0.99)
                    ir.fit(sub["p_long"].values, sub["label"].astype(int).values)
                out[aname] = ("per_asset", ir)
                continue
            except (ValueError, TypeError):
                pass
        out[aname] = ("global", ir_global)
    return out


def predict_per_dir_confidence(data: pd.DataFrame, calibrators: dict) -> np.ndarray:
    """For each directional trade, give a confidence in [0,1] that this
    *trade* wins:
      BUY  → P(label=1 | p_long)
      SELL → P(label=1 | mirror of p_long under the implicit 2-class
             symmetry used by the live confidence metric, 1 - p_long)
    """
    conf = np.full(len(data), np.nan)
    for aname, sub in data.groupby("asset_name"):
        kind, ir = calibrators.get(aname, ("global", None))
        if ir is None:
            continue
        sig = sub["signal"].values
        is_buy = sig == 1
        is_sell = sig == -1
        p_long = sub["p_long"].values
        pos = np.arange(len(sub))
        c_buy = ir.predict(p_long[is_buy]) if is_buy.any() else np.array([])
        c_sell = ir.predict(1.0 - p_long[is_sell]) if is_sell.any() else np.array([])
        conf[pos[is_buy]] = c_buy
        conf[pos[is_sell]] = c_sell
    return conf


def bucket_table(direction: pd.DataFrame, conf_col: str, label_col: str, n_buckets: int = 10) -> pd.DataFrame:
    bucket = pd.qcut(direction[conf_col], q=n_buckets, duplicates="drop", labels=False)
    g = direction.groupby(bucket).agg(
        n=(label_col, "size"),
        wr=(label_col, "mean"),
        avg_conf=(conf_col, "mean"),
    )
    return g


def spearman_corr(df: pd.DataFrame, conf_col: str, wr_col: str = "wr") -> tuple[float, float]:
    from scipy.stats import spearmanr

    r, p = spearmanr(df[conf_col], df[wr_col])
    return r, p


def main(tag: str):
    data = load_all_tag(tag)
    print(f"\nTotal rows: {len(data)}")
    print(data["signal"].map({1: "BUY", 0: "FLAT", -1: "SELL"}).value_counts().rename("count"))

    # ── Step A1: the broken-rule diagnostic (replicating original analysis) ──
    directional = data[data["signal"] != 0].copy()
    print(f"\nDirectional trades: {len(directional)}")

    directional["broken_conf"] = directional.apply(
        lambda r: r["p_long"] if r["signal"] == 1 else (1.0 - r["p_long"]),
        axis=1,
    )

    print("\n=== A1: Broken-rule diagnostic (max(p_long, 1-p_long), per-direction) ===")
    a1 = bucket_table(directional, "broken_conf", "label")
    print(a1.to_string())

    # ── Step A2: per-asset isotonic calibrator (with global fallback) ──
    print("\n=== A2: Per-asset isotonic calibration, direction-conditional confidence ===")
    calibrators = fit_calibrators(data)
    n_per_asset = sum(1 for v in calibrators.values() if v[0] == "per_asset")
    n_global = sum(1 for v in calibrators.values() if v[0] == "global")
    print(f"Calibrators: {n_per_asset} per-asset, {n_global} global fallback")

    directional["cal_conf"] = predict_per_dir_confidence(directional, calibrators)
    calibrated = directional.dropna(subset=["cal_conf"]).copy()
    print(f"Trades with calibrated confidence: {len(calibrated)}")

    a2 = bucket_table(calibrated, "cal_conf", "label", n_buckets=5)
    print(a2.to_string())

    # ── Step A2b: GLOBAL isotonic only (apples-to-apples to production BinnedCalibrator) ──
    print("\n=== A2b: GLOBAL isotonic only (production-style BinnedCalibrator analog) ===")
    import warnings

    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        ir_g = IsotonicRegression(out_of_bounds="clip", y_min=0.01, y_max=0.99)
        ir_g.fit(data["p_long"].values, data["label"].astype(int).values)
    directional["global_cal_conf"] = np.where(
        directional["signal"] == 1,
        ir_g.predict(directional["p_long"].values),
        ir_g.predict(1.0 - directional["p_long"].values),
    )
    a2b = bucket_table(directional, "global_cal_conf", "label", n_buckets=10)
    print(a2b.to_string())

    # ── Step A2c: calibration DIAGNOSTIC on probabilities × outcomes — fixed-bucket empirical win rate
    print("\n=== A2c: Reliability / per-asset empirical WR over the calibrated P(label=1|p_long) — BUY only ===")
    directional_cal_buy = directional[directional["signal"] == 1].copy()
    directional_cal_buy["cal_p"] = ir_g.predict(directional_cal_buy["p_long"].values)
    for lo, hi in [(0.0, 0.20), (0.20, 0.40), (0.40, 0.55), (0.55, 0.70), (0.70, 0.85), (0.85, 1.01)]:
        sub = directional_cal_buy[(directional_cal_buy["cal_p"] >= lo) & (directional_cal_buy["cal_p"] < hi)]
        if len(sub) >= 5:
            print(f"  cal_p ∈ [{lo:.2f},{hi:.2f}): n={len(sub):4d} WR={sub['label'].mean():.3f}")

    print("\n=== A2d: Reliability — SELL only (calibrated P(label=1|mirror) ) ===")
    directional_cal_sell = directional[directional["signal"] == -1].copy()
    directional_cal_sell["cal_p"] = ir_g.predict(1.0 - directional_cal_sell["p_long"].values)
    for lo, hi in [(0.0, 0.20), (0.20, 0.40), (0.40, 0.55), (0.55, 0.70), (0.70, 0.85), (0.85, 1.01)]:
        sub = directional_cal_sell[(directional_cal_sell["cal_p"] >= lo) & (directional_cal_sell["cal_p"] < hi)]
        if len(sub) >= 5:
            print(f"  cal_p ∈ [{lo:.2f},{hi:.2f}): n={len(sub):4d} WR={sub['label'].mean():.3f}")

    # ── Step A3: per-asset sanity ──
    print("\n=== A3: Per-asset WR vs mean BROKEN confidence (Spearman) ===")
    asset_perf_broken = (
        directional.groupby("asset_name")
        .agg(
            n=("label", "size"),
            wr=("label", "mean"),
            avg_broken=("broken_conf", "mean"),
        )
        .reset_index()
    )
    rb, pb = spearman_corr(asset_perf_broken, "avg_broken")
    print(f"  r={rb:.3f}, p={pb:.3f} (broken-rule confidence)")
    print(asset_perf_broken.sort_values("avg_broken", ascending=False).head(10).to_string(index=False))

    print("\n=== A4: Per-asset WR vs mean CALIBRATED confidence (Spearman) ===")
    asset_perf_cal = (
        calibrated.groupby("asset_name")
        .agg(
            n=("label", "size"),
            wr=("label", "mean"),
            avg_cal=("cal_conf", "mean"),
        )
        .reset_index()
    )
    rc, pc = spearman_corr(asset_perf_cal, "avg_cal")
    print(f"  r={rc:.3f}, p={pc:.3f} (calibrated, direction-conditional confidence)")
    print(asset_perf_cal.sort_values("avg_cal", ascending=False).head(10).to_string(index=False))

    print("\n=== A4b: Per-asset WR vs mean GLOBAL-CALIBRATED confidence (Spearman) ===")
    asset_perf_g = (
        directional.groupby("asset_name")
        .agg(
            n=("label", "size"),
            wr=("label", "mean"),
            avg_global_cal=("global_cal_conf", "mean"),
        )
        .reset_index()
    )
    rg, pg = spearman_corr(asset_perf_g, "avg_global_cal")
    print(f"  r={rg:.3f}, p={pg:.3f} (global isotonic, direction-conditional)")
    print(asset_perf_g.sort_values("avg_global_cal", ascending=False).head(10).to_string(index=False))

    # ── Step A5: side-by-side bucket tables ──
    print("\n=== A5: Side-by-side bucket comparison (broken vs per-asset-cal vs global-cal) ===")
    n_max = max(len(a1), len(a2), len(a2b))
    for i in range(n_max):
        line = f"  i={i}: "
        if i < len(a1):
            b = a1.iloc[i]
            line += f"B n={int(b['n']):4d} conf={b['avg_conf']:.3f} WR={b['wr']:.3f}  |  "
        else:
            line += "B                              |  "
        if i < len(a2):
            c = a2.iloc[i]
            line += f"PA n={int(c['n']):4d} conf={c['avg_conf']:.3f} WR={c['wr']:.3f}  |  "
        else:
            line += "PA                              |  "
        if i < len(a2b):
            g = a2b.iloc[i]
            line += f"G n={int(g['n']):4d} conf={g['avg_conf']:.3f} WR={g['wr']:.3f}"
        print(line)

    # ── Step A6: BUY-side and SELL-side separately ──
    print("\n=== A6: BUY trades only — broken vs per-asset-cal vs global-cal ===")
    buy = directional[directional["signal"] == 1].copy()
    buy_ck = buy.dropna(subset=["cal_conf"])
    if len(buy) > 0:
        print("  broken (10-bin):")
        print(bucket_table(buy, "broken_conf", "label", n_buckets=10).to_string())
    if len(buy_ck) > 0:
        pa = bucket_table(buy_ck, "cal_conf", "label", n_buckets=5)
        gb = bucket_table(buy, "global_cal_conf", "label", n_buckets=5)
        n = max(len(pa), len(gb))
        print("  per-asset-cal (5-bin):       global-cal (5-bin):")
        for i in range(n):
            line = "    "
            if i < len(pa):
                c = pa.iloc[i]
                line += f"PA[{i}] n={int(c['n']):4d} conf={c['avg_conf']:.3f} WR={c['wr']:.3f}    "
            else:
                line += "                                  "
            if i < len(gb):
                g = gb.iloc[i]
                line += f"G[{i}] n={int(g['n']):4d} conf={g['avg_conf']:.3f} WR={g['wr']:.3f}"
            print(line)

    print("\n=== A7: SELL trades only — broken vs per-asset-cal vs global-cal ===")
    sell = directional[directional["signal"] == -1].copy()
    sell_ck = sell.dropna(subset=["cal_conf"])
    if len(sell) > 0:
        print("  broken (10-bin):")
        print(bucket_table(sell, "broken_conf", "label", n_buckets=10).to_string())
    if len(sell_ck) > 0:
        pa = bucket_table(sell_ck, "cal_conf", "label", n_buckets=5)
        gb = bucket_table(sell, "global_cal_conf", "label", n_buckets=5)
        n = max(len(pa), len(gb))
        print("  per-asset-cal (5-bin):       global-cal (5-bin):")
        for i in range(n):
            line = "    "
            if i < len(pa):
                c = pa.iloc[i]
                line += f"PA[{i}] n={int(c['n']):4d} conf={c['avg_conf']:.3f} WR={c['wr']:.3f}    "
            else:
                line += "                                  "
            if i < len(gb):
                g = gb.iloc[i]
                line += f"G[{i}] n={int(g['n']):4d} conf={g['avg_conf']:.3f} WR={g['wr']:.3f}"
            print(line)

    # ── Step A8: top-x% filter — does trading the most-confident X% beat trading the least-confident X%? ──
    print("\n=== A8: Top-X% filter (broken-rule confidence) — directional trades ===")
    directional_sorted = directional.sort_values("broken_conf", ascending=False).reset_index(drop=True)
    n_dir = len(directional_sorted)
    cuts = [0.10, 0.25, 0.50, 0.75, 1.00]
    print(f"  {'top%':<8} {'n':<6} {'avg_conf':<10} {'win_rate':<10} {'summary':<60}")
    for c in cuts:
        sub = directional_sorted.head(int(n_dir * c))
        summary = ""
        if c < 1.0 and c > 0:
            summary = f"vs bottom {1.0 - c:.0%}"
        print(f"  {c:<8.0%} {len(sub):<6} {sub['broken_conf'].mean():<10.3f} {sub['label'].mean():<10.3f} {summary}")
    # Compare top vs bottom
    for c in [0.10, 0.25, 0.50, 0.75]:
        top = directional_sorted.head(int(n_dir * c))
        bot = directional_sorted.tail(int(n_dir * c))
        n_common = min(len(top), len(bot))
        if n_common == 0:
            continue
        from scipy.stats import mannwhitneyu

        u, p = mannwhitneyu(top["label"].values, bot["label"].values, alternative="greater")
        print(f"  Mann-Whitney top {c:.0%} vs bottom {c:.0%}: U={u}, p(WR>)= {p:.3g} (n={n_common})")

    print("\n=== A9: Top-X% filter (broken-rule confidence) — BUY only ===")
    buy_sorted = (
        directional[directional["signal"] == 1].sort_values("broken_conf", ascending=False).reset_index(drop=True)
    )
    n_buy = len(buy_sorted)
    print(f"  {'top%':<8} {'n':<6} {'avg_conf':<10} {'win_rate':<10}")
    for c in [0.10, 0.25, 0.50, 0.75, 1.00]:
        sub = buy_sorted.head(int(n_buy * c))
        print(f"  {c:<8.0%} {len(sub):<6} {sub['broken_conf'].mean():<10.3f} {sub['label'].mean():<10.3f}")

    print("\n=== A10: Top-X% filter (broken-rule confidence) — SELL only ===")
    sell_sorted = (
        directional[directional["signal"] == -1].sort_values("broken_conf", ascending=False).reset_index(drop=True)
    )
    n_sell = len(sell_sorted)
    print(f"  {'top%':<8} {'n':<6} {'avg_conf':<10} {'win_rate':<10}")
    for c in [0.10, 0.25, 0.50, 0.75, 1.00]:
        sub = sell_sorted.head(int(n_sell * c))
        print(f"  {c:<8.0%} {len(sub):<6} {sub['broken_conf'].mean():<10.3f} {sub['label'].mean():<10.3f}")

    # ── Step A11: POST-FIX direction-conditional confidence (live path) ──
    # After the calibration fix, proba[:, 2] = cal_p_long and proba[:, 0]
    # is preserved from the 3-class softmax. The live confidence rule
    # ``max(prob_long, prob_short)`` therefore picks the chosen-direction
    # probability, which is the *direction-conditional* P(win|signal).
    # Bucketing the trades by this metric should resolve the C-03 inversion.
    print("\n=== A11: POST-FIX direction-conditional confidence (live path) ===")
    directional["live_conf"] = np.where(
        directional["signal"] == 1,
        directional["p_long"],
        1.0 - directional["p_long"],
    )
    a11 = bucket_table(directional, "live_conf", "label", n_buckets=10)
    print("  all directional trades (per direction, column per chosen-side prob):")
    print(a11.to_string())

    print("\n=== A12: POST-FIX Top-X% filter (live_conf, BUY only) ===")
    buy_live = directional[directional["signal"] == 1].sort_values("live_conf", ascending=False).reset_index(drop=True)
    n_buy = len(buy_live)
    print(f"  {'top%':<8} {'n':<6} {'avg_conf':<10} {'win_rate':<10}")
    for c in [0.10, 0.25, 0.50, 0.75, 1.00]:
        sub = buy_live.head(int(n_buy * c))
        print(f"  {c:<8.0%} {len(sub):<6} {sub['live_conf'].mean():<10.3f} {sub['label'].mean():<10.3f}")
    if n_buy >= 20:
        from scipy.stats import mannwhitneyu

        u, p = mannwhitneyu(buy_live.head(int(n_buy * 0.10))["label"].values, buy_live.tail(int(n_buy * 0.10))["label"].values, alternative="greater")
        print(f"  Mann-Whitney top 10% vs bottom 10% (alternative=greater): U={u}, p={p:.3g}")

    print("\n=== A13: POST-FIX Top-X% filter (live_conf, SELL only) ===")
    sell_live = directional[directional["signal"] == -1].sort_values("live_conf", ascending=False).reset_index(drop=True)
    n_sell = len(sell_live)
    print(f"  {'top%':<8} {'n':<6} {'avg_conf':<10} {'win_rate':<10}")
    for c in [0.10, 0.25, 0.50, 0.75, 1.00]:
        sub = sell_live.head(int(n_sell * c))
        print(f"  {c:<8.0%} {len(sub):<6} {sub['live_conf'].mean():<10.3f} {sub['label'].mean():<10.3f}")

    print("\n=== A14: POST-FIX per-asset Spearman (live_conf vs WR) ===")
    asset_perf_live = (
        directional.groupby("asset_name")
        .agg(
            n=("label", "size"),
            wr=("label", "mean"),
            avg_live=("live_conf", "mean"),
        )
        .reset_index()
    )
    rl, pl = spearman_corr(asset_perf_live, "avg_live")
    print(f"  r={rl:.3f}, p={pl:.3f} (post-fix live_conf)")
    print(asset_perf_live.sort_values("avg_live", ascending=False).head(10).to_string(index=False))

    # ── A15: Proof-of-concept — does a richer meta-labeling model discriminate OOS? ──
    # Train a quick meta classifier on (p_long, p_short) → label for BUY trades only.
    # This is just to gauge whether Option C work would be fruitful if we have
    # the right feature set; the live meta-label was not trained with these.
    print("\n=== A15: Quick meta-labeling PoC (BUY only, simple features) ===")
    print("    NOTE: This is a proof-of-concept only. The production meta-label")
    print("    would need additional features (vol_regime, spread_bps, etc.) that")
    print("    are not currently captured in feature vectors.")
    try:
        from sklearn.metrics import brier_score_loss, roc_auc_score

        buy_meta = directional[directional["signal"] == 1].copy()
        n_meta = len(buy_meta)
        if n_meta < 50:
            print("    Insufficient BUY trades for meta-labeling PoC.")
        else:
            X = buy_meta[["p_long"]].values
            y = buy_meta["label"].astype(int).values
            n_val = max(int(n_meta * 0.2), 25)
            X_tr, X_va = X[:-n_val], X[-n_val:]
            y_tr, y_va = y[:-n_val], y[-n_val:]
            from xgboost import XGBClassifier
            model_m = XGBClassifier(n_estimators=60, max_depth=2, learning_rate=0.05, random_state=42, verbosity=0)
            model_m.fit(X_tr, y_tr, eval_set=[(X_va, y_va)], verbose=False)
            p_tr = model_m.predict_proba(X_tr)[:, 1]
            p_va = model_m.predict_proba(X_va)[:, 1]
            auc_tr = roc_auc_score(y_tr, p_tr)
            auc_va = roc_auc_score(y_va, p_va)
            brier_tr = brier_score_loss(y_tr, p_tr)
            brier_va = brier_score_loss(y_va, p_va)
            print(f"    Total BUY trades: {n_meta}, training: {len(X_tr)}, OOS: {len(X_va)}")
            print(f"    AUC   train={auc_tr:.3f}  OOS={auc_va:.3f}")
            print(f"    Brier train={brier_tr:.3f}  OOS={brier_va:.3f}")
            print(f"    OOS WR={y_va.mean():.3f}; base-rate Brier={y_va.mean()*(1-y_va.mean()):.3f}")
            print()
            # Bucket OOS predictions
            df_va = pd.DataFrame({"meta": p_va, "y": y_va})
            df_va["bucket"] = pd.qcut(df_va["meta"], q=10, duplicates="drop", labels=False)
            gb = df_va.groupby("bucket").agg(n=("y","size"), wr=("y","mean"), avg_meta=("meta","mean"))
            print(f"    Out-of-sample discretization:")
            print(gb.to_string())
    except Exception as exc:
        print(f"    Skipped due to: {exc}")

    # ── Save JSON for archival ──
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    out = {
        "tag": tag,
        "n_dir_trades": int(len(directional)),
        "n_calibrated_trades": int(len(calibrated)),
        "broken_buckets": a1.reset_index().to_dict(orient="records"),
        "pa_cal_buckets": a2.reset_index().to_dict(orient="records"),
        "global_cal_buckets": a2b.reset_index().to_dict(orient="records"),
        "post_fix_live_buckets": a11.reset_index().to_dict(orient="records"),
        "asset_perf_broken_spearman": {"r": float(rb), "p": float(pb)},
        "asset_perf_pa_cal_spearman": {"r": float(rc), "p": float(pc)},
        "asset_perf_global_cal_spearman": {"r": float(rg), "p": float(pg)},
        "asset_perf_live_spearman": {"r": float(rl), "p": float(pl)},
    }
    out_path = OUT_DIR / f"c03_confidence_diagnostic_{tag}.json"
    with open(out_path, "w") as f:
        json.dump(out, f, indent=2, default=str)
    print(f"\nSaved: {out_path}")

    return out


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--tag", default="retrained")
    args = ap.parse_args()
    main(args.tag)
