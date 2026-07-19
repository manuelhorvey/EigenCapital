#!/usr/bin/env python3
"""
Feature-level PSI for top PSI outliers + synthetic stationary baseline.

Two investigations:

1. SYNTHETIC BASELINE: Run the same walk-forward + PSI methodology on a
   stationary AR(1) process (no regime shift) to establish what PSI value
   is "expected" under pure walk-forward growth with no real drift.

2. FEATURE-LEVEL PSI for EURAUD, GBPAUD, NZDCHF — the three highest-PSI
   assets — to determine whether they share a common driver or are failing
   for unrelated reasons.

Usage:
    PYTHONPATH=$PYTHONPATH:. python scripts/diagnostics/psi_feature_deepdive.py
"""

from __future__ import annotations

import json
import logging
import sys
import warnings
from pathlib import Path

import numpy as np
import pandas as pd

from eigencapital.domain.encoding import EigenCapitalJSONEncoder

sys.path.insert(0, Path(Path(__file__).resolve().parent.parent, "."))

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("psi_deepdive")
warnings.filterwarnings("ignore")

OUTPUT_DIR = Path("diagnostics_output")
OUTPUT_DIR.mkdir(exist_ok=True)

PSI_STABLE = 0.1
PSI_MODERATE = 0.25

# ── Synthetic baseline ──────────────────────────────────────────────────────


def generate_synthetic_series(n: int = 848, phi: float = 0.95, seed: int = 42) -> pd.Series:
    """Stationary AR(1) process with Gaussian noise.

    phi=0.95 gives realistic FX autocorrelation (~0.95 daily).
    Returns a series with same length as typical walk-forward data.
    """
    rng = np.random.RandomState(seed)
    innovations = rng.normal(0, 0.005, n)
    x = np.zeros(n)
    for t in range(1, n):
        x[t] = phi * x[t - 1] + innovations[t]
    return pd.Series(x, index=pd.bdate_range("2023-01-01", periods=n))


def run_synthetic_walk_forward(series: pd.Series, n_folds: int = 3, gap: int = 20) -> pd.Series:
    """Minimal walk-forward on a synthetic series to generate p_long-like output.

    Uses expanding windows like the real walk-forward. Returns a Series of
    "p_long" values (here simulated as the z-score of recent return).
    """
    from features.alpha_features import momentum_features, zscore_reversion

    # Create a price-like DataFrame from the synthetic series
    prices = pd.DataFrame({"close": np.exp(series.cumsum())})

    # Generate features similar to the real pipeline
    mom = momentum_features(prices["close"], horizons=[21, 63])
    zscore = zscore_reversion(prices["close"], window=20)

    features = pd.DataFrame(index=prices.index)
    features["mom_21d"] = mom["mom_21d"]
    features["mom_63d"] = mom["mom_63d"]
    features["zscore_20"] = zscore
    features["vol_ratio"] = features["mom_21d"].rolling(63).std() / max(
        features["mom_21d"].rolling(5).std().iloc[-1], 1e-9
    )

    features = features.dropna()
    if len(features) < 200:
        return pd.Series(dtype=float)

    n = len(features)
    fold_size = n // n_folds
    all_p_long = []

    for fold in range(n_folds):
        train_end = n - (n_folds - fold) * fold_size - gap
        test_start = train_end + gap
        test_end = min(test_start + fold_size, n)

        if train_end < 100 or test_start >= test_end:
            continue

        X_tr = features.iloc[:train_end]
        X_te = features.iloc[test_start:test_end]

        # Simple directional model: linear combination of features + noise
        # This gives us a "model" that evolves with more data (expanding window)
        weights = X_tr.mean() / X_tr.std().replace(0, np.nan)
        weights = weights.fillna(0)

        p_long_te = (X_te * weights).sum(axis=1)
        p_long_te = 1 / (1 + np.exp(-p_long_te.clip(-5, 5)))  # sigmoid

        all_p_long.append(p_long_te)

    if all_p_long:
        return pd.concat(all_p_long).sort_index()
    return pd.Series(dtype=float)


