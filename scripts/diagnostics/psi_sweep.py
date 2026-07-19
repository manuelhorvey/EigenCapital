#!/usr/bin/env python3
"""
PSI (Population Stability Index) sweep across all portfolio assets.

Methodology (per advisor guidance):
1. Reference window = first 50% of data points (same for all assets)
2. Comparison window = second 50% of data points
3. Decile binning (10 equal-width bins) on raw p_long probability
4. Standard thresholds: <0.1 stable, 0.1-0.25 moderate, >0.25 significant
5. Feature-level PSI for flagged assets to distinguish input drift vs model non-stationarity

Usage:
    PYTHONPATH=$PYTHONPATH:. python scripts/diagnostics/psi_sweep.py
"""

from __future__ import annotations

import json
import logging
import sys
import warnings
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, Path(Path(__file__).resolve().parent.parent, "."))

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("psi_sweep")
warnings.filterwarnings("ignore")

OUTPUT_DIR = Path("diagnostics_output")
OUTPUT_DIR.mkdir(exist_ok=True)

# All 21 portfolio assets
ALL_ASSETS = [
    "GC", "USDCHF", "USDCAD", "ES", "NQ", "GBPCAD",
    "NZDCAD", "^DJI", "NZDUSD", "GBPAUD", "NZDCHF", "CADCHF",
    "AUDUSD", "EURCHF", "EURCAD", "EURNZD", "GBPCHF", "GBPUSD", "EURAUD",
    "USDJPY", "GBPJPY",
]

# PSI thresholds (standard)
PSI_STABLE = 0.1
PSI_MODERATE = 0.25

# Feature names for ES feature-level PSI
ES_FEATURE_COLS = [
    "ES_carry_vol_adj", "ES_mom_21d", "ES_mom_63d", "ES_mom_126d", "ES_mom_252d",
    "ES_zscore_20", "ES_vol_ratio", "ES_dow_signal",
    "dxy_mom_21d", "vix_mom_5d", "spx_mom_5d",
]


def compute_psi(reference: np.ndarray, actual: np.ndarray, n_bins: int = 10) -> float:
    """Population Stability Index: measures distribution shift between two probability arrays.

    PSI = sum((actual_pct_i - ref_pct_i) * ln(actual_pct_i / ref_pct_i))

    Uses equal-width bins. Small pseudo-counts (1e-6) to avoid log(0).
    """
    if len(reference) == 0 or len(actual) == 0:
        return 0.0

    bin_edges = np.linspace(0, 1, n_bins + 1)
    ref_counts, _ = np.histogram(reference, bins=bin_edges)
    actual_counts, _ = np.histogram(actual, bins=bin_edges)

    ref_pct = ref_counts / max(ref_counts.sum(), 1)
    actual_pct = actual_counts / max(actual_counts.sum(), 1)

    psi = 0.0
    for r, a in zip(ref_pct, actual_pct):
        r = max(r, 1e-6)
        a = max(a, 1e-6)
        psi += (a - r) * np.log(a / r)

    return round(float(psi), 4)


def compute_feature_psi(X_ref: pd.DataFrame, X_actual: pd.DataFrame) -> dict:
    """Compute per-feature PSI between reference and actual feature distributions.

    Handles features with different value ranges by using decile binning
    relative to the reference distribution.
    """
    per_feature_psi = {}
    for col in X_ref.columns:
        if col not in X_actual.columns:
            continue
        ref_vals = X_ref[col].dropna().values
        act_vals = X_actual[col].dropna().values
        if len(ref_vals) < 10 or len(act_vals) < 10:
            continue

        # Decile binning: bin edges from reference distribution
        bin_edges = np.percentile(ref_vals, np.linspace(0, 100, 11))
        # Ensure unique bin edges (handle duplicate percentiles)
        bin_edges = np.unique(bin_edges)
        if len(bin_edges) < 2:
            continue

        ref_counts, _ = np.histogram(ref_vals, bins=bin_edges)
        actual_counts, _ = np.histogram(act_vals, bins=bin_edges)

        ref_pct = ref_counts / max(ref_counts.sum(), 1)
        actual_pct = actual_counts / max(actual_counts.sum(), 1)

        psi = 0.0
        for r, a in zip(ref_pct, actual_pct):
            r = max(r, 1e-6)
            a = max(a, 1e-6)
            psi += (a - r) * np.log(a / r)

        per_feature_psi[col] = round(float(psi), 4)

    return per_feature_psi


