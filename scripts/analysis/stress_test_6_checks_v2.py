"""
Six checks v2 — fold-aware, with regime decomposition already complete.
Outputs final structured report for the deliverable.
"""

import json
import warnings
from pathlib import Path

import numpy as np
import pandas as pd
from scipy.stats import norm, spearmanr

warnings.filterwarnings("ignore")

OUTPUT_DIR = Path("data/processed")
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
WALKFORWARD_DIR = Path("scripts/walkforward")
TAG = "expanded_10yr"

ASSET_TP_SL = {
    "AUDJPY": (2.01, 0.52), "AUDUSD": (4.24, 1.41), "BTCUSD": (1.51, 0.58),
    "CADCHF": (4.0, 1.0), "CADJPY": (1.97, 0.52), "CHFJPY": (2.0, 0.5),
    "EURAUD": (1.77, 0.54), "EURCAD": (2.12, 0.71), "EURCHF": (3.0, 1.0),
    "EURNZD": (3.36, 1.12), "GBPAUD": (3.0, 1.0), "GBPCAD": (4.34, 1.45),
    "GBPCHF": (2.45, 0.82), "GBPJPY": (2.22, 0.50), "GBPUSD": (1.97, 0.52),
    "GC": (4.0, 1.0), "NZDCAD": (5.48, 1.83), "NZDCHF": (4.0, 1.0),
    "NZDJPY": (2.02, 0.51), "NZDUSD": (3.87, 1.29), "USDCAD": (3.90, 1.30),
    "USDCHF": (3.0, 0.85), "USDJPY": (1.97, 0.52), "^DJI": (4.0, 0.5),
}

SELL_ONLY_POOL = [
    "AUDJPY","AUDUSD","BTCUSD","CADCHF","EURCAD","EURCHF",
    "EURNZD","GBPCAD","GBPCHF","GBPJPY","GC","NZDCAD",
    "NZDCHF","NZDJPY","NZDUSD","USDCAD","USDCHF","USDJPY","^DJI",
]

def load_signal_parquet(asset):
    path = WALKFORWARD_DIR / f"{asset}_wf_signals_{TAG}.parquet"
    if not path.exists():
        return None
    df = pd.read_parquet(path)
    if isinstance(df.index, pd.MultiIndex):
        df.index = df.index.get_level_values("date")
    if not isinstance(df.index, pd.DatetimeIndex):
        df.index = pd.to_datetime(df.index)
    if df.index.tz is not None:
        df.index = df.index.tz_localize(None)
    return df

def load_summary(asset):
    path = WALKFORWARD_DIR / f"{asset}_wf_summary_{TAG}.csv"
    try:
        return pd.read_csv(path)
    except:
        return None

def wilson_ci(wins, n, z=1.96):
    if n == 0:
        return 0.0, 0.0, 0.0
    p = wins / n
    denom = 1 + z**2 / n
    centre = (p + z**2 / (2 * n)) / denom
    margin = z * np.sqrt((p * (1 - p) + z**2 / (4 * n)) / n) / denom
    return p, centre - margin, centre + margin


