import pandas as pd
import numpy as np
from models.hybrid_ensemble import HybridRegimeEnsemble
from signals.signal_generator import RegimeAwareSignalGenerator
from backtests.expectancy_audit import calculate_expectancy

class WalkForwardValidator:
    """
    Rolling Walk-Forward Validation for Alpha Stability.
    """
    def __init__(self, ensemble: HybridRegimeEnsemble, window_years: int = 3, step_years: int = 1):
        self.ensemble = ensemble
        self.window_years = window_years
        self.step_years = step_years

    def run_validation(self, X, y, regimes, returns, regime_features):
        """
        Runs rolling OOS validation windows.
        """
        years = X.index.year.unique()
        start_year = years[0]
        end_year = years[-1]
        
        results = []
        
        # Start after the first 'window_years'
        for current_year in range(start_year + self.window_years, end_year + 1, self.step_years):
            train_end = current_year - 1
            oos_year = current_year
            
            print(f"\n--- Walk-Forward Window: Train up to {train_end}, OOS {oos_year} ---")
            
            # Split
            train_mask = (X.index.year <= train_end)
            oos_mask = (X.index.year == oos_year)
            
            X_train, y_train, r_train = X[train_mask], y[train_mask], regimes[train_mask]
            X_oos = X[oos_mask]
            regime_features_oos = regime_features.loc[X_oos.index]
            
            if len(X_oos) == 0: continue
            
            # 1. Re-train Ensemble on growing window
            self.ensemble.train(X_train, y_train, r_train)
            
            # 2. Generate Signals OOS
            generator = RegimeAwareSignalGenerator(self.ensemble)
            # We relax thresholds for OOS to ensure we get some trades even in quiet years
            signals_oos = generator.generate_signals(X_oos, regime_features_oos)
            
            # 3. Calculate Performance
            df_oos = signals_oos.copy()
            df_oos['returns'] = returns.shift(-1).loc[X_oos.index]
            df_oos['pnl'] = df_oos['signal'] * df_oos['risk_multiplier'] * df_oos['returns']
            
            trades = df_oos[df_oos['signal'] != 0]
            metrics = calculate_expectancy(trades)
            
            metrics['window'] = oos_year
            results.append(metrics)
            
            print(f"  Window {oos_year} Expectancy: {metrics['expectancy']} | Trades: {metrics['n_trades']}")
            
        return pd.DataFrame(results)

if __name__ == "__main__":
    try:
        # Assemble Manifold
        base = pd.read_parquet("data/processed/EURUSD_features.parquet")
        regime_meta = pd.read_parquet("data/processed/EURUSD_regime_labels.parquet")
        struct = pd.read_parquet("data/processed/EURUSD_structural_features.parquet")
        interact = pd.read_parquet("data/processed/EURUSD_interaction_features.parquet")
        labeled = pd.read_parquet("data/processed/EURUSD_labeled.parquet")
        data = pd.read_parquet("data/raw/EURUSD_1d.parquet")
        returns = data['close'].pct_change()
        
        common_idx = base.index.intersection(regime_meta.index).intersection(struct.index).intersection(interact.index).intersection(labeled.index)
        
        X = pd.concat([
            base.loc[common_idx].drop('label', axis=1),
            regime_meta.loc[common_idx][['P_trend', 'P_range', 'P_volatile', 'regime_confidence']],
            struct.loc[common_idx],
            interact.loc[common_idx]
        ], axis=1)
        
        y = labeled.loc[common_idx, 'label'] + 1
        regimes = regime_meta.loc[common_idx, 'regime']
        regime_features = regime_meta.loc[common_idx]
        
        # Run Validator
        ensemble = HybridRegimeEnsemble()
        validator = WalkForwardValidator(ensemble)
        wf_results = validator.run_validation(X, y, regimes, returns, regime_features)
        
        print("\n" + "="*30)
        print("WALK-FORWARD SUMMARY")
        print("="*30)
        print(wf_results[['window', 'expectancy', 'win_rate', 'n_trades', 'profit_factor']])
        
        avg_exp = wf_results['expectancy'].mean()
        std_exp = wf_results['expectancy'].std()
        
        print(f"\nAverage Expectancy: {avg_exp:.6f}")
        print(f"Expectancy Std Dev: {std_exp:.6f}")
        
        if avg_exp > 0:
            print("\nSUCCESS: System maintained positive average expectancy across walk-forward windows.")
        else:
            print("\nWARNING: Negative average expectancy in walk-forward. Re-tuning needed.")
            
    except Exception as e:
        import traceback
        traceback.print_exc()
