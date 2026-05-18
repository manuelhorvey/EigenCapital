"""GC=F walk-forward with fwd60 label — strongest isolation variant.

Features: real_yield_delta_63, breakeven_delta_63, dxy_mom_63, gc_mom_63
Label:    fwd60
"""
import logging, os, sys, pickle
import pandas as pd
import numpy as np
import xgboost as xgb

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(__file__))))
from scripts.train_all_assets import fetch_history, load_macro

logging.basicConfig(level=logging.INFO, format='%(asctime)s [%(levelname)s] %(message)s')
logger = logging.getLogger('gc_wf')

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
GC = "GC=F"

FWD60_THRESHOLD = 0.02
CONF_THRESHOLD = 0.45
TRAIN_YEARS = 5
TEST_YEARS = 1
STEP_YEARS = 1
MIN_TRADES = 10

FEATURES = [
    'real_yield_delta_63',
    'breakeven_delta_63',
    'dxy_mom_63',
    'gc_mom_63',
]


def compute_fwd60_labels(df):
    ret = df['close'].pct_change(60).shift(-60)
    labels = ret.apply(
        lambda x: 2 if x > FWD60_THRESHOLD else (0 if x < -FWD60_THRESHOLD else 1)
    ).astype(int)
    return labels


def compute_features_gc(df, macro):
    labels = compute_fwd60_labels(df)
    labeled = pd.DataFrame({'label': labels}).dropna()
    pi = pd.DatetimeIndex([pd.Timestamp(x).tz_localize(None) for x in labeled.index])
    a = macro.reindex(pi, method='ffill')
    a.index = labeled.index
    a['real_yield_delta_63'] = a['real_yield_10y'].diff(63)
    a['breakeven_delta_63'] = a['breakeven_10y'].diff(63)
    a['dxy_mom_63'] = a['dxy'].pct_change(63)
    a['gc_mom_63'] = df['close'].pct_change(63)
    a['label'] = labeled['label']
    return a.dropna(subset=FEATURES + ['label'])


def bootstrap_pvalues(pnl_series, n_iter=500):
    rng = np.random.default_rng(42)
    n = len(pnl_series)
    if n < 5:
        return 1.0
    boot_medians = np.array([
        pnl_series.sample(n=n, replace=True, random_state=int(i)).median()
        for i in rng.integers(0, 2**31, size=n_iter)
    ])
    return float((boot_medians <= 0).mean())


