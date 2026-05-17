import pandas as pd
import numpy as np
import xgboost as xgb
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from labels.triple_barrier import apply_triple_barrier

TRAIN_START = "2017-05-16"
TRAIN_END = "2022-05-16"
TEST_START = "2022-05-17"
TEST_END = "2024-12-31"

EURUSD_COT_FEATURES = [
    "rate_diff",
    "eurusd_mom_63",
    "lev_net_cot_index",
    "lev_net_change_4w",
]

FEATURE_ALIASES = {
    "rate_diff": "Rate Diff (US - ECB)",
    "eurusd_mom_63": "EURUSD Momentum 63d",
    "lev_net_cot_index": "Leveraged Fund COT Index",
    "lev_net_change_4w": "Leveraged Fund Δ 4w",
}


def load_eurusd_data():
    price = pd.read_parquet("data/raw/EURUSD_1d.parquet")
    price.index = price.index.tz_localize(None)
    return price


def load_macro(price_index):
    raw = pd.read_parquet("data/processed/macro_factors.parquet")
    raw = raw.reindex(
        pd.date_range(raw.index.min(), raw.index.max(), freq="D")
    ).ffill()

    raw["rate_diff"] = raw["fed_funds"] - raw["ecb_rate"]

    aligned = raw.reindex(price_index, method="ffill")
    aligned.index = price_index
    return aligned


def load_cot(price_index):
    cot_raw = pd.read_parquet("data/processed/cot_raw.parquet")
    from data.loaders.cot_loader import get_contract_series, align_cot_to_daily
    from features.cot_features import build_cot_features

    cot_series = get_contract_series(cot_raw, "EURUSD")
    if cot_series is None:
        return None
    cot_feats = build_cot_features(cot_series)
    aligned = align_cot_to_daily(cot_feats, price_index)
    return aligned


