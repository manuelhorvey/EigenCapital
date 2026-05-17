"""EURUSD Hybrid Isolation Test: COT in MacroExpertHead via HybridRegimeEnsemble.

Tests whether feeding COT features through the MacroExpertHead (protected weight)
produces correct directional bias in 2022-2024 alongside price features.

Uses the original COT isolation split: train 2017-05-16 to 2022-05-16, test 2022-05-17 to 2024-12-31.

Gates:
  1. P(short) > P(long) in 2022 (USD strength cycle)
  2. P(long) > P(short) in 2023 (EUR recovery)
  3. max confidence > 0.65
  4. L/S ratio between 0.4:1 and 3:1
"""
import pandas as pd
import numpy as np
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from models.hybrid_ensemble import HybridRegimeEnsemble
from data.loaders.cot_loader import get_contract_series, align_cot_to_daily
from features.cot_features import build_cot_features

TRAIN_START = "2017-05-16"
TRAIN_END = "2022-05-16"
TEST_START = "2022-05-17"
TEST_END = "2024-12-31"

EURUSD_MACRO_FEATURES = [
    'rate_diff',
    'eurusd_mom_63',
    'lev_net_cot_index',
    'lev_net_change_4w',
    'commercial_to_lev_ratio',
]

MACRO_HEAD_CONFIG = {
    'features': EURUSD_MACRO_FEATURES,
    'model_params': {
        'learning_rate': 0.30,
        'max_depth': 2,
        'min_child_weight': 10,
        'n_estimators': 300,
    },
}


def load_price():
    df = pd.read_parquet("data/raw/EURUSD_1d.parquet")
    df.index = df.index.tz_localize(None)
    return df


def load_macro(price):
    m = pd.read_parquet("data/processed/macro_factors.parquet")
    m = m.reindex(pd.date_range(m.index.min(), m.index.max(), freq='D')).ffill()
    m = m.reindex(price.index, method='ffill')
    m['rate_diff'] = m['fed_funds'] - m['ecb_rate']
    m['eurusd_mom_63'] = price['close'].pct_change(fill_method=None)
    cot_raw = pd.read_parquet("data/processed/cot_raw.parquet")
    cot_series = get_contract_series(cot_raw, "EURUSD")
    if cot_series is not None:
        cot_feats = build_cot_features(cot_series)
        cot_aligned = align_cot_to_daily(cot_feats, price.index)
        for col in EURUSD_MACRO_FEATURES:
            if col in cot_aligned.columns:
                m[col] = cot_aligned[col].values
    return m


