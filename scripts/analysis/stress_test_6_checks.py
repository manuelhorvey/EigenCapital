"""
Six checks to stress-test SELL_ONLY alpha robustness.

Usage:
  PYTHONPATH=$PYTHONPATH:. python scripts/analysis/stress_test_6_checks.py

Output: data/processed/stress_test_6_checks.json + printed summary
"""

import json
import os
import warnings
from pathlib import Path

import numpy as np
import pandas as pd
from scipy.stats import norm

warnings.filterwarnings("ignore")

OUTPUT_DIR = Path("data/processed")
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
WALKFORWARD_DIR = Path("scripts/walkforward")

# ── Per-asset TP/SL from config (truth) ──
ASSET_TP_SL = {
    "AUDJPY": (2.01, 0.52),
    "AUDUSD": (4.24, 1.41),
    "BTCUSD": (1.51, 0.58),
    "CADCHF": (4.0, 1.0),
    "CADJPY": (1.97, 0.52),
    "CHFJPY": (2.0, 0.5),
    "EURAUD": (1.77, 0.54),
    "EURCAD": (2.12, 0.71),
    "EURCHF": (3.0, 1.0),
    "EURNZD": (3.36, 1.12),
    "GBPAUD": (3.0, 1.0),
    "GBPCAD": (4.34, 1.45),
    "GBPCHF": (2.45, 0.82),
    "GBPJPY": (2.22, 0.50),
    "GBPUSD": (1.97, 0.52),
    "GC": (4.0, 1.0),
    "NZDCAD": (5.48, 1.83),
    "NZDCHF": (4.0, 1.0),
    "NZDJPY": (2.02, 0.51),
    "NZDUSD": (3.87, 1.29),
    "USDCAD": (3.90, 1.30),
    "USDCHF": (3.0, 0.85),
    "USDJPY": (1.97, 0.52),
    "^DJI": (4.0, 0.5),
}

# ── Sell-only assets from expanded_10yr validation ──
SELL_ONLY_ASSETS = [
    "AUDJPY", "AUDUSD", "BTCUSD", "CADCHF", "EURCAD", "EURCHF",
    "EURNZD", "GBPCAD", "GBPCHF", "GBPJPY", "GC", "NZDCAD",
    "NZDCHF", "NZDJPY", "NZDUSD", "USDCAD", "USDCHF", "USDJPY", "^DJI",
]


def load_signal_parquet(asset, tag="expanded_10yr"):
    """Load OOS signal parquet for an asset."""
    path = WALKFORWARD_DIR / f"{asset}_wf_signals_{tag}.parquet"
    if not path.exists():
        return None
    df = pd.read_parquet(path)
    if isinstance(df.index, pd.MultiIndex):
        df.index = df.index.get_level_values("date")
    if not isinstance(df.index, pd.DatetimeIndex):
        df.index = pd.to_datetime(df.index)
    df["year"] = df.index.year
    return df


def wilson_ci(wins, n, z=1.96):
    """Wilson score confidence interval for a proportion."""
    if n == 0:
        return 0.0, 0.0, 0.0
    p = wins / n
    denominator = 1 + z**2 / n
    centre = (p + z**2 / (2 * n)) / denominator
    margin = z * np.sqrt((p * (1 - p) + z**2 / (4 * n)) / n) / denominator
    return p, centre - margin, centre + margin


def check_1_regime_decomposition(signals):
    """Yearly WR(S) per asset, flag concentration."""
    results = {}
    for asset in SELL_ONLY_ASSETS:
        df = signals.get(asset)
        if df is None or df.empty:
            results[asset] = {"error": "no_data"}
            continue
        sell = df[df["signal"] == -1]
        if sell.empty:
            results[asset] = {"error": "no_sell_trades"}
            continue
        yearly = []
        for yr in sorted(sell["year"].unique()):
            yr_sell = sell[sell["year"] == yr]
            n = len(yr_sell)
            wins = (yr_sell["label"] == 0).sum()
            wr = wins / n if n > 0 else 0.0
            yearly.append({"year": int(yr), "n": n, "wins": int(wins), "wr": round(wr, 4)})
        total_wins = sum(y["wins"] for y in yearly)
        total_n = sum(y["n"] for y in yearly)
        overall_wr = total_wins / total_n if total_n > 0 else 0.0
        active_years = [y for y in yearly if y["n"] >= 10]
        if active_years:
            wr_values = np.array([y["wr"] for y in active_years])
            wr_std = float(np.std(wr_values))
            wr_mean = float(np.mean(wr_values))
            max_deviation = float(np.max(np.abs(wr_values - wr_mean)))
            pct_positive = float(np.mean(wr_values > 0.5))
        else:
            wr_std = 0.0
            wr_mean = 0.0
            max_deviation = 0.0
            pct_positive = 0.0
        dominant_year = max(yearly, key=lambda y: y["n"]) if yearly else None
        dominance_pct = (dominant_year["n"] / total_n * 100) if dominant_year and total_n > 0 else 0.0
        flagged = dominance_pct > 40 or wr_std > 0.15 or max_deviation > 0.25
        results[asset] = {
            "total_sell_trades": total_n,
            "overall_wr": round(overall_wr, 4),
            "yearly": yearly,
            "n_active_years": len(active_years),
            "wr_std_across_years": round(wr_std, 4),
            "max_wr_deviation": round(max_deviation, 4),
            "pct_years_above_50pct": round(pct_positive, 4),
            "dominant_year_pct": round(dominance_pct, 1),
            "flagged": flagged,
            "flag_reason": (
                f"yr_conc={dominance_pct:.0f}%>40"
                if dominance_pct > 40
                else f"high_std={wr_std:.3f}>0.15"
                if wr_std > 0.15
                else f"max_dev={max_deviation:.2f}>0.25"
                if max_deviation > 0.25
                else "ok"
            ),
        }
    return results


