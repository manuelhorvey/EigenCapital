import logging
import os
import sys

import numpy as np
import pandas as pd
import xgboost as xgb

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(__file__))))
from features.builder import build_features, compute_macro_derived
from features.registry import FEATURE_REGISTRY
from labels.triple_barrier import apply_triple_barrier
from scripts.training.train_all_assets import fetch_history

TICKERS = list(FEATURE_REGISTRY.keys())


def _slug(ticker: str) -> str:
    return ticker.replace('=', '').replace('-', '_').lower()


def compute_features(df, ref, macro, ticker):
    """Build feature DataFrame WITHOUT labels to prevent year-boundary label leakage.

    Labels are computed per-fold inside the walk-forward loop so the
    triple-barrier lookahead window never crosses the train/test boundary.
    """
    contract = FEATURE_REGISTRY[ticker]
    fdf = build_features(df, macro, ref, contract, compute_labels=False)
    return fdf, list(contract.features)


def load_macro():
    path = os.path.join(BASE, 'data', 'processed', 'macro_factors.parquet')
    m = pd.read_parquet(path)
    return compute_macro_derived(m)

logging.basicConfig(level=logging.INFO, format='%(asctime)s [%(levelname)s] %(message)s')
logger = logging.getLogger('walkforward')

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def walk_forward_one(ticker, macro, ref, window_years=3, step_years=1, conf_threshold=0.45):
    slug = _slug(ticker)
    logger.info('  %s: downloading history...', ticker)
    df = fetch_history(ticker)
    features_df, feats = compute_features(df, ref, macro, ticker)
    logger.info('  %s: %d feature rows, features=%s', ticker, len(features_df), feats)

    if len(features_df) < 500:
        logger.warning('  %s: insufficient data (%d rows), skipping', ticker, len(features_df))
        return None

    # Strip tz from close to match features_df's tz-unaware index (build_features
    # returns tz-unaware in the inference path).  Use .copy() to avoid mutating df.
    close_series = df['close'].copy()
    if close_series.index.tz is not None:
        close_series.index = close_series.index.tz_localize(None)
    closes = close_series.reindex(features_df.index)
    returns = closes.pct_change().shift(-1)
    years = sorted(features_df.index.year.unique())
    start_year = years[0]
    end_year = years[-1]

    contract = FEATURE_REGISTRY[ticker]
    label_params = contract.label_params
    pt_sl = label_params.get("pt_sl", [2.0, 2.0])
    vb = label_params.get("vertical_barrier", 20)

    windows = []
    for current_year in range(start_year + window_years, end_year + 1, step_years):
        train_end = current_year - 1
        oos_year = current_year

        train_mask = features_df.index.year <= train_end
        oos_mask = features_df.index.year == oos_year

        X_train = features_df.loc[train_mask, feats]
        X_oos = features_df.loc[oos_mask, feats]

        if len(X_oos) == 0 or len(X_train) < 200:
            continue

        # Compute labels per-fold to avoid year-boundary lookahead leakage.
        # Expand training close by vertical_barrier rows past train_end so
        # triple-barrier labels have a complete lookahead window.
        train_close = closes.loc[train_mask]
        train_extended_end = min(len(closes), train_mask.sum() + vb)
        train_close_ext = closes.iloc[:train_extended_end].to_frame("close")
        train_labels = apply_triple_barrier(train_close_ext, pt_sl=pt_sl, vertical_barrier=vb)
        if train_labels is not None and not train_labels.empty:
            y_train = train_labels.reindex(train_close.index)['label'].dropna().astype(int)
            # Triple-barrier labels are -1/0/1; XGBoost multi:softprob expects 0/1/2
            y_train = (y_train + 1).astype(int)
        else:
            y_train = pd.Series(dtype=int)
        train_valid = y_train.index.intersection(X_train.index)
        X_train = X_train.loc[train_valid]
        y_train = y_train.loc[train_valid]

        # OOS labels: extend close by vb rows past OOS for complete lookahead.
        oos_close = closes.loc[oos_mask]
        oos_extended_end = min(len(closes), oos_mask.sum() + vb + train_mask.sum())
        oos_close_ext = closes.iloc[train_mask.sum():oos_extended_end].to_frame("close")
        oos_labels = apply_triple_barrier(oos_close_ext, pt_sl=pt_sl, vertical_barrier=vb)
        if oos_labels is not None and not oos_labels.empty:
            y_oos = oos_labels.reindex(oos_close.index)['label'].dropna().astype(int)
            # Triple-barrier labels are -1/0/1; XGBoost multi:softprob expects 0/1/2
            y_oos = (y_oos + 1).astype(int)
        else:
            y_oos = pd.Series(dtype=int)
        oos_valid = y_oos.index.intersection(X_oos.index)
        X_oos = X_oos.loc[oos_valid]
        y_oos = y_oos.loc[oos_valid]

        if len(y_oos) == 0 or len(y_train) < 200:
            continue

        # XGBoost multi:softprob requires all 3 label classes present in training
        if len(np.unique(y_train)) < 3:
            logger.warning('  %s [%d]: not all 3 label classes in train, skipping', ticker, oos_year)
            continue

        model = xgb.XGBClassifier(
            n_estimators=300, max_depth=2, learning_rate=0.02,
            objective='multi:softprob', num_class=3,
            random_state=42, n_jobs=1, tree_method='hist', verbosity=0,
        )
        model.fit(X_train, y_train, eval_set=[(X_oos, y_oos)], verbose=False)

        proba = model.predict_proba(X_oos)
        prob_long = proba[:, 2]
        prob_short = proba[:, 0]

        signals = pd.Series(0, index=X_oos.index)
        signals[prob_long > conf_threshold] = 2
        signals[prob_short > conf_threshold] = 1

        oos_returns = returns.loc[X_oos.index]
        pnl = pd.Series(0.0, index=X_oos.index)
        active = signals != 0
        direction = np.where(signals == 2, 1, np.where(signals == 1, -1, 0))
        pnl[active] = direction[active] * oos_returns[active]

        trades = pnl[pnl != 0]
        n_trades = len(trades)
        total_pnl = pnl.sum()
        wins = trades[trades > 0]
        losses = trades[trades < 0]
        win_rate = len(wins) / n_trades if n_trades > 0 else 0
        avg_win = wins.mean() if not wins.empty else 0
        avg_loss = abs(losses.mean()) if not losses.empty else 0
        expectancy = (win_rate * avg_win) - ((1 - win_rate) * avg_loss) if n_trades > 0 else 0
        profit_factor = wins.sum() / abs(losses.sum()) if not losses.empty and losses.sum() != 0 else 0.0
        profit_factor = min(profit_factor, 100.0) if profit_factor > 0 else 0.0
        daily_vol = pnl.std() * np.sqrt(252)
        sharpe = pnl.mean() / pnl.std() * np.sqrt(252) if pnl.std() > 0 else 0

        windows.append({
            'ticker': ticker,
            'window': oos_year,
            'n_trades': n_trades,
            'win_rate': round(win_rate, 4),
            'expectancy': round(expectancy, 6),
            'profit_factor': round(profit_factor, 2),
            'sharpe': round(sharpe, 3),
            'total_return': round(total_pnl, 6),
            'daily_vol': round(daily_vol, 6),
            'n_train': len(X_train),
            'n_test': len(X_oos),
        })
        logger.info('  %s [%d]: trades=%d win=%.2f%% exp=%.6f pf=%.2f sharpe=%.3f',
                     ticker, oos_year, n_trades, win_rate*100, expectancy, profit_factor, sharpe)

    if not windows:
        return None

    df_windows = pd.DataFrame(windows)
    pf_values = df_windows['profit_factor'].replace(0, np.nan)
    summary = {
        'ticker': ticker,
        'n_windows': len(df_windows),
        'avg_expectancy': df_windows['expectancy'].mean(),
        'std_expectancy': df_windows['expectancy'].std(),
        'avg_win_rate': df_windows['win_rate'].mean(),
        'avg_profit_factor': pf_values.mean() if pf_values.notna().any() else 0.0,
        'median_profit_factor': pf_values.median() if pf_values.notna().any() else 0.0,
        'avg_sharpe': df_windows['sharpe'].mean(),
        'avg_trades_per_window': df_windows['n_trades'].mean(),
        'pct_positive_exp': (df_windows['expectancy'] > 0).mean(),
        'pct_profitable': (df_windows['profit_factor'] > 1.0).mean(),
        'total_return_all': df_windows['total_return'].sum(),
    }
    return df_windows, summary


