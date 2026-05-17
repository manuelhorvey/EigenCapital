import pandas as pd
import numpy as np
from models.hybrid_ensemble import HybridRegimeEnsemble
from signals.signal_generator import RegimeAwareSignalGenerator
from backtests.expectancy_audit import calculate_expectancy

ROLLING_CONFIG = {
    'train_months': 18,
    'val_months':   3,
    'test_months':  6,
    'step_months':  6,
}

class RollingRetrainValidator:
    def __init__(self, ensemble: HybridRegimeEnsemble, config: dict = None):
        self.ensemble = ensemble
        self.config = config or ROLLING_CONFIG

    def run_validation(self, X, y, regimes, returns, regime_features):
        dates = X.index.sort_values()
        start_date = dates[0]
        end_date = dates[-1]

        train_delta = pd.DateOffset(months=self.config['train_months'])
        val_delta = pd.DateOffset(months=self.config['val_months'])
        test_delta = pd.DateOffset(months=self.config['test_months'])
        step_delta = pd.DateOffset(months=self.config['step_months'])

        window_start = start_date + train_delta + val_delta

        all_results = []
        all_signals = []

        while window_start + test_delta <= end_date:
            test_end = window_start + test_delta
            train_start = window_start - train_delta - val_delta
            train_end = train_start + train_delta

            oos_mask = (X.index >= window_start) & (X.index < test_end)
            train_mask = (X.index >= train_start) & (X.index < train_end)

            X_train, y_train, r_train = X[train_mask], y[train_mask], regimes[train_mask]
            X_oos = X[oos_mask]
            regime_features_oos = regime_features.loc[X_oos.index]

            if len(X_train) == 0 or len(X_oos) == 0:
                window_start += step_delta
                continue

            n_training = len(X_train)
            print(f"\n--- Rolling Window: Train {train_start.date()} to {train_end.date()} "
                  f"({n_training} rows) | OOS {window_start.date()} to {test_end.date()} ({len(X_oos)} rows) ---")

            self.ensemble.train(X_train, y_train, r_train)

            generator = RegimeAwareSignalGenerator(self.ensemble)
            signals_oos = generator.generate_signals(X_oos, regime_features_oos)

            df_oos = signals_oos.copy()
            forward_ret = returns.reindex(X_oos.index)
            df_oos['returns'] = forward_ret.values
            df_oos['pnl'] = df_oos['signal'] * df_oos['risk_multiplier'] * df_oos['returns']

            trades = df_oos[df_oos['signal'] != 0]
            metrics = calculate_expectancy(trades)
            metrics['train_start'] = train_start
            metrics['train_end'] = train_end
            metrics['test_start'] = window_start
            metrics['test_end'] = test_end
            all_results.append(metrics)
            all_signals.append(df_oos[['raw_prob_short', 'raw_prob_neutral', 'raw_prob_long', 'signal', 'pnl']].copy())

            exp_str = f"{metrics['expectancy']:.6f}" if metrics.get('expectancy') is not None else "N/A"
            print(f"  Expectancy: {exp_str} | Trades: {metrics.get('n_trades', 0)} | PF: {metrics.get('profit_factor', 'N/A')}")

            window_start += step_delta

        return pd.DataFrame(all_results), pd.concat(all_signals).sort_index()