def check_2_trade_count_audit(signals, skill_results):
    """Report n_trades + Wilson CI on all WRs, flag low-n."""
    results = {}
    for asset in SELL_ONLY_ASSETS:
        df = signals.get(asset)
        if df is None or df.empty:
            results[asset] = {"error": "no_data"}
            continue
        classes = {}
        for sig_val, sig_name in [(-1, "sell"), (1, "buy"), (0, "flat")]:
            subset = df[df["signal"] == sig_val]
            n = len(subset)
            if n == 0:
                classes[sig_name] = {"n": 0, "wr": None, "ci_low": None, "ci_high": None, "flagged": True, "reason": "zero_trades"}
                continue
            wins = (subset["label"] == (0 if sig_val == -1 else 1)).sum()
            p, ci_low, ci_high = wilson_ci(wins, n)
            flagged = n < 30
            classes[sig_name] = {
                "n": n,
                "wr": round(p, 4),
                "ci_low": round(ci_low, 4),
                "ci_high": round(ci_high, 4),
                "flagged": flagged,
                "reason": f"n={n}<30" if flagged else "ok",
            }
        results[asset] = classes
    return results


def check_3_expectancy_conversion(signals):
    """Compute expectancy E = WR*tp - (1-WR)*sl. Rank by E not WR."""
    results = {}
    for asset in SELL_ONLY_ASSETS:
        tp, sl = ASSET_TP_SL.get(asset, (2.0, 1.0))
        df = signals.get(asset)
        if df is None or df.empty:
            results[asset] = {"error": "no_data"}
            continue
        # SELL trades
        sell = df[df["signal"] == -1]
        n_sell = len(sell)
        sell_wins = (sell["label"] == 0).sum() if n_sell > 0 else 0
        wr_s = sell_wins / n_sell if n_sell > 0 else 0.0
        expectancy_s = wr_s * tp - (1 - wr_s) * sl
        breakeven_wr_s = sl / (tp + sl)
        rrr = tp / sl
        # BUY trades
        buy = df[df["signal"] == 1]
        n_buy = len(buy)
        buy_wins = (buy["label"] == 1).sum() if n_buy > 0 else 0
        wr_b = buy_wins / n_buy if n_buy > 0 else 0.0
        expectancy_b = wr_b * tp - (1 - wr_b) * sl
        breakeven_wr_b = sl / (tp + sl)
        # Net expectancy per trade
        total_trades = n_sell + n_buy
        total_wins = sell_wins + buy_wins
        net_expectancy = (total_wins * tp - (total_trades - total_wins) * sl) / total_trades if total_trades > 0 else 0.0
        # Spread/slippage: assume 1bp cost per trade (conservative for FX majors, 2bp for crosses, 3bp for indices/metals)
        spread_cost = 0.0
        if asset in ("^DJI", "GC", "BTCUSD"):
            spread_cost = 0.03
        elif asset in ("AUDJPY", "NZDJPY", "GBPJPY", "CHFJPY", "CADJPY"):
            spread_cost = 0.02
        else:
            spread_cost = 0.01
        expectancy_net = net_expectancy - spread_cost
        high_wr_low_e = wr_s > 0.7 and expectancy_s < 0.1
        results[asset] = {
            "tp_mult": tp,
            "sl_mult": sl,
            "rrr": round(rrr, 2),
            "breakeven_wr": round(breakeven_wr_s, 4),
            "sell_trades": n_sell,
            "sell_wr": round(wr_s, 4),
            "sell_expectancy_per_trade": round(expectancy_s, 4),
            "sell_expectancy_total": round(expectancy_s * n_sell, 1),
            "buy_trades": n_buy,
            "buy_wr": round(wr_b, 4),
            "buy_expectancy_per_trade": round(expectancy_b, 4),
            "total_trades": total_trades,
            "net_expectancy_per_trade": round(net_expectancy, 4),
            "spread_cost_r": spread_cost,
            "net_expectancy_after_spread": round(expectancy_net, 4),
            "high_wr_low_e_flag": high_wr_low_e,
        }
    return results