def compute_psi(reference: np.ndarray, actual: np.ndarray, n_bins: int = 10) -> float:
    """PSI between two distributions with decile binning."""
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
    """Per-feature PSI using reference distribution decile binning."""
    per_feature_psi = {}
    for col in X_ref.columns:
        if col not in X_actual.columns:
            continue
        ref_vals = X_ref[col].dropna().values
        act_vals = X_actual[col].dropna().values
        if len(ref_vals) < 10 or len(act_vals) < 10:
            continue
        bin_edges = np.percentile(ref_vals, np.linspace(0, 100, 11))
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
    for d in ["walkforward", "scripts/walkforward"]:
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
            prices,
            rate_diffs,
            dxy=dxy,
            vix=vix,
            spx=spx,
            commodities=commodities,
        )

        if not ohlcv.empty:
            from features.regime_features import generate_regime_features

            regime_df = generate_regime_features(ohlcv)
            prefix = asset.upper()
            regime_renamed = regime_df.rename(columns={c: f"{prefix}_{c}" for c in regime_df.columns})
            full_df = alpha_df.join(regime_renamed, how="left").dropna()
        else:
            full_df = alpha_df.copy()

        return full_df.ffill().dropna()
    except Exception as e:
        logger.warning("  Could not generate features for %s: %s", asset, e)
        return None


TICKER_MAP = {
    "GC": "GC=F",
    "USDCHF": "USDCHF=X",
    "USDCAD": "USDCAD=X",
    "ES": "ES=F",
    "NQ": "NQ=F",
    "GBPCAD": "GBPCAD=X",
    "NZDCAD": "NZDCAD=X",
    "^DJI": "^DJI",
    "NZDUSD": "NZDUSD=X",
    "GBPAUD": "GBPAUD=X",
    "NZDCHF": "NZDCHF=X",
    "CADCHF": "CADCHF=X",
    "AUDUSD": "AUDUSD=X",
    "EURCHF": "EURCHF=X",
    "EURCAD": "EURCAD=X",
    "EURNZD": "EURNZD=X",
    "GBPCHF": "GBPCHF=X",
    "GBPUSD": "GBPUSD=X",
    "EURAUD": "EURAUD=X",
    "USDJPY": "USDJPY=X",
    "GBPJPY": "GBPJPY=X",
}


# ── Main ────────────────────────────────────────────────────────────────────


