import pandas as pd
import numpy as np
from features.base_features import generate_base_features
from features.regime_features import generate_regime_features
from features.structural_features import generate_structural_features
from features.interaction_features import generate_interaction_features
from features.cot_features import build_cot_features, EURUSD_COT_FEATURES
from labels.triple_barrier import apply_triple_barrier
from models.regime.regime_classifier import RegimeClassifier
from data.loaders.macro_loader import MACRO_FEATURES
from data.loaders.cot_loader import get_contract_series, align_cot_to_daily
from data.loaders.download_cot import download_all_years
import os

DAILY_PATH     = "data/raw/EURUSD_1d.parquet"
WEEKLY_PATH    = "data/raw/EURUSD_1w.parquet"
LABEL_PARAMS   = {'pt_sl': [2, 2], 'vertical_barrier': 8}
COT_RAW_PATH   = "data/processed/cot_raw.parquet"


def run_weekly_pipeline():
    print("=== WEEKLY DATA PIPELINE ===")

    price_daily = pd.read_parquet(DAILY_PATH)
    price_weekly = price_daily.resample('W-FRI').last()
    price_weekly['volume'] = price_daily['volume'].resample('W-FRI').sum()
    price_weekly.to_parquet(WEEKLY_PATH)
    print(f"Resampled: {len(price_daily)} daily -> {len(price_weekly)} weekly")

    labeled = apply_triple_barrier(price_weekly, **LABEL_PARAMS)
    labeled.to_parquet("data/processed/EURUSD_labeled_1w.parquet")
    print(f"Labels: {len(labeled)} rows  [{labeled['label'].value_counts(normalize=True).to_dict()}]")

    base_features = generate_base_features(price_weekly)
    base_features.to_parquet("data/processed/EURUSD_features_1w.parquet")
    print(f"Base features: {base_features.shape}")

    regime_raw = generate_regime_features(price_weekly)
    regime_raw.to_parquet("data/processed/EURUSD_regime_features_1w.parquet")
    print(f"Regime features (raw): {regime_raw.shape}")

    struct_features = generate_structural_features(price_weekly)
    struct_features.to_parquet("data/processed/EURUSD_structural_features_1w.parquet")
    print(f"Structural features: {struct_features.shape}")

    common = base_features.index.intersection(regime_raw.index).intersection(
        struct_features.index).intersection(labeled.index)
    print(f"Common index: {len(common)} rows")

    base_aligned   = base_features.loc[common]
    struct_aligned = struct_features.loc[common]
    labeled_aligned = labeled.loc[common]
    regime_raw_aligned = regime_raw.loc[common]

    classifier = RegimeClassifier(confidence_threshold=0.45)
    regime_out = classifier.classify(regime_raw_aligned)
    regime_out.to_parquet("data/processed/EURUSD_regime_labels_1w.parquet")
    print(f"Regime labels: {regime_out['regime'].value_counts().to_dict()}")

    interactions = generate_interaction_features(base_aligned, regime_out, struct_aligned)
    interactions.to_parquet("data/processed/EURUSD_interaction_features_1w.parquet")
    print(f"Interaction features: {interactions.shape}")

    macro_raw = pd.read_parquet("data/processed/macro_factors.parquet")

    macro_fn = lambda df: df.copy()
    macro_daily = macro_raw.copy()
    macro_daily = macro_daily.reindex(macro_daily.index).ffill()

    macro_daily['rate_diff'] = macro_daily['fed_funds'] - macro_daily['ecb_rate']
    macro_daily['yield_slope'] = macro_daily['us_10y'] - macro_daily['us_2y']
    macro_daily['dxy_mom_21'] = macro_daily['dxy'].pct_change(21, fill_method=None)
    macro_daily['dxy_mom_63'] = macro_daily['dxy'].pct_change(63, fill_method=None)
    macro_daily['fed_funds_delta_3m'] = macro_daily['fed_funds'].diff(90)
    macro_daily['rate_diff_delta_3m'] = macro_daily['rate_diff'].diff(90)

    if hasattr(common, 'tz') and common.tz is not None:
        macro_daily = macro_daily.tz_localize(common.tz)
    macro_weekly = macro_daily.reindex(common, method='ffill')
    macro_weekly.index = macro_weekly.index.normalize()
    macro_features = macro_weekly[MACRO_FEATURES].copy()
    macro_features.to_parquet("data/processed/macro_features_1w.parquet")
    print(f"Macro features: {macro_features.shape}")

    # COT data pipeline
    if not os.path.exists(COT_RAW_PATH):
        print("\nDownloading COT data...")
        download_all_years(path=COT_RAW_PATH)

    cot_raw = pd.read_parquet(COT_RAW_PATH)
    cot_series = get_contract_series(cot_raw, "EURUSD")
    if cot_series is not None and len(cot_series) > 0:
        cot_weekly_feats = build_cot_features(cot_series)
        cot_weekly_feats.to_parquet("data/processed/EURUSD_cot_features_1w.parquet")
        print(f"COT features (weekly): {cot_weekly_feats.shape}")

        cot_shifted = cot_weekly_feats.copy()
        cot_shifted.index = cot_series.index + pd.Timedelta(days=3)
        daily_cot = cot_shifted.reindex(macro_daily.index, method='ffill')
        daily_cot.index.name = 'date'
        daily_cot.to_parquet("data/processed/EURUSD_cot_daily.parquet")
        print(f"COT features (daily): {len(daily_cot)} rows")
    else:
        print("No COT data for EURUSD")

    print("\nDone. Files saved:")
    for f in ['EURUSD_labeled_1w', 'EURUSD_features_1w', 'EURUSD_regime_features_1w',
              'EURUSD_structural_features_1w', 'EURUSD_regime_labels_1w',
              'EURUSD_interaction_features_1w', 'macro_features_1w',
              'EURUSD_cot_features_1w', 'EURUSD_cot_daily']:
        print(f"  data/processed/{f}.parquet")


if __name__ == "__main__":
    run_weekly_pipeline()