def check_6_cross_asset_correlation(signals):
    """Pairwise SELL signal probability correlation. Effective independent bets."""
    sig_probs = {}
    for asset in SELL_ONLY_ASSETS:
        df = signals.get(asset)
        if df is None or df.empty:
            continue
        # Use p_long as signal probability, aligned by timestamp
        sp = df["p_long"].copy()
        sp.name = asset
        # If p_long > 0.5, model predicts BUY; if < 0.5, SELL
        sig_probs[asset] = sp
    common_index = None
    for asset, sp in sig_probs.items():
        if common_index is None:
            common_index = set(sp.index)
        else:
            common_index = common_index.intersection(set(sp.index))
    common_index = sorted(common_index)
    if len(common_index) < 10:
        return {"error": f"too_few_aligned_timestamps:{len(common_index)}"}
    aligned = pd.DataFrame({asset: sig_probs[asset].loc[common_index]
                           for asset in sig_probs})
    corr = aligned.corr(method="spearman")
    eigvals = np.linalg.eigvalsh(corr.values)
    eigvals = np.maximum(eigvals, 0)
    hhi = np.sum(eigvals**2) / (np.sum(eigvals)**2) if np.sum(eigvals) > 0 else 1.0
    n_effective = 1.0 / hhi if hhi > 0 else 1.0
    high_corr_pairs = []
    assets_list = list(corr.columns)
    for i in range(len(assets_list)):
        for j in range(i + 1, len(assets_list)):
            c = corr.iloc[i, j]
            if abs(c) > 0.5:
                high_corr_pairs.append({
                    "a": assets_list[i],
                    "b": assets_list[j],
                    "corr": round(c, 3),
                })
    return {
        "n_assets": len(assets_list),
        "n_aligned_timestamps": len(common_index),
        "n_effective_independent_bets": round(n_effective, 2),
        "hhi_of_eigenvalues": round(hhi, 4),
        "max_corr": round(float(np.max(np.triu(corr.values, k=1))), 3),
        "mean_abs_corr": round(float(np.mean(np.abs(np.triu(corr.values, k=1)))), 3),
        "high_corr_pairs_above_0_5": high_corr_pairs,
        "eigenvalue_decay": [round(float(x), 4) for x in sorted(eigvals, reverse=True)[:10]],
    }


