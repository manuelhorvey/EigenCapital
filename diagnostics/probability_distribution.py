import pandas as pd
import numpy as np
from models.hybrid_ensemble import HybridRegimeEnsemble
from signals.signal_generator import RegimeAwareSignalGenerator

DIAG_CONFIGS = [
    ("Without macro", False),
    ("With macro",    True),
]

EURUSD_DATA = {
    'base':         "data/processed/EURUSD_features.parquet",
    'regime_meta':  "data/processed/EURUSD_regime_labels.parquet",
    'struct':       "data/processed/EURUSD_structural_features.parquet",
    'interact':     "data/processed/EURUSD_interaction_features.parquet",
    'labeled':      "data/processed/EURUSD_labeled.parquet",
    'macro':        "data/processed/macro_features.parquet",
    'price':        "data/raw/EURUSD_1d.parquet",
}

TRAIN = ('2020-01-01', '2021-12-31')
TEST  = ('2022-01-01', '2024-12-31')


def load_data(with_macro: bool):
    base = pd.read_parquet(EURUSD_DATA['base'])
    regime_meta = pd.read_parquet(EURUSD_DATA['regime_meta'])
    struct = pd.read_parquet(EURUSD_DATA['struct'])
    interact = pd.read_parquet(EURUSD_DATA['interact'])
    labeled = pd.read_parquet(EURUSD_DATA['labeled'])
    data = pd.read_parquet(EURUSD_DATA['price'])
    returns = data['close'].pct_change()

    common_idx = base.index.intersection(regime_meta.index).intersection(
        struct.index).intersection(interact.index).intersection(labeled.index)

    parts = [
        base.loc[common_idx].drop('label', axis=1),
        regime_meta.loc[common_idx][['P_trend', 'P_range', 'P_volatile', 'regime_confidence']],
        struct.loc[common_idx],
        interact.loc[common_idx],
    ]

    if with_macro:
        macro = pd.read_parquet(EURUSD_DATA['macro'])
        macro_daily = macro.reindex(common_idx, method='ffill')
        macro_daily.index = macro_daily.index.normalize()
        parts.append(macro_daily)

    X = pd.concat(parts, axis=1)
    y = labeled.loc[common_idx, 'label'] + 1
    regimes = regime_meta.loc[common_idx, 'regime']
    regime_features = regime_meta.loc[common_idx]

    return X, y, regimes, regime_features, returns


def run_diagnostic(with_macro: bool, train_period: tuple, test_period: tuple):
    label = "WITH MACRO" if with_macro else "NO MACRO"
    print(f"\n{'='*60}")
    print(f"  {label}")
    print(f"{'='*60}")

    X, y, regimes, regime_features, returns = load_data(with_macro)

    train_mask = (X.index >= train_period[0]) & (X.index <= train_period[1])
    test_mask  = (X.index >= test_period[0])  & (X.index <= test_period[1])

    X_train, y_train, r_train = X[train_mask], y[train_mask], regimes[train_mask]
    X_test = X[test_mask]
    regime_features_test = regime_features.loc[X_test.index]

    print(f"  Train: {train_period} ({X_train.shape[0]} rows, {X_train.shape[1]} features)")
    print(f"  Test:  {test_period} ({X_test.shape[0]} rows)")

    ensemble = HybridRegimeEnsemble()
    ensemble.train(X_train, y_train, r_train)

    generator = RegimeAwareSignalGenerator(ensemble)
    signals = generator.generate_signals(X_test, regime_features_test)

    probs_short  = signals['raw_prob_short'].values
    probs_flat   = signals['raw_prob_neutral'].values
    probs_long   = signals['raw_prob_long'].values
    max_dir_conf = np.maximum(probs_short, probs_long)

    print(f"\n  Probability distribution on test set ({len(signals)} obs):")
    print(f"    P(short) mean={probs_short.mean():.4f}  std={probs_short.std():.4f}")
    print(f"    P(flat)  mean={probs_flat.mean():.4f}  std={probs_flat.std():.4f}")
    print(f"    P(long)  mean={probs_long.mean():.4f}  std={probs_long.std():.4f}")
    print(f"    Max dir conf — mean={max_dir_conf.mean():.4f}  median={np.median(max_dir_conf):.4f}  max={max_dir_conf.max():.4f}")
    print(f"    Above 0.65 threshold: {(max_dir_conf > 0.65).sum()} ({(max_dir_conf > 0.65).mean():.1%})")
    print(f"    Above 0.55 threshold: {(max_dir_conf > 0.55).sum()} ({(max_dir_conf > 0.55).mean():.1%})")

    trades = signals[signals['signal'] != 0]
    print(f"    Trades generated: {len(trades)}")
    if len(trades) > 0:
        print(f"    Long trades:  {(trades['signal'] == 1).sum()}")
        print(f"    Short trades: {(trades['signal'] == -1).sum()}")

    # Per-year breakdown within test window
    for yr in range(int(test_period[0][:4]), int(test_period[1][:4]) + 1):
        yr_idx = signals.index.year == yr
        yr_probs_short = signals.loc[yr_idx, 'raw_prob_short']
        yr_probs_long  = signals.loc[yr_idx, 'raw_prob_long']
        yr_dir_conf = np.maximum(yr_probs_short, yr_probs_long)
        yr_trades = (signals.loc[yr_idx, 'signal'] != 0).sum()
        print(f"    {yr}: mean_dir_conf={yr_dir_conf.mean():.4f}  "
              f"above_0.55={(yr_dir_conf > 0.55).sum()}  trades={yr_trades}")

    return signals


if __name__ == "__main__":
    signals_no  = run_diagnostic(False, TRAIN, TEST)
    signals_yes = run_diagnostic(True,  TRAIN, TEST)

    print("\n" + "="*60)
    print("  DIAGNOSIS")
    print("="*60)

    for config in DIAG_CONFIGS:
        label, with_macro = config
        sigs = signals_yes if with_macro else signals_no
        max_dir = np.maximum(sigs['raw_prob_short'], sigs['raw_prob_long'])
        mean_conf = max_dir.mean()
        trades = (sigs['signal'] != 0).sum()

        if trades < 20:
            case = "A — Macro features increased uncertainty (probabilities dispersed)"
        elif mean_conf > 0.50:
            case = "B — Macro features increased confidence but wrong direction"
        else:
            case = "A — General low confidence across test period"

        print(f"\n  {label}: {case}")

    print("\n  Threshold check for 0.55 vs 0.65:")
    for label, with_macro in DIAG_CONFIGS:
        sigs = signals_yes if with_macro else signals_no
        max_dir = np.maximum(sigs['raw_prob_short'], sigs['raw_prob_long'])
        for thresh in [0.55, 0.60, 0.65, 0.70]:
            n = (max_dir > thresh).sum()
            print(f"    {label:15s}  > {thresh:.2f}: {n:4d} trades")