def main():
    results = {}

    # ================================================================
    # 1. SYNTHETIC BASELINE
    # ================================================================
    print("=" * 80)
    print("INVESTIGATION 1: SYNTHETIC BASELINE PSI")
    print("=" * 80)
    print()
    print("Method: Generate a stationary AR(1) process (phi=0.95, no regime shift),")
    print("run a minimal walk-forward (expanding windows, 3 folds), compute PSI")
    print("between first and second halves of the p_long-like output.")
    print()

    np.random.seed(42)
    n_trials = 100
    baseline_psis = []

    for trial in range(n_trials):
        series = generate_synthetic_series(n=848, phi=0.95, seed=trial)
        p_long = run_synthetic_walk_forward(series)
        if len(p_long) < 40:
            continue
        mid = len(p_long) // 2
        psi = compute_psi(p_long.values[:mid], p_long.values[mid:])
        baseline_psis.append(psi)

    baseline_mean = np.mean(baseline_psis) if baseline_psis else 0.0
    baseline_std = np.std(baseline_psis) if baseline_psis else 0.0
    baseline_p95 = np.percentile(baseline_psis, 95) if baseline_psis else 0.0
    baseline_max = np.max(baseline_psis) if baseline_psis else 0.0

    print(f"Trials: {len(baseline_psis)}")
    print(f"Mean PSI under no-regime-shift: {baseline_mean:.4f}")
    print(f"Std PSI:                       {baseline_std:.4f}")
    print(f"95th percentile PSI:           {baseline_p95:.4f}")
    print(f"Max PSI observed:              {baseline_max:.4f}")
    print()
    print(f"Distribution of baseline PSI:")
    hist = np.histogram(baseline_psis, bins=10)
    for i in range(len(hist[1]) - 1):
        bar = "#" * int(hist[0][i] / max(hist[0]) * 30)
        print(f"  {hist[1][i]:.4f} - {hist[1][i + 1]:.4f}: {bar} ({int(hist[0][i])})")
    print()

    # Recommended threshold based on synthetic baseline
    # Mean + 2*std covers ~95% of no-regime-shift cases
    threshold_calibrated = round(baseline_mean + 2 * baseline_std, 4)
    print(f"Calibrated threshold (mean + 2*std): {threshold_calibrated}")
    print(f"Standard threshold (0.25):           0.2500")
    print(f"Ratio calibrated/standard:           {threshold_calibrated / 0.25:.2f}x")
    print()

    # Apply calibrated threshold to the 21 assets
    print("Assets exceeding calibrated threshold (>{:.4f}):".format(threshold_calibrated))
    from psi_sweep import compute_psi as psi_fn

    # Recompute with synthetic baseline comparison
    assets_psi = {}
    all_asset_list = [
        "GC",
        "USDCHF",
        "USDCAD",
        "ES",
        "NQ",
        "GBPCAD",
        "NZDCAD",
        "^DJI",
        "NZDUSD",
        "GBPAUD",
        "NZDCHF",
        "CADCHF",
        "AUDUSD",
        "EURCHF",
        "EURCAD",
        "EURNZD",
        "GBPCHF",
        "GBPUSD",
        "EURAUD",
        "USDJPY",
        "GBPJPY",
    ]

    for asset in all_asset_list:
        df = load_walkforward(asset)
        if df is None or len(df) < 40:
            continue
        p_long = df["p_long"].values
        mid = len(p_long) // 2
        psi = compute_psi(p_long[:mid], p_long[mid:])
        assets_psi[asset] = psi

    n_exceed = sum(1 for v in assets_psi.values() if v > threshold_calibrated)
    for asset, psi in sorted(assets_psi.items(), key=lambda x: -x[1]):
        flag = " ***" if psi > threshold_calibrated else ""
        print(f"  {asset:8s} PSI={psi:>8.4f} (>{threshold_calibrated} = {psi > threshold_calibrated}){flag}")
    print(f"Total exceeding calibrated threshold: {n_exceed}/{len(assets_psi)}")
    print()

    results["synthetic_baseline"] = {
        "n_trials": len(baseline_psis),
        "mean_psi": round(baseline_mean, 4),
        "std_psi": round(baseline_std, 4),
        "p95_psi": round(baseline_p95, 4),
        "max_psi": round(baseline_max, 4),
        "calibrated_threshold": threshold_calibrated,
        "standard_threshold": 0.25,
    }

    # ================================================================
    # 2. FEATURE-LEVEL PSI FOR TOP-3 OUTLIERS
    # ================================================================
    print()
    print("=" * 80)
    print("INVESTIGATION 2: FEATURE-LEVEL PSI FOR TOP-3 OUTLIERS")
    print("=" * 80)
    print()

    top_assets = ["EURAUD", "GBPAUD", "NZDCHF"]
    top_psis = {"EURAUD": 16.65, "GBPAUD": 7.94, "NZDCHF": 7.80}

    for i, asset in enumerate(top_assets):
        ticker = TICKER_MAP.get(asset)
        if ticker is None:
            print(f"{asset}: no ticker map — skipping")
            continue

        print(f"--- {asset} (output PSI={top_psis[asset]}) ---")
        features = generate_features(asset, ticker)

        if features is not None and len(features) >= 40:
            mid = len(features) // 2
            X_ref = features.iloc[:mid]
            X_actual = features.iloc[mid:]

            feature_psi = compute_feature_psi(X_ref, X_actual)

            # Print top-15 features by PSI
            print(f"  {'Feature':45s} {'PSI':10s} {'Severity':12s}")
            print(f"  {'-' * 67}")
            for feat, psi in sorted(feature_psi.items(), key=lambda x: -x[1])[:15]:
                if psi > PSI_MODERATE:
                    sev = "SIGNIFICANT"
                elif psi > PSI_STABLE:
                    sev = "moderate"
                else:
                    sev = "stable"
                print(f"  {feat:45s} {psi:>10.4f} {sev:>12s}")

            # Summary stats
            n_total = len(feature_psi)
            n_significant = sum(1 for v in feature_psi.values() if v > PSI_MODERATE)
            n_moderate = sum(1 for v in feature_psi.values() if PSI_STABLE < v <= PSI_MODERATE)
            n_stable = sum(1 for v in feature_psi.values() if v <= PSI_STABLE)
            max_psi_val = max(feature_psi.values())
            max_feat = max(feature_psi, key=feature_psi.get)

            print()
            print(
                f"  Summary: {n_total} features, {n_significant} significant, {n_moderate} moderate, {n_stable} stable"
            )
            print(f"  Max feature PSI: {max_feat} ({max_psi_val:.4f})")

            # Check for common high-PSI features across top-3
            if i == 0:
                common_features = set(feature_psi.keys())
                common_psi = dict(feature_psi)
            else:
                common_features &= set(feature_psi.keys())
                # Track which features are >0.25 in ALL top-3
                common_high_psi = {
                    f
                    for f in common_features
                    if feature_psi.get(f, 0) > PSI_MODERATE and common_psi.get(f, 0) > PSI_MODERATE
                }

            # Save
            out_path = OUTPUT_DIR / f"{asset}_feature_psi.json"
            with open(out_path, "w") as f:
                json.dump(feature_psi, f, indent=2)
            print(f"  Saved to {out_path}")
        else:
            print(f"  Could not generate features")

        print()

    # ================================================================
    # 3. CROSS-ASSET COMPARISON
    # ================================================================
    print("=" * 80)
    print("CROSS-ASSET COMPARISON: COMMON DRIVERS")
    print("=" * 80)
    print()

    # Load saved feature PSI files
    feature_psis = {}
    for asset in top_assets:
        p = OUTPUT_DIR / f"{asset}_feature_psi.json"
        if p.exists():
            with open(p) as f:
                feature_psis[asset] = json.load(f)

    # Load ES for comparison
    es_p = OUTPUT_DIR / "ES_feature_psi.json"
    if es_p.exists():
        with open(es_p) as f:
            feature_psis["ES"] = json.load(f)

    if len(feature_psis) >= 2:
        # Find features that are SIGNIFICANT in MULTIPLE assets
        all_features = set()
        for fp in feature_psis.values():
            all_features.update(fp.keys())

        # Count how many assets each feature is significant in
        feature_asset_count = {}
        for feat in all_features:
            count = sum(1 for fp in feature_psis.values() if fp.get(feat, 0) > PSI_MODERATE)
            if count >= 2:
                feature_asset_count[feat] = count

        if feature_asset_count:
            print("Features with PSI > 0.25 in 2+ of 4 assets (EURAUD, GBPAUD, NZDCHF, ES):")
            print()
            print(f"  {'Feature':45s} {'Assets':6s} {'EURAUD':8s} {'GBPAUD':8s} {'NZDCHF':8s} {'ES':8s}")
            print(f"  {'-' * 75}")
            for feat in sorted(feature_asset_count, key=lambda f: -feature_asset_count[f]):
                vals = [feature_psis.get(a, {}).get(feat, 0) for a in ["EURAUD", "GBPAUD", "NZDCHF", "ES"]]
                print(
                    f"  {feat:45s} {feature_asset_count[feat]:>6d} {vals[0]:>8.4f} {vals[1]:>8.4f} {vals[2]:>8.4f} {vals[3]:>8.4f}"
                )
        else:
            print("No features with PSI > 0.25 in 2+ assets.")
    else:
        print("Insufficient feature PSI data for cross-asset comparison.")

    # Save all results
    out_path = OUTPUT_DIR / "psi_deepdive_results.json"
    with open(out_path, "w") as f:
        json.dump(
            results
            | {
                "feature_psis": {
                    a: dict(sorted(fp.items(), key=lambda x: -x[1])[:20]) for a, fp in feature_psis.items()
                }
            },
            f,
            indent=2,
            cls=EigenCapitalJSONEncoder,
        )
    logger.info("Results saved to %s", out_path)


if __name__ == "__main__":
    main()