def main():
    tag = "expanded_10yr"
    print("=" * 80)
    print(f"STRESS TEST: 6 checks on SELL_ONLY alpha  (tag={tag})")
    print("=" * 80)

    # Load skill results to confirm sell-only list
    skill_path = OUTPUT_DIR / f"directional_skill_{tag}.json"
    if skill_path.exists():
        with open(skill_path) as f:
            skill_results = {x["asset"]: x for x in json.load(f)}
    else:
        skill_results = {}

    # Load signal parquets
    signals = {}
    for asset in SELL_ONLY_ASSETS:
        df = load_signal_parquet(asset, tag=tag)
        if df is not None:
            signals[asset] = df
            print(f"  Loaded {asset}: {len(df)} OOS rows ({df.index.year.min()}-{df.index.year.max()})")
        else:
            print(f"  MISSING {asset}: no signal parquet")

    # ── Check 1: Regime Decomposition ──
    print("\n" + "─" * 40)
    print("CHECK 1: REGIME DECOMPOSITION (yearly WR stability)")
    print("─" * 40)
    c1 = check_1_regime_decomposition(signals)
    n_flagged = sum(1 for v in c1.values() if isinstance(v, dict) and v.get("flagged"))
    n_ok = sum(1 for v in c1.values() if isinstance(v, dict) and not v.get("flagged"))
    n_err = sum(1 for v in c1.values() if isinstance(v, dict) and v.get("error"))
    print(f"  Flagged: {n_flagged}, OK: {n_ok}, Error: {n_err}")
    flagged_assets = [a for a, v in c1.items() if isinstance(v, dict) and v.get("flagged")]
    for a in flagged_assets:
        v = c1[a]
        dom_yr = max(v["yearly"], key=lambda y: y["n"]) if v.get("yearly") else None
        print(f"  ⚠ {a}: WR_std={v['wr_std_across_years']:.3f}, "
              f"dominant_yr={dom_yr['year'] if dom_yr else '?'}@"
              f"{v['dominant_year_pct']:.0f}% of trades, "
              f"max_dev={v['max_wr_deviation']:.2f}")

    # ── Check 2: Trade Count Audit ──
    print("\n" + "─" * 40)
    print("CHECK 2: TRADE COUNT AUDIT (Wilson CIs)")
    print("─" * 40)
    c2 = check_2_trade_count_audit(signals, skill_results)
    low_n_sell = []
    for a, cls in c2.items():
        s = cls.get("sell", {})
        if s.get("flagged"):
            low_n_sell.append((a, s["n"]))
    print(f"  Assets with <30 SELL trades: {len(low_n_sell)}")
    for a, n in low_n_sell[:10]:
        print(f"    ⚠ {a}: n_sell={n}")
    high_ci_sell = []
    for a, cls in c2.items():
        s = cls.get("sell", {})
        b = cls.get("buy", {})
        if s.get("n", 0) >= 30 and b.get("n", 0) >= 30:
            s_ci_w = s.get("ci_high", 0) - s.get("ci_low", 0)
            b_ci_w = b.get("ci_high", 0) - b.get("ci_low", 0)
            high_ci_sell.append((a, s_ci_w, b_ci_w))
    print(f"  CI widths (sell) for assets with ≥30 both classes:")
    for a, s_w, b_w in sorted(high_ci_sell, key=lambda x: x[1]):
        print(f"    {a}: sell_CI_width={s_w:.3f}, buy_CI_width={b_w:.3f}")

    # ── Check 3: Expectancy Conversion ──
    print("\n" + "─" * 40)
    print("CHECK 3: EXPECTANCY CONVERSION")
    print("─" * 40)
    c3 = check_3_expectancy_conversion(signals)
    ranked = sorted(
        [(a, v) for a, v in c3.items() if isinstance(v, dict) and not v.get("error")],
        key=lambda x: x[1]["net_expectancy_after_spread"],
        reverse=True,
    )
    print(f"  {'Asset':>8} | {'TP':>4} {'SL':>4} | {'WR(S)':>6} | {'E(S)':>7} | {'E(net)':>7} | {'RRR':>4} | {'BE_WR':>6} | {'nS':>5} | {'nB':>5}")
    print("-" * 72)
    for a, v in ranked:
        print(f"  {a:>8} | {v['tp_mult']:>4.1f} {v['sl_mult']:>4.2f} | "
              f"{v['sell_wr']:.2%} | {v['sell_expectancy_per_trade']:>+7.3f} | "
              f"{v['net_expectancy_after_spread']:>+7.3f} | {v['rrr']:>4.1f} | "
              f"{v['breakeven_wr']:.2%} | {v['sell_trades']:>5d} | {v['buy_trades']:>5d}")
    high_wr_low_e = [a for a, v in c3.items() if isinstance(v, dict) and v.get("high_wr_low_e_flag")]
    print(f"\n  High-WR / Low-Expectancy flagged: {high_wr_low_e if high_wr_low_e else 'None'}")

    # ── Check 6: Cross-Asset Signal Correlation ──
    print("\n" + "─" * 40)
    print("CHECK 6: CROSS-ASSET SIGNAL CORRELATION")
    print("─" * 40)
    c6 = check_6_cross_asset_correlation(signals)
    if "error" not in c6:
        print(f"  Assets in matrix: {c6['n_assets']}")
        print(f"  Aligned timestamps: {c6['n_aligned_timestamps']}")
        print(f"  Effective independent bets: {c6['n_effective_independent_bets']} (of {c6['n_assets']})")
        print(f"  Max pairwise |corr|: {c6['max_corr']:.3f}")
        print(f"  Mean |corr|: {c6['mean_abs_corr']:.3f}")
        print(f"  HHI of eigenvalues: {c6['hhi_of_eigenvalues']:.4f}")
        print(f"  Eigenvalue decay (top 10): {c6['eigenvalue_decay']}")
        if c6["high_corr_pairs_above_0_5"]:
            print(f"  High-corr pairs (>0.5):")
            for pair in c6["high_corr_pairs_above_0_5"]:
                print(f"    {pair['a']} vs {pair['b']}: {pair['corr']:.3f}")
        else:
            print(f"  No pairs with |corr| > 0.5")
    else:
        print(f"  Error: {c6['error']}")

    # Save intermediate results
    output = {
        "tag": tag,
        "n_assets": len(SELL_ONLY_ASSETS),
        "check_1_regime_decomposition": {k: v for k, v in c1.items() if isinstance(v, dict) and "yearly" in v},
        "check_2_trade_count_audit": c2,
        "check_3_expectancy_conversion": {k: v for k, v in c3.items() if isinstance(v, dict) and "sell_expectancy_per_trade" in v},
        "check_6_cross_asset_correlation": c6,
    }
    output_path = OUTPUT_DIR / "stress_test_6_checks.json"
    with open(output_path, "w") as f:
        json.dump(output, f, indent=2, default=str)
    print(f"\nSaved to {output_path}")


if __name__ == "__main__":
    main()