def load_walkforward(asset: str) -> pd.DataFrame | None:
    """Load the best available walk-forward parquet for an asset."""
    dirs = ["walkforward", "scripts/walkforward"]
    for d in dirs:
        # Try production tag first, then base
        for pattern in [
            f"{asset}_wf_signals_production.parquet",
            f"{asset}_wf_signals.parquet",
        ]:
            p = Path(d) / pattern
            if p.exists():
                return pd.read_parquet(p)
    return None


def generate_features(asset: str, ticker: str) -> pd.DataFrame | None:
    """Generate feature DataFrame for an asset using the production pipeline."""
    try:
        from features.alpha_features import build_alpha_features
        from features.data_fetch import fetch_asset_data, fetch_asset_ohlcv

        prices, rate_diffs, dxy, vix, spx, commodities = fetch_asset_data(asset, ticker)
        if prices.empty or len(prices) < 100:
            return None

        ohlcv = fetch_asset_ohlcv(ticker)
        alpha_df = build_alpha_features(
            prices, rate_diffs, dxy=dxy, vix=vix, spx=spx,
            commodities=commodities,
        )

        if not ohlcv.empty:
            from features.regime_features import generate_regime_features
            regime_df = generate_regime_features(ohlcv)
            prefix = asset.upper()
            regime_renamed = regime_df.rename(
                columns={c: f"{prefix}_{c}" for c in regime_df.columns}
            )
            full_df = alpha_df.join(regime_renamed, how="left").dropna()
        else:
            full_df = alpha_df.copy()

        return full_df.ffill().dropna()
    except Exception as e:
        logger.warning("  Could not generate features for %s: %s", asset, e)
        return None


# Ticker map for ES feature generation
TICKER_MAP = {
    "GC": "GC=F", "USDCHF": "USDCHF=X", "USDCAD": "USDCAD=X",
    "ES": "ES=F", "NQ": "NQ=F", "GBPCAD": "GBPCAD=X",
    "NZDCAD": "NZDCAD=X", "^DJI": "^DJI", "NZDUSD": "NZDUSD=X",
    "GBPAUD": "GBPAUD=X", "NZDCHF": "NZDCHF=X", "CADCHF": "CADCHF=X",
    "AUDUSD": "AUDUSD=X", "EURCHF": "EURCHF=X", "EURCAD": "EURCAD=X",
    "EURNZD": "EURNZD=X", "GBPCHF": "GBPCHF=X", "GBPUSD": "GBPUSD=X",
    "EURAUD": "EURAUD=X", "USDJPY": "USDJPY=X", "GBPJPY": "GBPJPY=X",
}