def main():
    results = {}

    # ── Load summaries and signals ──
    summaries = {}
    signals = {}
    for a in SELL_ONLY_POOL:
        s = load_summary(a)
        if s is not None:
            summaries[a] = s
        sig = load_signal_parquet(a)
        if sig is not None:
            signals[a] = sig

    # ── PRE-CHECK: Fold Stability (refined from Check 1) ──
    fold_stability = {}
    for asset in SELL_ONLY_POOL:
        if asset not in summaries:
            fold_stability[asset] = {"fold_count": 0, "stable": False, "decay": False, "single_fold": False, "avg_hit": 0}
            continue
        df = summaries[asset]
        folds_w_sell = []
        fold_hits = []
        for _, r in df.iterrows():
            n_s = int(r["test_samples"] * r["short_rate"])
            folds_w_sell.append(n_s)
            fold_hits.append(r["hit_rate"] if n_s > 10 else None)
        
        n_active = sum(1 for n in folds_w_sell if n > 10)
        avg_hit = np.mean([h for h in fold_hits if h is not None]) if any(fold_hits) else 0.0
        
        # Decay detection: hit_rate correlation with fold index for active folds
        decay = False
        if n_active >= 4:
            active_indices = [(i, fold_hits[i]) for i in range(5) if fold_hits[i] is not None]
            if len(active_indices) >= 4:
                xs = np.array([i for i, _ in active_indices])
                ys = np.array([h for _, h in active_indices])
                if len(xs) > 1 and np.std(ys) > 0.05:
                    slope = np.polyfit(xs, ys, 1)[0]
                    decay = slope < -0.03 and ys[0] > 0 and ys[-1] < 0
        
        fold_stability[asset] = {
            "fold_count": n_active,
            "stable": n_active >= 3 and abs(avg_hit) > 0.05,
            "decay": decay,
            "single_fold": n_active == 1,
            "avg_hit_rate": round(float(avg_hit), 4),
            "folds_n_sell": folds_w_sell,
        }

    # ── CHECK 2: Trade Count + CI (fold-aware) ──
    check2 = {}
    for asset in SELL_ONLY_POOL:
        sig = signals.get(asset)
        if sig is None:
            check2[asset] = {"error": "no_signal_data"}
            continue
        fs = fold_stability[asset]
        sell = sig[sig["signal"] == -1]
        n_s = len(sell)
        s_wins = int((sell["label"] == 0).sum()) if n_s > 0 else 0
        s_wr, s_ci_l, s_ci_h = wilson_ci(s_wins, n_s)
        s_ci_w = s_ci_h - s_ci_l
        
        buy = sig[sig["signal"] == 1]
        n_b = len(buy)
        b_wins = int((buy["label"] == 1).sum()) if n_b > 0 else 0
        b_wr, b_ci_l, b_ci_h = wilson_ci(b_wins, n_b)
        b_ci_w = b_ci_h - b_ci_l
        
        # Per-fold WR for SELL
        per_fold_wr = []
        df_sig = sig.copy()
        df_sig["fold_label"] = "unknown"
        # Reconstruct fold from summary
        summ = summaries.get(asset)
        if summ is not None:
            for _, row in summ.iterrows():
                ts = pd.Timestamp(row["test_start"])
                te = pd.Timestamp(row["test_end"])
                mask = (df_sig.index >= ts) & (df_sig.index <= te)
                df_sig.loc[mask, "fold_label"] = f"fold_{int(row['fold'])}"
            for fname in sorted(df_sig["fold_label"].unique()):
                fdata = df_sig[(df_sig["fold_label"] == fname) & (df_sig["signal"] == -1)]
                fn = len(fdata)
                if fn > 0:
                    fw = int((fdata["label"] == 0).sum())
                    per_fold_wr.append({"fold": fname, "n": fn, "wr": round(fw / fn, 4)})
        
        check2[asset] = {
            "n_sell": n_s, "sell_wr": round(s_wr, 4),
            "sell_ci_width": round(s_ci_w, 4),
            "sell_significant": s_ci_l > 0.5,
            "n_buy": n_b, "buy_wr": round(b_wr, 4),
            "buy_ci_width": round(b_ci_w, 4),
            "low_n_flag": n_s < 30,
            "ci_info": n_s >= 30,
            "per_fold_sell_wr": per_fold_wr,
        }

    # ── CHECK 3: Expectancy ──
    check3 = {}
    for asset in SELL_ONLY_POOL:
        sig = signals.get(asset)
        if sig is None:
            check3[asset] = {"error": "no_signal_data"}
            continue
        tp, sl = ASSET_TP_SL.get(asset, (2.0, 1.0))
        rrr = tp / sl
        be_wr = sl / (tp + sl)
        
        sell = sig[sig["signal"] == -1]
        n_s = len(sell)
        s_wins = int((sell["label"] == 0).sum()) if n_s > 0 else 0
        wr_s = s_wins / n_s if n_s > 0 else 0.0
        e_s = wr_s * tp - (1 - wr_s) * sl
        
        buy = sig[sig["signal"] == 1]
        n_b = len(buy)
        b_wins = int((buy["label"] == 1).sum()) if n_b > 0 else 0
        wr_b = b_wins / n_b if n_b > 0 else 0.0
        e_b = wr_b * tp - (1 - wr_b) * sl
        
        n_total = n_s + n_b
        n_wins = s_wins + b_wins
        e_net = (n_wins * tp - (n_total - n_wins) * sl) / n_total if n_total > 0 else 0.0
        
        # Fold-aware total R (expectancy * trades)
        total_r = e_net * n_total
        
        # High WR / Low E check
        hw_le = wr_s > 0.7 and e_s < 0.5
        
        check3[asset] = {
            "tp": tp, "sl": sl, "rrr": round(rrr, 2), "be_wr": round(be_wr, 4),
            "n_sell": n_s, "sell_wr": round(wr_s, 4), "sell_e": round(e_s, 4),
            "n_buy": n_b, "buy_wr": round(wr_b, 4),
            "total_trades": n_total, "net_e": round(e_net, 4),
            "total_R": round(total_r, 1),
            "high_wr_low_e": hw_le,
        }

    # ── CHECK 6: Cross-Asset Signal Correlation ──
    # Use p_long signals aligned by timestamp
    sig_probs = {}
    for asset in SELL_ONLY_POOL:
        sig = signals.get(asset)
        if sig is None or len(sig) < 50:
            continue
        sp = sig["p_long"].copy()
        sp.name = asset
        sig_probs[asset] = sp
    
    common_idx = None
    for sp in sig_probs.values():
        idx_set = set(sp.dropna().index)
        if common_idx is None:
            common_idx = idx_set
        else:
            common_idx = common_idx.intersection(idx_set)
    common_idx = sorted(common_idx)
    
    if len(common_idx) >= 50:
        aligned = pd.DataFrame({a: sig_probs[a].loc[common_idx] for a in sig_probs})
        corr = aligned.corr(method="spearman")
        eigvals = np.linalg.eigvalsh(corr.values)
        eigvals = np.maximum(eigvals, 0)
        hhi = np.sum(eigvals**2) / (np.sum(eigvals)**2) if np.sum(eigvals) > 0 else 1.0
        n_eff = 1.0 / hhi if hhi > 0 else 1.0
        
        high_corr = []
        assets_list = list(corr.columns)
        for i in range(len(assets_list)):
            for j in range(i + 1, len(assets_list)):
                c = float(corr.iloc[i, j])
                if abs(c) > 0.5:
                    high_corr.append({"pair": f"{assets_list[i]}/{assets_list[j]}", "corr": round(c, 3)})
        
        # Fold-level correlation: how often do assets trade SELL in the same fold?
        fold_overlap = {}
        for asset in SELL_ONLY_POOL:
            summ = summaries.get(asset)
            if summ is None:
                continue
            active_folds = []
            for _, r in summ.iterrows():
                if r["short_rate"] > 0.05:
                    active_folds.append(int(r["fold"]))
            fold_overlap[asset] = active_folds
        
        check6 = {
            "n_assets": len(corr.columns),
            "n_aligned_timestamps": len(common_idx),
            "effective_independent_bets": round(n_eff, 2),
            "hhi_eigenvalues": round(hhi, 4),
            "max_abs_corr": round(float(np.max(np.abs(np.triu(corr.values, k=1)))), 3),
            "mean_abs_corr": round(float(np.mean(np.abs(np.triu(corr.values, k=1)))), 3),
            "high_corr_pairs_above_0_5": high_corr,
            "eigenvalue_decay_top10": [round(float(x), 4) for x in sorted(eigvals, reverse=True)[:10]],
            "fold_overlap": {a: folds for a, folds in fold_overlap.items() if len(folds) >= 2},
        }
    else:
        check6 = {"error": f"too_few_aligned_timestamps:{len(common_idx)}"}

    # ── SYNTHESIS ──
    # Categorize each asset by evidence quality
    synthesis = {}
    for asset in SELL_ONLY_POOL:
        fs = fold_stability.get(asset, {})
        c2 = check2.get(asset, {})
        c3 = check3.get(asset, {})
        
        if isinstance(c2, dict) and c2.get("low_n_flag"):
            tier = "D - insufficient trades"
        elif fs.get("single_fold"):
            tier = "C - single fold only"
        elif fs.get("decay"):
            tier = "C - WR decay across folds"
        elif fs.get("fold_count", 0) >= 3 and c2.get("sell_significant"):
            tier = "A - multi-fold stable & significant"
        elif fs.get("fold_count", 0) >= 2:
            tier = "B - multi-fold but unstable"
        else:
            tier = "D - insufficient evidence"
        
        synthesis[asset] = {
            "tier": tier,
            "fold_count": fs.get("fold_count", 0),
            "avg_hit_rate": fs.get("avg_hit_rate"),
            "sell_wr": c2.get("sell_wr"),
            "sell_ci_width": c2.get("sell_ci_width"),
            "net_expectancy": c3.get("net_e"),
            "total_R": c3.get("total_R"),
            "n_sell": c2.get("n_sell"),
            "decay": fs.get("decay", False),
            "single_fold": fs.get("single_fold", False),
        }

    # ── OUTPUT ──
    result = {
        "tag": TAG,
        "macro_data_range": "2020-01-02 to 2026-07-02 (macro bottleneck)",
        "effective_asset_data_range": "2021-01 to 2026-06 (after feature warmup)",
        "check_1_fold_stability": fold_stability,
        "check_2_trade_count_audit": check2,
        "check_3_expectancy": check3,
        "check_6_cross_asset_correlation": check6,
        "synthesis": synthesis,
        "tier_summary": {},
    }
    for asset, syn in synthesis.items():
        t = syn["tier"]
        result["tier_summary"].setdefault(t, 0)
        result["tier_summary"][t] += 1

    out_path = OUTPUT_DIR / "stress_test_6_checks_v2.json"
    with open(out_path, "w") as f:
        json.dump(result, f, indent=2, default=str)
    
    # Print summary
    print("=" * 80)
    print("FINAL TIER CLASSIFICATION (SELL_ONLY alpha evidence quality)")
    print("=" * 80)
    print(f"\n{'Asset':>8} | {'Tier':>35} | {'nS':>5} | {'WR(S)':>7} | {'E(net)':>7} | {'TotalR':>8} | {'CIw':>5} | {'Folds':>5}")
    print("-" * 90)
    for asset in sorted(synthesis.keys()):
        s = synthesis[asset]
        if s is None:
            continue
        print(f"{asset:>8} | {s['tier']:>35} | {s['n_sell']:>5d} | {s['sell_wr']:.2%} "
              f"| {s['net_expectancy']:>+7.3f} | {s['total_R']:>8.1f} | {s['sell_ci_width']:.3f} | {s['fold_count']:>5d}")
    
    print(f"\nTier summary:")
    for t, c in sorted(result["tier_summary"].items()):
        print(f"  {t}: {c}")
    
    print(f"\nEffective independent bets: {check6.get('effective_independent_bets', 'N/A')} of {check6.get('n_assets', 'N/A')}")
    print(f"Saved to {out_path}")

if __name__ == "__main__":
    main()