def main():
    logger.info('Loading macro data...')
    macro = load_macro()
    ref = fetch_history('SPY', years=10)

    all_summaries = []
    all_windows = []

    for ticker in TICKERS:
        try:
            result = walk_forward_one(ticker, macro, ref)
            if result is None:
                logger.warning('  ✗ %s: walk-forward failed', ticker)
                continue
            df_w, summary = result
            all_windows.append(df_w)
            all_summaries.append(summary)
            logger.info('  ✓ %s: avg_exp=%.6f avg_pf=%.2f avg_sharpe=%.3f pos_windows=%.0f%%',
                         ticker, summary['avg_expectancy'], summary['avg_profit_factor'],
                         summary['avg_sharpe'], summary['pct_profitable']*100)
        except Exception as e:
            logger.error('  ✗ %s: error: %s', ticker, e)
            import traceback; traceback.print_exc()

    if not all_summaries:
        print('No results.')
        return

    summary_df = pd.DataFrame(all_summaries).sort_values('avg_expectancy', ascending=False)
    windows_df = pd.concat(all_windows, ignore_index=True)

    print('\n' + '=' * 100)
    print('WALK-FORWARD SUMMARY (sorted by avg expectancy)')
    print('=' * 100)
    cols = ['ticker', 'n_windows', 'avg_expectancy', 'std_expectancy',
            'avg_win_rate', 'avg_profit_factor', 'avg_sharpe',
            'avg_trades_per_window', 'pct_positive_exp', 'pct_profitable']
    print(f'{"Ticker":>10s}  {"Win":>4s}  {"AvgExp":>10s}  {"StdExp":>10s}  '
          f'{"WinRate":>8s}  {"AvgPF":>7s}  {"Sharpe":>7s}  {"Trades":>6s}  '
          f'{"Pos%":>5s}  {"Prof%":>5s}')
    print('-' * 100)
    for _, r in summary_df.iterrows():
        print(f'{r["ticker"]:>10s}  {int(r["n_windows"]):>4d}  '
              f'{r["avg_expectancy"]:>10.6f}  {r["std_expectancy"]:>10.6f}  '
              f'{r["avg_win_rate"]:>8.4f}  {r["avg_profit_factor"]:>7.2f}  '
              f'{r["avg_sharpe"]:>7.3f}  {int(r["avg_trades_per_window"]):>6d}  '
              f'{r["pct_positive_exp"]:>5.0%}  {r["pct_profitable"]:>5.0%}')

    mean_exp = summary_df['avg_expectancy'].mean()
    mean_wr = summary_df['avg_win_rate'].mean()
    med_pf = summary_df['median_profit_factor'].median()
    mean_sharpe = summary_df['avg_sharpe'].mean()
    mean_prof = summary_df['pct_profitable'].mean()
    print('\nPortfolio averages:')
    print(f'  Avg expectancy:          {mean_exp:.6f}')
    print(f'  Avg win rate:            {mean_wr:.4f}')
    print(f'  Median profit factor:    {med_pf:.2f}')
    print(f'  Avg sharpe:              {mean_sharpe:.3f}')
    print(f'  Avg profitable windows:  {mean_prof:.2%}')

    n_pass = (summary_df['avg_expectancy'] > 0).sum()
    n_pf = (summary_df['median_profit_factor'] > 1.0).sum()
    print(f'\n  Assets with positive avg expectancy: {n_pass}/{len(summary_df)}')
    print(f'  Assets with median PF > 1.0:         {n_pf}/{len(summary_df)}')

    os.makedirs(os.path.join(BASE, 'data', 'processed'), exist_ok=True)
    summary_df.to_csv(os.path.join(BASE, 'data', 'processed', 'walkforward_summary.csv'), index=False)
    windows_df.to_csv(os.path.join(BASE, 'data', 'processed', 'walkforward_windows.csv'), index=False)
    logger.info('Results saved to data/processed/walkforward_summary.csv')


if __name__ == '__main__':
    main()