def main():
    results = []

    logger.info("=" * 70)
    logger.info("PSI SWEEP: 21 Assets")
    logger.info("Reference = first 50% of data points, Comparison = second 50%")
    logger.info("Decile binning (10 bins) on raw p_long probability")
    logger.info("Thresholds: <0.1 stable, 0.1-0.25 moderate, >0.25 significant")
    logger.info("=" * 70)

    for asset in ALL_ASSETS:
        df = load_walkforward(asset)
        if df is None or len(df) < 40:
            logger.warning("  %s: insufficient data — skipping", asset)
            continue

        p_long = df["p_long"].values
        n = len(p_long)
        mid = n // 2

        ref = p_long[:mid]
        actual = p_long[mid:]

        psi = compute_psi(ref, actual)

        # Classification
        if psi < PSI_STABLE:
            severity = "stable"
        elif psi < PSI_MODERATE:
            severity = "moderate"
        else:
            severity = "SIGNIFICANT"

        # Additional metrics
        ref_mean = float(ref.mean())
        actual_mean = float(actual.mean())
        mean_shift = actual_mean - ref_mean

        result = {
            "asset": asset,
            "n_total": n,
            "n_ref": len(ref),
            "n_actual": len(actual),
            "psi": psi,
            "severity": severity,
            "ref_mean_p_long": round(ref_mean, 4),
            "actual_mean_p_long": round(actual_mean, 4),
            "mean_shift": round(mean_shift, 4),
        }
        results.append(result)

        flag = " *** CRITICAL ***" if severity == "SIGNIFICANT" else ""
        logger.info(
            "  %-8s PSI=%-8.4f %-12s ref_mu=%-6.4f act_mu=%-6.4f shift=%+.4f%s",
            asset, psi, severity, ref_mean, actual_mean, mean_shift, flag,
        )

    # Sort by PSI descending
    results.sort(key=lambda r: -r["psi"])

    print()
    print("=" * 100)
    print("PSI SWEEP RESULTS (sorted by PSI descending)")
    print("=" * 100)
    print()

    header = "{:<10s} {:>6s} {:>10s} {:>10s} {:>12s} {:>10s} {:>10s} {:>10s} {:>12s}".format(
        "Asset", "N", "PSI", "Severity", "Ref_mu_pL", "Act_mu_pL",
        "Shift", "Ref_N", "Act_N")
    print(header)
    print("-" * len(header))

    n_critical = 0
    n_moderate = 0
    n_stable = 0

    for r in results:
        flag = " <<<" if r["severity"] == "SIGNIFICANT" else ""
        line = "{:<10s} {:>6d} {:>10.4f} {:>10s} {:>10.4f} {:>10.4f} {:>+10.4f} {:>10d} {:>10d}{}".format(
            r["asset"], r["n_total"], r["psi"], r["severity"],
            r["ref_mean_p_long"], r["actual_mean_p_long"],
            r["mean_shift"], r["n_ref"], r["n_actual"], flag)
        print(line)

        if r["severity"] == "SIGNIFICANT":
            n_critical += 1
        elif r["severity"] == "moderate":
            n_moderate += 1
        else:
            n_stable += 1

    print()
    print("-" * len(header))
    print("{:<10s} {:>6s} {:>10s} {:>10s} {:>10s} {:>10s} {:>10s} {:>10s} {:>10s}".format(
        "TOTAL", "", "", "", "", "", "", "", ""))
    print()
    print("Severity distribution:")
    print("  SIGNIFICANT (PSI > 0.25): {} assets".format(n_critical))
    print("  Moderate (PSI 0.1-0.25):  {} assets".format(n_moderate))
    print("  Stable (PSI < 0.1):        {} assets".format(n_stable))

    # Portfolio-wide crisis signal
    print()
    if n_critical >= 3:
        print("PORTFOLIO-WIDE CRISIS SIGNAL: {} assets with PSI > 0.25".format(n_critical))
        print("  This is not isolated — multiple assets show significant distribution drift.")
    elif n_critical == 0:
        print("No PSI > 0.25 assets found. ES PSI=5.08 was an artifact of the earlier methodology.")
    else:
        print("Isolated drift: {} asset(s) flagged. Investigate individually.".format(n_critical))

    # ── ES deep-dive: feature-level PSI ──
    print()
    print("=" * 100)
    print("ES FEATURE-LEVEL PSI (to distinguish input drift vs model non-stationarity)")
    print("=" * 100)
    print()

    es_ticker = TICKER_MAP.get("ES", "ES=F")
    es_features = generate_features("ES", es_ticker)

    if es_features is not None and len(es_features) >= 40:
        mid = len(es_features) // 2
        X_ref = es_features.iloc[:mid]
        X_actual = es_features.iloc[mid:]

        feature_psi = compute_feature_psi(X_ref, X_actual)

        print("{:<45s} {:>10s}".format("Feature", "PSI"))
        print("-" * 55)
        for feat, psi_val in sorted(feature_psi.items(), key=lambda x: -x[1])[:20]:
            flag = " ***" if psi_val > PSI_MODERATE else ""
            print("{:<45s} {:>10.4f}{}".format(feat, psi_val, flag))

        # Save full feature PSI
        feature_psi_path = OUTPUT_DIR / "ES_feature_psi.json"
        with open(feature_psi_path, "w") as f:
            json.dump(feature_psi, f, indent=2)
        print()
        print("Full ES feature-level PSI saved to {}".format(feature_psi_path))
    else:
        print("  Could not generate ES features for PSI analysis.")
        if es_features is None:
            print("  Reason: feature generation returned None")
        else:
            print("  Reason: only {} rows (need >= 40)".format(len(es_features)))

    # ── Save full results ──
    output_path = OUTPUT_DIR / "psi_sweep_results.json"
    with open(output_path, "w") as f:
        json.dump({"results": results, "n_assets": len(results), "threshold_stable": PSI_STABLE,
                    "threshold_moderate": PSI_MODERATE, "n_critical": n_critical,
                    "n_moderate": n_moderate, "n_stable": n_stable}, f, indent=2)
    logger.info("Full results saved to %s", output_path)


if __name__ == "__main__":
    main()
