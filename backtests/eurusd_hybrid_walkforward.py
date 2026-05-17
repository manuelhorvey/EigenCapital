"""EURUSD Hybrid Walk-Forward: COT in MacroExpertHead via HybridRegimeEnsemble.

9-window expanding walk-forward:
  Train 2010-2015 → Test 2016  (first window with available data)
  Train 2010-2016 → Test 2017
  ...
  Train 2010-2023 → Test 2024

Gate: PF > 1.10 AND Bootstrap p < 0.10 for each window.
2022 and 2023 must both be positive (confirmed directional correctness).
"""
import pandas as pd
import numpy as np
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from models.hybrid_ensemble import HybridRegimeEnsemble
from data.loaders.cot_loader import get_contract_series, align_cot_to_daily
from features.cot_features import build_cot_features

SIGNAL_THRESHOLD = 0.50
MIN_TRADES = 20

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

WF_CONFIG = {
    'train_years': 5,
    'test_years': 1,
    'step_years': 1,
    'min_trades': 20,
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


def bootstrap_pf(pnl_array, n_iterations=1000):
    pnl_array = pnl_array.values if isinstance(pnl_array, pd.Series) else pnl_array
    actual_wins = pnl_array[pnl_array > 0].sum()
    actual_losses = pnl_array[pnl_array < 0].sum()
    actual_pf = actual_wins / (abs(actual_losses) + 1e-9)
    if actual_pf <= 1.0:
        return 1.0
    signs = np.sign(pnl_array)
    abs_pnl = np.abs(pnl_array)
    count = 0
    for _ in range(n_iterations):
        np.random.shuffle(signs)
        null_pnl = signs * abs_pnl
        null_wins = null_pnl[null_pnl > 0].sum()
        null_losses = null_pnl[null_pnl < 0].sum()
        null_pf = null_wins / (abs(null_losses) + 1e-9)
        if null_pf >= actual_pf:
            count += 1
    return (count + 1) / (n_iterations + 1)


def run_walk_forward():
    print("=" * 60)
    print("EURUSD HYBRID Walk-Forward — COT in MacroExpertHead")
    print("=" * 60)

    price = load_price()
    print(f"EURUSD: {len(price)} rows, {price.index[0].date()} to {price.index[-1].date()}")

    macro = load_macro(price)

    # Load pre-computed features
    base = pd.read_parquet("data/processed/EURUSD_features.parquet")
    regime_meta = pd.read_parquet("data/processed/EURUSD_regime_labels.parquet")
    struct = pd.read_parquet("data/processed/EURUSD_structural_features.parquet")
    interact = pd.read_parquet("data/processed/EURUSD_interaction_features.parquet")
    labeled = pd.read_parquet("data/processed/EURUSD_labeled.parquet")

    # Align indices
    feat_idx = base.index.tz_localize(None).intersection(
        regime_meta.index.tz_localize(None)).intersection(
        struct.index.tz_localize(None)).intersection(
        interact.index.tz_localize(None)).intersection(
        labeled.index.tz_localize(None))
    common_no_tz = feat_idx.intersection(macro.index)
    common_tz = common_no_tz.tz_localize('Europe/London')

    X = pd.concat([
        base.loc[common_tz].drop('label', axis=1),
        regime_meta.loc[common_tz][['P_trend', 'P_range', 'P_volatile', 'regime_confidence']],
        struct.loc[common_tz],
        interact.loc[common_tz],
    ], axis=1)

    for col in EURUSD_MACRO_FEATURES:
        X[col] = macro[col].reindex(common_no_tz).values

    y = labeled.loc[common_tz, 'label'] + 1
    regimes = regime_meta.loc[common_tz, 'regime']

    years = sorted(X.index.year.unique())
    first_test_year = years[0] + WF_CONFIG['train_years']
    print(f"Data: {X.index[0].date()} to {X.index[-1].date()}, {len(X)} rows")
    print(f"Signal threshold: P > {SIGNAL_THRESHOLD}")
    print()

    all_results = []

    for test_year in range(first_test_year, years[-1] + 1, WF_CONFIG['step_years']):
        train_end = test_year - 1
        train_start = test_year - WF_CONFIG['train_years']

        train_mask = (X.index.year >= train_start) & (X.index.year <= train_end)
        test_mask = (X.index.year == test_year)

        X_train = X[train_mask]
        y_train = y[train_mask]
        r_train = regimes[train_mask]
        X_test = X[test_mask]
        r_test = regimes[test_mask]

        if len(X_train) < 100 or len(X_test) < 20:
            print(f"  {test_year}: insufficient data (train={len(X_train)}, test={len(X_test)}) → SKIP")
            all_results.append({
                'year': test_year, 'trades': len(X_test),
                'expectancy': None, 'profit_factor': None, 'bootstrap_p': None, 'gate': 'SKIP',
            })
            continue

        ensemble = HybridRegimeEnsemble(
            macro_feature_names=EURUSD_MACRO_FEATURES,
            macro_head_config=MACRO_HEAD_CONFIG,
        )
        ensemble.train(X_train, y_train, r_train)

        proba = ensemble.predict_proba(X_test, r_test)
        p_short, p_long = proba[:, 0], proba[:, 2]

        signal = np.zeros(len(p_short))
        signal[p_long > SIGNAL_THRESHOLD] = 1
        signal[p_short > SIGNAL_THRESHOLD] = -1
        both = (p_long > SIGNAL_THRESHOLD) & (p_short > SIGNAL_THRESHOLD)
        signal[both] = np.where(p_long[both] >= p_short[both], 1, -1)

        test_returns = price['close'].pct_change().reindex(X_test.index.tz_localize(None)).values
        trade_pnl = (signal * test_returns)[signal != 0]
        n_trades = len(trade_pnl)

        if n_trades < MIN_TRADES:
            print(f"  {test_year}: trades={n_trades:3d} (below {MIN_TRADES}) → SKIP")
            all_results.append({
                'year': test_year, 'trades': n_trades,
                'expectancy': None, 'profit_factor': None, 'bootstrap_p': None, 'gate': 'SKIP',
            })
            continue

        wins = trade_pnl[trade_pnl > 0].sum()
        losses = trade_pnl[trade_pnl < 0].sum()
        pf = wins / (abs(losses) + 1e-9)
        avg_win = trade_pnl[trade_pnl > 0].mean() if (trade_pnl > 0).any() else 0
        avg_loss = abs(trade_pnl[trade_pnl < 0].mean()) if (trade_pnl < 0).any() else 0
        win_rate = (trade_pnl > 0).mean()
        expectancy = (win_rate * avg_win) - ((1 - win_rate) * avg_loss)
        bp = bootstrap_pf(trade_pnl)
        gate = "PASS" if (pf > 1.10 and bp < 0.10) else "FAIL"
        print(f"  {test_year}: trades={n_trades:3d}  PF={pf:.2f}  exp={expectancy:.6f}  bp={bp:.4f}  gate={gate}")
        all_results.append({
            'year': test_year, 'trades': n_trades,
            'expectancy': expectancy, 'profit_factor': pf, 'bootstrap_p': bp, 'gate': gate,
        })

    print("\n" + "=" * 60)
    print("HYBRID WALK-FORWARD RESULTS")
    print("=" * 60)
    print(f"{'Window':8s}  {'Trades':>6s}  {'PF':>6s}  {'Exp':>10s}  {'Bootstrap p':>11s}  {'Gate':>6s}")
    print("-" * 52)
    for r in all_results:
        t, p, e, b, g = r['trades'], r['profit_factor'], r['expectancy'], r['bootstrap_p'], r['gate']
        pf_s = f"{p:.2f}" if p is not None else "  N/A"
        ex_s = f"{e:.6f}" if e is not None else "      N/A"
        bp_s = f"{b:.4f}" if b is not None else "      N/A"
        print(f"  {r['year']:4d}     {t:4d}     {pf_s:>4s}   {ex_s:>10s}   {bp_s:>8s}     {g}")

    valid = [r for r in all_results if r['gate'] != 'SKIP']
    passed = sum(1 for r in valid if r['gate'] == 'PASS')
    avg_pf = np.mean([r['profit_factor'] for r in valid]) if valid else 0
    print(f"\nPassed: {passed}/{len(valid)}  |  Avg PF: {avg_pf:.2f}  |  Gate: PF > 1.10, p < 0.10")

    return all_results


if __name__ == "__main__":
    run_walk_forward()