def walk_forward():
    logger.info('Loading data...')
    macro = load_macro()
    df = fetch_history(GC)

    logger.info('Computing fwd60 features...')
    features_df = compute_features_gc(df, macro)
    logger.info('  %d feature rows', len(features_df))

    closes = df['close'].reindex(features_df.index)
    returns = closes.pct_change().shift(-1)

    years = sorted(features_df.index.year.unique())
    start_year = years[0]
    end_year = years[-1]
    logger.info('  Years: %d-%d', start_year, end_year)

    windows = []
    for oos_year in range(start_year + TRAIN_YEARS, end_year + 1, STEP_YEARS):
        train_start = oos_year - TRAIN_YEARS
        train_end = oos_year - 1

        train_mask = (features_df.index.year >= train_start) & (features_df.index.year <= train_end)
        oos_mask = features_df.index.year == oos_year

        X_train = features_df.loc[train_mask, FEATURES]
        y_train = features_df.loc[train_mask, 'label'].astype(int)
        X_oos = features_df.loc[oos_mask, FEATURES]
        y_oos = features_df.loc[oos_mask, 'label'].astype(int)

        if len(X_oos) == 0 or len(X_train) < 200:
            continue

        label_dist = y_train.value_counts(normalize=True)
        if label_dist.min() < 0.05:
            logger.warning('    Skipping %d: label imbalance min_class=%.1f%%',
                          oos_year, label_dist.min() * 100)
            continue

        model = xgb.XGBClassifier(
            n_estimators=300, max_depth=2, learning_rate=0.02,
            objective='multi:softprob', num_class=3,
            random_state=42, n_jobs=1, tree_method='hist', verbosity=0,
        )
        model.fit(X_train, y_train)

        proba = model.predict_proba(X_oos)
        prob_long = proba[:, 2]
        prob_short = proba[:, 0]

        signals = pd.Series(0, index=X_oos.index)
        signals[prob_long > CONF_THRESHOLD] = 2
        signals[prob_short > CONF_THRESHOLD] = 0

        oos_returns = returns.loc[X_oos.index]
        pnl = pd.Series(0.0, index=X_oos.index)
        active = signals != 0
        direction = np.where(signals == 2, 1, np.where(signals == 0, -1, 0))
        pnl[active] = direction[active] * oos_returns[active]

        trades = pnl[pnl != 0]
        n_trades = len(trades)
        total_pnl = float(pnl.sum())
        wins = trades[trades > 0]
        losses = trades[trades < 0]
        win_rate = len(wins) / n_trades if n_trades > 0 else 0
        avg_win = float(wins.mean()) if not wins.empty else 0
        avg_loss = float(abs(losses.mean())) if not losses.empty else 0
        expectancy = (win_rate * avg_win) - ((1 - win_rate) * avg_loss) if n_trades > 0 else 0
        profit_factor = float(wins.sum() / abs(losses.sum())) if not losses.empty and losses.sum() != 0 else 0.0
        profit_factor = min(profit_factor, 100.0)
        daily_vol = float(pnl.std() * np.sqrt(252))
        sharpe = float(pnl.mean() / pnl.std() * np.sqrt(252)) if pnl.std() > 0 else 0
        bp = bootstrap_pvalues(pnl[pnl != 0]) if n_trades > 0 else 1.0

        windows.append({
            'window': oos_year,
            'n_trades': n_trades,
            'win_rate': round(win_rate, 4),
            'avg_win': round(avg_win, 6),
            'avg_loss': round(avg_loss, 6),
            'expectancy': round(expectancy, 6),
            'profit_factor': round(profit_factor, 3),
            'sharpe': round(sharpe, 3),
            'total_return': round(total_pnl, 6),
            'daily_vol': round(daily_vol, 6),
            'bootstrap_p': round(bp, 4),
            'n_train': len(X_train),
            'n_test': len(X_oos),
        })
        logger.info('  [%d]: trades=%d win=%.0f%% exp=%.6f pf=%.2f sharpe=%.3f p=%.3f',
                     oos_year, n_trades, win_rate*100, expectancy, profit_factor, sharpe, bp)

    if not windows:
        logger.error('No valid windows.')
        return

    df_w = pd.DataFrame(windows)

    print('\n')
    print('=' * 110)
    print('GC=F FWD60 WALK-FORWARD')
    print('=' * 110)
    print(f'Label:       fwd60 (threshold={FWD60_THRESHOLD})')
    print(f'Features:    {FEATURES}')
    print(f'Train:       {TRAIN_YEARS}yr windows, step {STEP_YEARS}yr')
    print(f'Confidence:  {CONF_THRESHOLD}')
    print()

    header = f'{"Win":>6s}  {"Trades":>6s}  {"WinRate":>7s}  {"Exp":>10s}  {"PF":>7s}  {"Sharpe":>7s}  {"Ret":>10s}  {"Vol":>9s}  {"p-value":>7s}'
    print(header)
    print('-' * len(header))

    n_positive_pf = 0
    for _, r in df_w.iterrows():
        w = int(r['window'])
        nt = int(r['n_trades'])
        pf_ok = r['profit_factor'] > 1.10
        sign = '✓' if pf_ok else ' '
        print(f'{sign} {w:>4d}  {nt:>6d}  {r["win_rate"]:>7.2%}  '
              f'{r["expectancy"]:>10.6f}  {r["profit_factor"]:>7.3f}  '
              f'{r["sharpe"]:>7.3f}  {r["total_return"]:>10.6f}  '
              f'{r["daily_vol"]:>9.6f}  {r["bootstrap_p"]:>7.4f}')
        if pf_ok:
            n_positive_pf += 1

    print()
    print('--- Summary ---')
    pf_values = df_w['profit_factor'].replace(0, np.nan)
    print(f'  Windows:             {len(df_w)}')
    print(f'  Avg trades/window:   {df_w["n_trades"].mean():.0f}')
    print(f'  Avg expectancy:      {df_w["expectancy"].mean():.6f}')
    print(f'  Median PF:           {pf_values.median():.3f}')
    print(f'  Avg Sharpe:          {df_w["sharpe"].mean():.3f}')
    print(f'  Windows PF > 1.10:   {n_positive_pf}/{len(df_w)}')
    print(f'  Windows PF > 1.0:    {(df_w["profit_factor"] > 1.0).sum()}/{len(df_w)}')
    print(f'  Windows pos Sharpe:  {(df_w["sharpe"] > 0).sum()}/{len(df_w)}')
    print(f'  Windows p < 0.20:    {(df_w["bootstrap_p"] < 0.20).sum()}/{len(df_w)}')
    print(f'  Total return:        {df_w["total_return"].sum():.6f}')

    min_pf = pf_values.min()
    max_dd = df_w['total_return'].min()
    print()
    print(f'  Gates:')
    print(f'    PF > 1.10:         {"✅" if n_positive_pf >= 5 else "❌"} ({n_positive_pf}/{len(df_w)})')
    print(f'    Bootstrap p<0.20:  {"✅" if (df_w["bootstrap_p"] < 0.20).sum() >= 5 else "❌"} ({(df_w["bootstrap_p"] < 0.20).sum()}/{len(df_w)})')
    print(f'    Min PF > 0.70:     {"✅" if min_pf > 0.70 else "❌"} (min={min_pf:.3f})')

    os.makedirs(os.path.join(BASE, 'data', 'processed'), exist_ok=True)
    out_path = os.path.join(BASE, 'data', 'processed', 'gc_walkforward_results.csv')
    df_w.to_csv(out_path, index=False)
    logger.info('Results saved to %s', out_path)


if __name__ == '__main__':
    walk_forward()
