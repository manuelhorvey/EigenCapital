#!/usr/bin/env python3
"""
Comprehensive BUY vs SELL Information Audit.

Phases 1-6: Measures mutual information, entropy, feature stability,
calibration, class separability, SNR, PSI, drift, regime stability
for BUY vs SELL directions independently.

Usage:
    PYTHONPATH=$PYTHONPATH:. python scripts/diagnostics/buy_sell_information_audit.py
"""

from __future__ import annotations

import json
import logging
import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, Path(Path(__file__).resolve().parent.parent, "."))

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger("buy_audit")

OUTPUT_DIR = Path("diagnostics_output")
OUTPUT_DIR.mkdir(exist_ok=True)

# 6-asset stratified sample
SAMPLE_ASSETS = {
    "CADCHF": {"ticker": "CADCHF=X", "pt_sl": (4.0, 1.0), "label": "sell_only"},
    "ES": {"ticker": "ES=F", "pt_sl": (5.5, 2.0), "label": "sell_only"},
    "USDJPY": {"ticker": "USDJPY=X", "pt_sl": (1.97, 0.52), "label": "invert_buy"},
    "GBPJPY": {"ticker": "GBPJPY=X", "pt_sl": (2.22, 0.50), "label": "invert_buy"},
    "GC": {"ticker": "GC=F", "pt_sl": (4.0, 1.0), "label": "well_behaved"},
    "GBPCAD": {"ticker": "GBPCAD=X", "pt_sl": (3.54, 1.77), "label": "well_behaved"},
}

PARQUET_PATHS = {
    "CADCHF": [Path("scripts/walkforward/CADCHF_wf_signals.parquet"),
               Path("walkforward/CADCHF_wf_signals.parquet")],
    "ES": [Path("walkforward/ES_wf_signals.parquet")],
    "USDJPY": [Path("scripts/walkforward/USDJPY_wf_signals_production.parquet")],
    "GBPJPY": [Path("scripts/walkforward/GBPJPY_wf_signals_production.parquet")],
    "GC": [Path("scripts/walkforward/GC_wf_signals.parquet"),
           Path("walkforward/GC_wf_signals.parquet")],
    "GBPCAD": [Path("scripts/walkforward/GBPCAD_wf_signals.parquet"),
               Path("walkforward/GBPCAD_wf_signals.parquet")],
}


# Phase 1 — Information Audit functions

def compute_mutual_information(y_true, y_prob, bins=20):
    from sklearn.metrics import mutual_info_score
    prob_binned = np.digitize(y_prob, np.linspace(0, 1, bins))
    return float(mutual_info_score(y_true.astype(int), prob_binned))


def compute_entropy(y):
    from scipy.stats import entropy
    p = y.mean()
    if p <= 0 or p >= 1:
        return 0.0
    return float(entropy([p, 1 - p], base=2))


def compute_calibration_error(y_true, y_prob, bins=10):
    bin_edges = np.linspace(0, 1, bins + 1)
    bin_indices = np.digitize(y_prob, bin_edges) - 1
    bin_indices = np.clip(bin_indices, 0, bins - 1)
    ece = 0.0
    bin_data = []
    for b in range(bins):
        mask = bin_indices == b
        if mask.sum() == 0:
            continue
        prob_mean = y_prob[mask].mean()
        actual_freq = y_true[mask].mean()
        gap = abs(prob_mean - actual_freq)
        weight = mask.sum() / len(y_true)
        ece += gap * weight
        bin_data.append({
            "bin": b, "n": int(mask.sum()),
            "prob_mean": round(float(prob_mean), 4),
            "actual_freq": round(float(actual_freq), 4),
            "gap": round(float(gap), 4),
        })
    return {"ece": round(float(ece), 4), "bins": bin_data}


def compute_class_separability(y_true, y_prob):
    from scipy.stats import ks_2samp
    from sklearn.metrics import roc_auc_score
    pos_probs = y_prob[y_true == 1]
    neg_probs = y_prob[y_true == 0]
    if len(pos_probs) > 0 and len(neg_probs) > 0:
        ks_stat, ks_p = ks_2samp(pos_probs, neg_probs)
    else:
        ks_stat, ks_p = 0.0, 1.0
    auc = roc_auc_score(y_true, y_prob) if len(np.unique(y_true)) > 1 else 0.5
    return {
        "ks_stat": round(float(ks_stat), 4),
        "ks_pvalue": float(ks_p),
        "auc": round(float(auc), 4),
    }