if __name__ == "__main__":
    try:
        base = pd.read_parquet("data/processed/EURUSD_features.parquet")
        regime_meta = pd.read_parquet("data/processed/EURUSD_regime_labels.parquet")
        struct = pd.read_parquet("data/processed/EURUSD_structural_features.parquet")
        interact = pd.read_parquet("data/processed/EURUSD_interaction_features.parquet")
        labeled = pd.read_parquet("data/processed/EURUSD_labeled.parquet")
        macro = pd.read_parquet("data/processed/macro_features.parquet")
        data = pd.read_parquet("data/raw/EURUSD_1d.parquet")
        returns = data['close'].pct_change()

        common_idx = base.index.intersection(regime_meta.index).intersection(
            struct.index).intersection(interact.index).intersection(labeled.index)

        macro_daily = macro.reindex(common_idx, method='ffill')
        macro_daily.index = macro_daily.index.normalize()

        X = pd.concat([
            base.loc[common_idx].drop('label', axis=1),
            regime_meta.loc[common_idx][['P_trend', 'P_range', 'P_volatile', 'regime_confidence']],
            struct.loc[common_idx],
            interact.loc[common_idx],
            macro_daily[['rate_diff', 'rate_diff_delta_3m', 'real_yield_10y',
                         'yield_slope', 'dxy_mom_21', 'dxy_mom_63', 'fed_funds_delta_3m']]
        ], axis=1)

        y = labeled.loc[common_idx, 'label'] + 1
        regimes = regime_meta.loc[common_idx, 'regime']
        regime_features = regime_meta.loc[common_idx]

        ensemble = HybridRegimeEnsemble()
        validator = RollingRetrainValidator(ensemble)
        results, all_signals = validator.run_validation(X, y, regimes, returns, regime_features)

        print("\n" + "="*30)
        print("ROLLING RETRAIN RESULTS")
        print("="*30)

        for _, row in results.iterrows():
            yr_range = f"{row['test_start'].year}-{row['test_end'].year}"
            print(f"  {yr_range:12s}  expect={row['expectancy']:.6f}  "
                  f"trades={row['n_trades']:3d}  PF={row.get('profit_factor', 0):.2f}")

        print("\n--- Aggregate by Calendar Year ---")
        results_list = []
        for _, row in results.iterrows():
            results_list.append({
                'expectancy': row['expectancy'],
                'n_trades': row['n_trades'],
                'profit_factor': row.get('profit_factor', 0),
            })
        agg = pd.DataFrame(results_list)
        avg_exp = agg['expectancy'].mean()
        total_trades = agg['n_trades'].sum()
        avg_pf = agg['profit_factor'].mean()
        print(f"Average Expectancy: {avg_exp:.6f}")
        print(f"Total Trades:       {total_trades}")
        print(f"Avg Profit Factor:  {avg_pf:.2f}")

        if avg_exp > 0:
            print("\nVERDICT: Positive expectancy across rolling windows.")
            print("Training window fix is viable. Model can generalize when kept current.")
        else:
            print("\nVERDICT: Negative expectancy even with rolling retrain.")
            print("Feature problem. Need macro/rate-environment features.")

        # Probability distribution diagnostics
        print("\n" + "="*30)
        print("PROBABILITY DISTRIBUTION DIAGNOSTICS")
        print("="*30)

        subset = all_signals['2022':'2024']
        print(f"\n2022-2024 subset: {len(subset)} observations")

        for label, probs in [('All windows', all_signals), ('2022-2024', subset)]:
            print(f"\n{label}:")
            print(f"  P(long)  mean={probs['raw_prob_long'].mean():.4f}  "
                  f"std={probs['raw_prob_long'].std():.4f}")
            print(f"  P(short) mean={probs['raw_prob_short'].mean():.4f}  "
                  f"std={probs['raw_prob_short'].std():.4f}")
            print(f"  P(flat)  mean={probs['raw_prob_neutral'].mean():.4f}  "
                  f"std={probs['raw_prob_neutral'].std():.4f}")

            max_conf = pd.concat([probs['raw_prob_long'], probs['raw_prob_short']], axis=1).max(axis=1)
            print(f"  Max directional confidence — mean={max_conf.mean():.4f}  "
                  f"median={max_conf.median():.4f}  max={max_conf.max():.4f}")
            print(f"  Bars above 0.65 threshold: {(max_conf > 0.65).sum()} / {len(probs)} "
                  f"({(max_conf > 0.65).mean():.1%})")
            print(f"  Bars above 0.55 threshold: {(max_conf > 0.55).sum()} / {len(probs)} "
                  f"({(max_conf > 0.55).mean():.1%})")
            print(f"  Bars with signal != 0:    {(probs['signal'] != 0).sum()} / {len(probs)} "
                  f"({(probs['signal'] != 0).mean():.1%})")

    except Exception as e:
        import traceback
        traceback.print_exc()