def run_isolation_test():
    print("=" * 60)
    print("EURUSD COT Isolation Test — 2022 to 2024")
    print("=" * 60)

    price = load_eurusd_data()
    print(f"EURUSD: {len(price)} rows, {price.index[0].date()} to {price.index[-1].date()}")

    labeled = apply_triple_barrier(price, pt_sl=[2, 2], vertical_barrier=20)
    labeled["label_int"] = (labeled["label"] + 1).astype(int)

    macro = load_macro(labeled.index)
    cot = load_cot(labeled.index)

    df = macro.loc[labeled.index, ["rate_diff"]].copy()
    df["eurusd_mom_63"] = price["close"].reindex(labeled.index).pct_change(63)
    if cot is not None:
        for col in ["lev_net_cot_index", "lev_net_change_4w"]:
            df[col] = cot[col].reindex(labeled.index)

    df["label"] = labeled["label_int"]
    df = df.dropna(subset=EURUSD_COT_FEATURES + ["label"])

    train_mask = (df.index >= TRAIN_START) & (df.index <= TRAIN_END)
    test_mask = (df.index >= TEST_START) & (df.index <= TEST_END)

    X_train = df.loc[train_mask, EURUSD_COT_FEATURES].dropna()
    y_train = df.loc[X_train.index, "label"].astype(int)
    X_test = df.loc[test_mask, EURUSD_COT_FEATURES].dropna()
    y_test = df.loc[X_test.index, "label"].astype(int)

    print(f"\nTrain: {len(X_train)} rows, labels={sorted(y_train.unique())}")
    print(f"Test:  {len(X_test)} rows, labels={sorted(y_test.unique())}")

    model = xgb.XGBClassifier(
        n_estimators=300,
        max_depth=2,
        learning_rate=0.3,
        objective="multi:softprob",
        num_class=3,
        random_state=42,
        n_jobs=1,
        tree_method="hist",
        verbosity=0,
    )
    model.fit(X_train, y_train)
    proba = model.predict_proba(X_test)
    preds = model.predict(X_test)

    p_short = proba[:, 0]
    p_long = proba[:, 2]
    max_conf = np.maximum(p_short, p_long)

    n_long = int((preds == 2).sum())
    n_short = int((preds == 0).sum())
    n_neutral = int((preds == 1).sum())
    ls_ratio = n_long / max(n_short, 1)

    print(f"\n{' Metric':25s} {'Value':>10s}")
    print("-" * 36)
    print(f"{'P(short) mean':25s} {p_short.mean():>10.4f}")
    print(f"{'P(long) mean':25s} {p_long.mean():>10.4f}")
    print(f"{'Max confidence':25s} {max_conf.max():>10.4f}")
    print(f"{'Mean confidence':25s} {max_conf.mean():>10.4f}")
    print(f"{'Over 0.55':25s} {(max_conf > 0.55).sum():>4d}/{len(max_conf):<6d}")
    print(f"{'Over 0.50':25s} {(max_conf > 0.50).sum():>4d}/{len(max_conf):<6d}")
    print(f"{'Pred long':25s} {n_long:>10d}")
    print(f"{'Pred short':25s} {n_short:>10d}")
    print(f"{'Pred neutral':25s} {n_neutral:>10d}")
    print(f"{'L/S ratio':25s} {ls_ratio:>10.2f}")

    df_result = pd.DataFrame(
        {"P_short": p_short, "P_long": p_long, "pred": preds}, index=X_test.index
    )

    print(f"\n--- Yearly Breakdown ---")
    for yr in sorted(df_result.index.year.unique()):
        yd = df_result[df_result.index.year == yr]
        dl = int((yd["pred"] == 2).sum())
        ds = int((yd["pred"] == 0).sum())
        eurusd_ret = price.loc[yd.index, "close"].pct_change().sum()
        print(
            f"  {yr}: P(s)={yd['P_short'].mean():.4f}  P(l)={yd['P_long'].mean():.4f}  "
            f"L={dl:>3d}  S={ds:>3d}  L/S={dl/max(ds,1):.2f}  EURUSD={eurusd_ret:+.2%}"
        )

    print(f"\n--- Feature Importance ---")
    imp = pd.DataFrame(
        {
            "feature": EURUSD_COT_FEATURES,
            "importance": model.feature_importances_,
            "alias": [FEATURE_ALIASES[f] for f in EURUSD_COT_FEATURES],
        }
    ).sort_values("importance", ascending=False)
    for _, r in imp.iterrows():
        print(f'  {r["alias"]:30s} {r["importance"]:.3f}')

    print(f"\n--- Signal Direction Check ---")
    yr2022 = df_result[df_result.index.year == 2022]
    yr2023 = df_result[df_result.index.year == 2023]
    yr2024 = df_result[df_result.index.year == 2024]

    if len(yr2022) > 0:
        print(f"  2022: P(s)={yr2022['P_short'].mean():.4f}  P(l)={yr2022['P_long'].mean():.4f}  "
              f"(EURUSD fell ~14% in 2022 -> should bias short)")
    if len(yr2023) > 0:
        print(f"  2023: P(s)={yr2023['P_short'].mean():.4f}  P(l)={yr2023['P_long'].mean():.4f}  "
              f"(EURUSD rose ~3% in 2023 -> should bias long)")
    if len(yr2024) > 0:
        print(f"  2024: P(s)={yr2024['P_short'].mean():.4f}  P(l)={yr2024['P_long'].mean():.4f}")

    # Gate check: directional correctness
    if len(yr2022) > 0 and len(yr2023) > 0:
        gate_2022 = yr2022["P_short"].mean() > yr2022["P_long"].mean()
        gate_2023 = yr2023["P_long"].mean() > yr2023["P_short"].mean()
        print(f"\n{'GATE: 2022 P(s) > P(l)':30s} {'PASS' if gate_2022 else 'FAIL':>6s}")
        print(f"{'GATE: 2023 P(l) > P(s)':30s} {'PASS' if gate_2023 else 'FAIL':>6s}")
        passed = gate_2022 and gate_2023
        print(f"\n{'OVERALL GATE':30s} {'PASS' if passed else 'FAIL':>6s}")

    print(f"\n{'GATE: Max conf > 0.70':30s} {'PASS' if max_conf.max() > 0.70 else 'FAIL':>6s}")

    if max_conf.max() > 0.70 and ((len(yr2022) == 0 or gate_2022) and (len(yr2023) == 0 or gate_2023)):
        print("\n  COT signal confirmed. Proceed to walk-forward.")
    else:
        print("\n  Gate not fully cleared. Review feature forms.")

    return {"model": model, "X_test": X_test, "y_test": y_test, "proba": proba, "preds": preds}


if __name__ == "__main__":
    run_isolation_test()