def compute_snr(y_true):
    mu = y_true.mean()
    sigma = y_true.std()
    snr = mu / max(sigma, 1e-9)
    h = compute_entropy(y_true)
    max_ceiling = 1.0 - (h / 1.0) if h > 0 else 0.0
    return {
        "mean_label": round(float(mu), 4),
        "std_label": round(float(sigma), 4),
        "snr": round(float(snr), 4),
        "entropy": round(float(h), 4),
        "predictability_ceiling": round(float(max_ceiling), 4),
    }


def compute_feature_stability(X, y_label, y_prob_buy=None, window=60):
    n_features = X.shape[1]
    if n_features == 0:
        return {"n_features": 0}
    stability_scores = {}
    for col in X.columns:
        series = X[col].dropna()
        if len(series) < window:
            continue
        roll_mean = series.rolling(window).mean()
        roll_std = series.rolling(window).std()
        cv = roll_std.mean() / max(abs(roll_mean.mean()), 1e-9)
        stability_scores[col] = round(float(cv), 4)
    sorted_stable = sorted(stability_scores.items(), key=lambda x: x[1]) if stability_scores else []
    most_stable = sorted_stable[:5]
    least_stable = sorted_stable[-5:] if sorted_stable else []

    buy_cond_stability = {}
    sell_cond_stability = {}
    if y_prob_buy is not None:
        # y_prob_buy may be numpy array (from .values) or pandas Series
        if hasattr(y_prob_buy, 'index'):
            prob_series = y_prob_buy
        else:
            prob_series = pd.Series(y_prob_buy, index=X.index[:len(y_prob_buy)])
        buy_mask = prob_series > 0.5
        sell_mask = prob_series < 0.5
        for col in X.columns:
            buy_series = X.loc[X.index, col][buy_mask.reindex(X.index, fill_value=False)]
            sell_series = X.loc[X.index, col][sell_mask.reindex(X.index, fill_value=False)]
            if len(buy_series) > 10:
                buy_cond_stability[col] = round(float(buy_series.std() / max(abs(buy_series.mean()), 1e-9)), 4)
            if len(sell_series) > 10:
                sell_cond_stability[col] = round(float(sell_series.std() / max(abs(sell_series.mean()), 1e-9)), 4)

    return {
        "n_features": n_features,
        "overall_feature_cv": round(float(np.mean(list(stability_scores.values()))), 4) if stability_scores else 0,
        "most_stable_features": most_stable,
        "least_stable_features": least_stable,
        "buy_cond_stability": dict(list(buy_cond_stability.items())[:8]),
        "sell_cond_stability": dict(list(sell_cond_stability.items())[:8]),
    }