def run_isolation_test():
    print("=" * 60)
    print("EURUSD HYBRID Isolation Test — COT in MacroExpertHead")
    print("=" * 60)

    price = load_price()
    print(f"EURUSD: {len(price)} rows, {price.index[0].date()} to {price.index[-1].date()}")

    macro = load_macro(price)

    # Load pre-computed features (tz-aware)
    base = pd.read_parquet("data/processed/EURUSD_features.parquet")
    regime_meta = pd.read_parquet("data/processed/EURUSD_regime_labels.parquet")
    struct = pd.read_parquet("data/processed/EURUSD_structural_features.parquet")
    interact = pd.read_parquet("data/processed/EURUSD_interaction_features.parquet")
    labeled = pd.read_parquet("data/processed/EURUSD_labeled.parquet")

    # Align indices — strip tz from feature dataframes for intersection, then restore
    macro_idx_no_tz = macro.index
    feat_idx = base.index.tz_localize(None).intersection(
        regime_meta.index.tz_localize(None)).intersection(
        struct.index.tz_localize(None)).intersection(
        interact.index.tz_localize(None)).intersection(
        labeled.index.tz_localize(None))
    common_no_tz = feat_idx.intersection(macro_idx_no_tz)

    # Build X with tz-aware index
    common_tz = common_no_tz.tz_localize('Europe/London')
    X = pd.concat([
        base.loc[common_tz].drop('label', axis=1),
        regime_meta.loc[common_tz][['P_trend', 'P_range', 'P_volatile', 'regime_confidence']],
        struct.loc[common_tz],
        interact.loc[common_tz],
    ], axis=1)

    # Add macro and COT features (macro has no tz, so reindex by date only)
    for col in EURUSD_MACRO_FEATURES:
        X[col] = macro[col].reindex(common_no_tz).values

    y = labeled.loc[common_tz, 'label'] + 1
    regimes = regime_meta.loc[common_tz, 'regime']

    # Train/test split
    train_mask = (X.index >= TRAIN_START) & (X.index <= TRAIN_END)
    test_mask = (X.index >= TEST_START) & (X.index <= TEST_END)

    X_train = X[train_mask]
    y_train = y[train_mask]
    r_train = regimes[train_mask]
    X_test = X[test_mask]
    y_test = y[test_mask]
    r_test = regimes[test_mask]

    print(f"\nTrain: {len(X_train)} rows ({X_train.index[0].date()} to {X_train.index[-1].date()})")
    print(f"Test:  {len(X_test)} rows ({X_test.index[0].date()} to {X_test.index[-1].date()})")
    print(f"Regimes in train: {r_train.unique()}")

    # Train ensemble
    ensemble = HybridRegimeEnsemble(
        macro_feature_names=EURUSD_MACRO_FEATURES,
        macro_head_config=MACRO_HEAD_CONFIG,
    )
    print("\nTraining HybridRegimeEnsemble with COT-enhanced MacroExpertHead...")
    ensemble.train(X_train, y_train, r_train)

    proba = ensemble.predict_proba(X_test, r_test)
    preds = np.argmax(proba, axis=1)

    p_short = proba[:, 0]
    p_long = proba[:, 2]
    max_conf = np.maximum(p_short, p_long)

    n_long = int((preds == 2).sum())
    n_short = int((preds == 0).sum())
    n_neutral = int((preds == 1).sum())
    ls_ratio = n_long / max(n_short, 1)

    print(f"\n{' Metric':30s} {'Value':>10s}")
    print("-" * 42)
    print(f"{'P(short) mean':30s} {p_short.mean():>10.4f}")
    print(f"{'P(long) mean':30s} {p_long.mean():>10.4f}")
    print(f"{'Max confidence':30s} {max_conf.max():>10.4f}")
    print(f"{'Mean confidence':30s} {max_conf.mean():>10.4f}")
    print(f"{'Over 0.55':30s} {(max_conf > 0.55).sum():>4d}/{len(max_conf):<6d}")
    print(f"{'Over 0.50':30s} {(max_conf > 0.50).sum():>4d}/{len(max_conf):<6d}")
    print(f"{'Pred long':30s} {n_long:>10d}")
    print(f"{'Pred short':30s} {n_short:>10d}")
    print(f"{'Pred neutral':30s} {n_neutral:>10d}")
    print(f"{'L/S ratio':30s} {ls_ratio:>10.2f}")

    # Yearly breakdown
    df_result = pd.DataFrame({
        'P_short': p_short, 'P_long': p_long, 'pred': preds,
        'max_conf': max_conf,
    }, index=X_test.index)

    print(f"\n--- Yearly Breakdown ---")
    for yr in sorted(df_result.index.year.unique()):
        yd = df_result[df_result.index.year == yr]
        dl = int((yd['pred'] == 2).sum())
        ds = int((yd['pred'] == 0).sum())
        tz_mask = yd.index.tz_localize(None)
        eurusd_ret = price.loc[tz_mask, 'close'].pct_change().sum()
        print(
            f"  {yr}: P(s)={yd['P_short'].mean():.4f}  P(l)={yd['P_long'].mean():.4f}  "
            f"L={dl:>3d}  S={ds:>3d}  L/S={dl/max(ds,1):.2f}  EURUSD={eurusd_ret:+.2%}"
        )

    # Gate checks
    print(f"\n--- Gate Checks ---")
    yr2022 = df_result[df_result.index.year == 2022] if 2022 in df_result.index.year else pd.DataFrame()
    yr2023 = df_result[df_result.index.year == 2023] if 2023 in df_result.index.year else pd.DataFrame()

    gate_1 = len(yr2022) > 0 and yr2022['P_short'].mean() > yr2022['P_long'].mean()
    gate_2 = len(yr2023) > 0 and yr2023['P_long'].mean() > yr2023['P_short'].mean()
    gate_3 = max_conf.max() > 0.65
    gate_4 = 0.4 <= ls_ratio <= 3.0

    print(f"{'GATE 1: 2022 P(s) > P(l)':35s} {'PASS' if gate_1 else 'FAIL':>6s}")
    print(f"{'GATE 2: 2023 P(l) > P(s)':35s} {'PASS' if gate_2 else 'FAIL':>6s}")
    print(f"{'GATE 3: max confidence > 0.65':35s} {'PASS' if gate_3 else 'FAIL':>6s}")
    print(f"{'GATE 4: L/S ratio 0.4:1 to 3:1':35s} {'PASS' if gate_4 else 'FAIL':>6s}")

    all_pass = all([gate_1, gate_2, gate_3, gate_4])
    print(f"\n{'HYBRID ISOLATION GATE':35s} {'PASS' if all_pass else 'FAIL':>6s}")

    if all_pass:
        print("\n  Hybrid COT+macro integration confirmed. Proceed to walk-forward.")
    else:
        print("\n  Gate not fully cleared. Consider alternative COT feature forms.")

    return {'ensemble': ensemble, 'proba': proba, 'preds': preds, 'X_test': X_test, 'y_test': y_test}


if __name__ == "__main__":
    run_isolation_test()