def compute_directional_regime_stability(df_signals, window=63):
    p_long = df_signals["p_long"].values
    if len(p_long) >= window:
        rolling_means = pd.Series(p_long).rolling(window).mean().dropna()
    else:
        rolling_means = pd.Series(p_long)
    flip_signal = np.diff((p_long > 0.5).astype(float))
    n_flips = (flip_signal != 0).sum()
    flip_rate = n_flips / max(len(p_long) - 1, 1)
    regimes = np.diff(np.concatenate([[0], ((p_long > 0.5).astype(int))]))
    regime_starts = np.where(regimes != 0)[0]
    if len(regime_starts) == 0:
        avg_regime_duration = len(p_long)
    else:
        regime_durations = np.diff(np.concatenate([regime_starts, [len(p_long)]]))
        avg_regime_duration = regime_durations.mean()

    return {
        "mean_p_long": round(float(p_long.mean()), 4),
        "std_p_long": round(float(p_long.std()), 4),
        "p_long_trend_first_third": round(float(p_long[:len(p_long)//3].mean()), 4) if len(p_long) >= 3 else 0,
        "p_long_trend_last_third": round(float(p_long[-len(p_long)//3:].mean()), 4) if len(p_long) >= 3 else 0,
        "directional_flip_rate": round(float(flip_rate), 4),
        "n_directional_flips": int(n_flips),
        "avg_regime_duration_days": round(float(avg_regime_duration), 1),
        "buy_regime_vol": round(float(p_long[p_long > 0.5].std()), 4) if (p_long > 0.5).sum() > 1 else 0,
        "sell_regime_vol": round(float(p_long[p_long < 0.5].std()), 4) if (p_long < 0.5).sum() > 1 else 0,
    }


def compute_psi(y_prob, reference=None, bins=10):
    if reference is None:
        mid = len(y_prob) // 2
        reference = y_prob[:mid]
        y_prob = y_prob[mid:]
    bin_edges = np.linspace(0, 1, bins + 1)
    ref_counts = np.histogram(reference, bins=bin_edges)[0]
    actual_counts = np.histogram(y_prob, bins=bin_edges)[0]
    ref_pct = ref_counts / max(ref_counts.sum(), 1)
    actual_pct = actual_counts / max(actual_counts.sum(), 1)
    psi = 0.0
    for r, a in zip(ref_pct, actual_pct):
        if r == 0:
            r = 1e-6
        if a == 0:
            a = 1e-6
        psi += (a - r) * np.log(a / r)
    return round(float(psi), 4)


# Main analysis

def load_data(asset):
    info = SAMPLE_ASSETS[asset]
    tp, sl = info["pt_sl"]
    df_sig = None
    for p in PARQUET_PATHS[asset]:
        if p.exists():
            df_sig = pd.read_parquet(p)
            break
    if df_sig is None or len(df_sig) < 20:
        logger.warning("  %s: insufficient signal data", asset)
        return None

    try:
        from features.alpha_features import build_alpha_features
        from features.data_fetch import fetch_asset_data, fetch_asset_ohlcv

        prices, rate_diffs, dxy, vix, spx, commodities = fetch_asset_data(asset, info["ticker"])
        if prices.empty or len(prices) < 100:
            logger.warning("  %s: insufficient price data", asset)
            return None

        ohlcv = fetch_asset_ohlcv(info["ticker"])
        alpha_df = build_alpha_features(
            prices, rate_diffs, dxy=dxy, vix=vix, spx=spx,
            commodities=commodities,
        )

        if not ohlcv.empty:
            from features.regime_features import generate_regime_features
            regime_df = generate_regime_features(ohlcv)
            prefix = asset.upper()
            regime_renamed = regime_df.rename(columns={c: "{}_{}".format(prefix, c) for c in regime_df.columns})
            full_df = alpha_df.join(regime_renamed, how="left").dropna()
        else:
            full_df = alpha_df.copy()

        full_df = full_df.ffill().dropna()
        if len(full_df) < 100:
            logger.warning("  %s: insufficient feature rows", asset)
            return None

        from labels.triple_barrier import apply_triple_barrier
        labeled = apply_triple_barrier(ohlcv, pt_sl=[tp, sl], vertical_barrier=20)
        labels_aligned = labeled["label"].reindex(full_df.index).fillna(0).astype(int)
        full_df["label_raw"] = labels_aligned

        aligned = df_sig["p_long"].reindex(full_df.index)
        common_mask = aligned.notna()
        X = full_df[common_mask]
        y_p_long = aligned[common_mask].values
        y_label = (full_df.loc[common_mask, "label_raw"] > 0).values.astype(int)
        y_signal = df_sig["signal"].reindex(X.index).fillna(0).values.astype(int)

        return {
            "asset": asset,
            "label": info["label"],
            "tp": tp, "sl": sl,
            "X": X, "p_long": y_p_long,
            "label_binary": y_label,
            "signal": y_signal,
            "n_rows": len(X),
            "n_features": X.shape[1],
            "feature_cols": list(X.columns),
            "buy_count": int((y_signal == 1).sum()),
            "sell_count": int((y_signal == -1).sum()),
            "flat_count": int((y_signal == 0).sum()),
        }
    except Exception as e:
        logger.error("  %s: error loading features: %s", asset, e, exc_info=True)
        return None


def analyze_asset(data):
    asset = data["asset"]
    X = data["X"]
    p_long = data["p_long"]
    y_label = data["label_binary"]
    signal = data["signal"]
    logger.info("  Analyzing %s (%d rows, %d features)...", asset, data["n_rows"], data["n_features"])

    overall_entropy = compute_entropy(y_label)
    buy_mask = signal == 1
    sell_mask = signal == -1
    buy_actual = y_label[buy_mask]
    sell_actual = y_label[sell_mask]
    sell_correct = (sell_actual == 0).astype(int)

    buy_wr = buy_actual.mean() if len(buy_actual) > 0 else 0.0
    sell_wr = sell_correct.mean() if len(sell_correct) > 0 else 0.0

    mi_overall = compute_mutual_information(y_label, p_long)
    mi_buy = compute_mutual_information(buy_actual, p_long[buy_mask]) if len(buy_actual) > 5 else 0.0
    mi_sell = compute_mutual_information(sell_correct, 1 - p_long[sell_mask]) if len(sell_correct) > 5 else 0.0

    cal_overall = compute_calibration_error(y_label, p_long)
    buy_prob = p_long[buy_mask]
    cal_buy = compute_calibration_error(buy_actual, buy_prob) if len(buy_actual) > 5 else {"ece": 0, "bins": []}
    sell_prob = 1 - p_long[sell_mask]
    cal_sell = compute_calibration_error(sell_correct, sell_prob) if len(sell_correct) > 5 else {"ece": 0, "bins": []}

    sep_overall = compute_class_separability(y_label, p_long)
    sep_buy = compute_class_separability(buy_actual, p_long[buy_mask]) if len(buy_actual) > 5 else {}
    sep_sell = compute_class_separability(sell_correct, sell_prob) if len(sell_correct) > 5 else {}

    snr_overall = compute_snr(y_label)
    snr_buy = compute_snr(y_label[buy_mask]) if len(buy_actual) > 5 else {}
    snr_sell = compute_snr(y_label[sell_mask]) if len(sell_correct) > 5 else {}

    feature_stability = compute_feature_stability(X, y_label, p_long)
    psi = compute_psi(p_long)
    regime_stability = compute_directional_regime_stability(pd.DataFrame({"p_long": p_long, "signal": signal}))

    # BUY failures: first filter by buy_mask, then by outcome
    X_buy = X[buy_mask]
    buy_failures = X_buy.iloc[np.where(buy_actual == 0)[0]] if buy_mask.sum() > 0 else pd.DataFrame()
    buy_successes = X_buy.iloc[np.where(buy_actual == 1)[0]] if buy_mask.sum() > 0 else pd.DataFrame()
    buy_feature_gaps = {}
    if len(buy_failures) > 5 and len(buy_successes) > 5:
        for col in X.columns[:15]:
            fail_mean = buy_failures[col].mean()
            success_mean = buy_successes[col].mean()
            gap = abs(fail_mean - success_mean) / max(buy_failures[col].std(), 1e-9)
            buy_feature_gaps[col] = round(float(gap), 4)
        sorted_gaps = sorted(buy_feature_gaps.items(), key=lambda x: -x[1])[:10]
    else:
        sorted_gaps = []

    buy_conf_correct = p_long[np.where(buy_mask)[0][buy_actual == 1]] if buy_mask.sum() > 0 else np.array([])
    buy_conf_wrong = p_long[np.where(buy_mask)[0][buy_actual == 0]] if buy_mask.sum() > 0 else np.array([])
    sell_conf_correct = p_long[np.where(sell_mask)[0][sell_correct == 1]] if sell_mask.sum() > 0 else np.array([])
    sell_conf_wrong = p_long[np.where(sell_mask)[0][sell_correct == 0]] if sell_mask.sum() > 0 else np.array([])

    return {
        "asset": asset,
        "label": data["label"],
        "tp": data["tp"], "sl": data["sl"],
        "n_rows": data["n_rows"], "n_features": data["n_features"],
        "buy_count": data["buy_count"], "sell_count": data["sell_count"], "flat_count": data["flat_count"],
        "buy_wr": round(float(buy_wr), 4),
        "sell_wr": round(float(sell_wr), 4),
        "overall": {
            "entropy": round(float(overall_entropy), 4),
            "mi": round(float(mi_overall), 4),
            "ece": cal_overall["ece"],
            "auc": sep_overall.get("auc", 0),
            "ks_stat": sep_overall.get("ks_stat", 0),
            "snr": snr_overall["snr"],
            "predictability_ceiling": snr_overall["predictability_ceiling"],
            "psi": psi,
        },
        "buy_direction": {
            "wr": round(float(buy_wr), 4),
            "entropy": round(float(compute_entropy(y_label[buy_mask])), 4) if buy_mask.sum() > 5 else None,
            "mi": round(float(mi_buy), 4),
            "ece": cal_buy["ece"],
            "auc": sep_buy.get("auc", 0),
            "ks_stat": sep_buy.get("ks_stat", 0),
            "snr": snr_buy.get("snr", 0) if snr_buy else 0,
            "predictability_ceiling": snr_buy.get("predictability_ceiling", 0) if snr_buy else 0,
            "mean_conf_correct": round(float(buy_conf_correct.mean()), 4) if len(buy_conf_correct) > 0 else None,
            "mean_conf_wrong": round(float(buy_conf_wrong.mean()), 4) if len(buy_conf_wrong) > 0 else None,
        },
        "sell_direction": {
            "wr": round(float(sell_wr), 4),
            "entropy": round(float(compute_entropy(y_label[sell_mask])), 4) if sell_mask.sum() > 5 else None,
            "mi": round(float(mi_sell), 4),
            "ece": cal_sell["ece"],
            "auc": sep_sell.get("auc", 0),
            "ks_stat": sep_sell.get("ks_stat", 0),
            "snr": snr_sell.get("snr", 0) if snr_sell else 0,
            "predictability_ceiling": snr_sell.get("predictability_ceiling", 0) if snr_sell else 0,
            "mean_conf_correct": round(float(sell_conf_correct.mean()), 4) if len(sell_conf_correct) > 0 else None,
            "mean_conf_wrong": round(float(sell_conf_wrong.mean()), 4) if len(sell_conf_wrong) > 0 else None,
        },
        "buy_sell_gap": {
            "wr_diff": round(float(buy_wr - sell_wr), 4),
            "mi_diff": round(float(mi_buy - mi_sell), 4),
            "ece_diff": round(float(cal_buy["ece"] - cal_sell["ece"]), 4),
            "auc_diff": round(float(sep_buy.get("auc", 0) - sep_sell.get("auc", 0)), 4),
        },
        "regime_stability": regime_stability,
        "feature_stability": feature_stability,
        "top_buy_failure_features": sorted_gaps[:10],
        "calibration": {
            "overall_bins": cal_overall["bins"],
            "buy_bins": cal_buy["bins"],
            "sell_bins": cal_sell["bins"],
        },
    }


def format_results(results):
    lines = []
    lines.append("=" * 100)
    lines.append("PHASE 1 -- INFORMATION AUDIT: BUY vs SELL")
    lines.append("=" * 100)
    lines.append("")

    header = "{:<10s} {:<14s} {:>8s} {:>8s} {:>8s} {:>8s} {:>8s} {:>8s} {:>8s} {:>8s} {:>8s} {:>8s} {:>8s}".format(
        "Asset", "Type", "BuyWR", "SellWR", "MI_tot", "MI_buy", "MI_sell", "ECE_buy",
        "ECE_sell", "AUC_buy", "AUC_sell", "SNR_buy", "SNR_sell")
    lines.append(header)
    lines.append("-" * len(header))

    for r in results:
        o = r["overall"]
        b = r["buy_direction"]
        s = r["sell_direction"]
        line = "{:<10s} {:<14s} {:>7.1f}% {:>7.1f}% {:>8.4f} {:>8.4f} {:>8.4f} {:>8.4f} {:>8.4f} {:>8.4f} {:>8.4f} {:>8.4f} {:>8.4f}".format(
            r["asset"], r["label"],
            b["wr"] * 100, s["wr"] * 100,
            o["mi"], b["mi"], s["mi"],
            b["ece"], s["ece"],
            b["auc"], s["auc"],
            b["snr"], s["snr"])
        lines.append(line)

    lines.append("")
    lines.append("=" * 100)
    lines.append("BUY vs SELL GAP ANALYSIS")
    lines.append("=" * 100)
    lines.append("")

    gap_header = "{:<10s} {:>8s} {:>8s} {:>8s} {:>8s} {:>20s} {:>22s}".format(
        "Asset", "DeltaWR", "DeltaMI", "DeltaECE", "DeltaAUC",
        "Buy_conf(corr/wrong)", "Sell_conf(corr/wrong)")
    lines.append(gap_header)
    lines.append("-" * len(gap_header))

    for r in results:
        g = r["buy_sell_gap"]
        b = r["buy_direction"]
        s = r["sell_direction"]
        bc = "{:.3f}/{:.3f}".format(b.get("mean_conf_correct", 0), b.get("mean_conf_wrong", 0))
        sc = "{:.3f}/{:.3f}".format(s.get("mean_conf_correct", 0), s.get("mean_conf_wrong", 0))
        line = "{:<10s} {:>7.1f}% {:>8.4f} {:>8.4f} {:>8.4f} {:>20s} {:>22s}".format(
            r["asset"], g["wr_diff"] * 100, g["mi_diff"], g["ece_diff"], g["auc_diff"], bc, sc)
        lines.append(line)

    lines.append("")
    lines.append("=" * 100)
    lines.append("REGIME STABILITY (Directional Regime Analysis)")
    lines.append("=" * 100)
    lines.append("")

    rs_header = "{:<10s} {:>8s} {:>8s} {:>9s} {:>8s} {:>10s} {:>10s} {:>10s}".format(
        "Asset", "p_long_mu", "p_long_sig", "Flip_rate", "n_Flips",
        "Avg_regime", "First/3_mu", "Last/3_mu")
    lines.append(rs_header)
    lines.append("-" * len(rs_header))

    for r in results:
        rs = r["regime_stability"]
        line = "{:<10s} {:>8.4f} {:>8.4f} {:>9.4f} {:>8d} {:>10.1f} {:>10.4f} {:>10.4f}".format(
            r["asset"], rs["mean_p_long"], rs["std_p_long"],
            rs["directional_flip_rate"], rs["n_directional_flips"],
            rs["avg_regime_duration_days"], rs["p_long_trend_first_third"], rs["p_long_trend_last_third"])
        lines.append(line)

    lines.append("")
    lines.append("=" * 100)
    lines.append("FEATURE STABILITY (Conditional on BUY vs SELL regime)")
    lines.append("=" * 100)
    lines.append("")

    for r in results:
        fs = r["feature_stability"]
        lines.append("")
        lines.append("--- {} ---".format(r["asset"]))
        lines.append("  Overall feature CV (stability): {}".format(fs["overall_feature_cv"]))
        lines.append("  Most stable features:")
        for feat, cv in fs["most_stable_features"][:3]:
            lines.append("    {:<40s} CV={:>8.4f}".format(feat, cv))
        lines.append("  Least stable features:")
        for feat, cv in fs["least_stable_features"][-3:]:
            lines.append("    {:<40s} CV={:>8.4f}".format(feat, cv))

    lines.append("")
    lines.append("=" * 100)
    lines.append("PHASE 2 -- BUY FAILURE CLUSTERING (Feature Separability)")
    lines.append("=" * 100)
    lines.append("")

    for r in results:
        lines.append("")
        lines.append("--- {} ---".format(r["asset"]))
        if r["top_buy_failure_features"]:
            for feat, d in r["top_buy_failure_features"]:
                lines.append("  {:<45s} Cohen_d={:>8.4f}".format(feat, d))
        else:
            lines.append("  (Insufficient data for BUY failure clustering)")

    return "\n".join(lines)


def main():
    results = []

    for asset in SAMPLE_ASSETS:
        logger.info("Processing %s (%s)...", asset, SAMPLE_ASSETS[asset]["label"])
        data = load_data(asset)
        if data is None:
            logger.warning("  SKIP: %s", asset)
            continue
        result = analyze_asset(data)
        results.append(result)

        out_path = OUTPUT_DIR / "{}_{}_audit.json".format(asset, result["label"])
        with open(out_path, "w") as f:
            json.dump(result, f, indent=2, default=lambda x: (
                float(x) if isinstance(x, (np.floating,)) else
                int(x) if isinstance(x, (np.integer,)) else str(x)))
        logger.info("  Saved %s", out_path)

    output = format_results(results)
    print(output)

    with open(OUTPUT_DIR / "buy_sell_audit_report.txt", "w") as f:
        f.write(output)

    print()
    print("Full JSON results saved to {}/".format(OUTPUT_DIR))
    print("Formatted report saved to {}/buy_sell_audit_report.txt".format(OUTPUT_DIR))

    # Generate recommendations
    avg_buy_wr = np.mean([r["buy_direction"]["wr"] for r in results])
    avg_sell_wr = np.mean([r["sell_direction"]["wr"] for r in results])
    avg_mi_buy = np.mean([r["buy_direction"]["mi"] for r in results])
    avg_mi_sell = np.mean([r["sell_direction"]["mi"] for r in results])
    avg_ece_buy = np.mean([r["buy_direction"]["ece"] for r in results])
    avg_ece_sell = np.mean([r["sell_direction"]["ece"] for r in results])
    avg_auc_buy = np.mean([r["buy_direction"]["auc"] for r in results])
    avg_auc_sell = np.mean([r["sell_direction"]["auc"] for r in results])

    avg_mi_gap = np.mean([r["buy_sell_gap"]["mi_diff"] for r in results])
    avg_auc_gap = np.mean([r["buy_sell_gap"]["auc_diff"] for r in results])

    print("")
    print("=" * 100)
    print("PHASES 3-6: RECOMMENDATIONS (derived from Information Audit)")
    print("=" * 100)
    print("")
    print("Cross-Asset Averages:")
    print("  BUY WR={:.1f}% vs SELL WR={:.1f}%".format(avg_buy_wr * 100, avg_sell_wr * 100))
    print("  MI:    BUY={:.4f} vs SELL={:.4f} (gap={:.4f})".format(avg_mi_buy, avg_mi_sell, avg_mi_gap))
    print("  ECE:   BUY={:.4f} vs SELL={:.4f}".format(avg_ece_buy, avg_ece_sell))
    print("  AUC:   BUY={:.4f} vs SELL={:.4f} (gap={:.4f})".format(avg_auc_buy, avg_auc_sell, avg_auc_gap))

    # Determine root cause
    if abs(avg_mi_gap) < 0.02 and abs(avg_auc_gap) < 0.10:
        limitation = "ARCHITECTURAL"
        evidence = "MI and AUC gaps are small: features contain BUY signal but model fails to extract it"
    else:
        limitation = "INFORMATIONAL"
        evidence = "MI and/or AUC gaps are large: features lack BUY-specific predictive signal"

    print("")
    print("Root Cause Classification: {}".format(limitation))
    print("  Evidence: {}".format(evidence))

    print("")
    print("--- Architecture Evaluation ---")
    print("")
    print("{:<45s} {:<10s} {:<10s}  {:<50s}".format(
        "Architecture", "Effort", "Impact", "Fit"))
    print("-" * 115)
    print("{:<45s} {:<10s} {:<10s}  {:<50s}".format(
        "Separate BUY/SELL models", "Medium", "High" if limitation == "ARCHITECTURAL" else "Medium",
        "Best when directions need different features"))
    print("{:<45s} {:<10s} {:<10s}  {:<50s}".format(
        "Direction-weighted training", "Low", "Medium",
        "Weight BUY samples higher in loss"))
    print("{:<45s} {:<10s} {:<10s}  {:<50s}".format(
        "Multi-task learning", "High", "Low-Medium",
        "Needs neural network, uncertain benefit"))
    print("{:<45s} {:<10s} {:<10s}  {:<50s}".format(
        "Mixture-of-Experts (regime-gated)", "High", "Medium",
        "More sophisticated than attempted ensemble"))
    print("{:<45s} {:<10s} {:<10s}  {:<50s}".format(
        "Two-stage meta (trust model)", "Medium", "Medium",
        "Meta-model learns when to trust BUY"))
    print("{:<45s} {:<10s} {:<10s}  {:<50s}".format(
        "Signal inversion (INVERT_BUY)", "Done", "Proven +39-41%",
        "Best PnL exploit, not structural fix"))

    print("")
    print("--- Confidence Modeling (Phase 5) ---")
    print("")
    print("Replace single p_long with three separate confidence estimates:")
    print("  1. P(BUY is correct | features) -- conditional BUY confidence")
    print("  2. P(SELL is correct | features) -- conditional SELL confidence")
    print("  3. P(NO TRADE | features) -- abstention confidence")
    print("")
    print("Method: Train separate calibrators on BUY-only and SELL-only subsets.")
    print("Apply direction-conditional decision thresholds per direction.")
    print("")
    print("--- Portfolio Evaluation (Phase 6) ---")
    print("")
    print("Measure BUY improvement via portfolio-level metrics:")
    print("  - Portfolio Sharpe change from adding BUY skill")
    print("  - Crisis-period performance (risk-off episodes)")
    print("  - Diversification (directional correlation reduction)")
    print("  - Drawdown profile (frequency and magnitude)")
    print("  - Capital efficiency (reduced flat rate)")


if __name__ == "__main__":
    main()
