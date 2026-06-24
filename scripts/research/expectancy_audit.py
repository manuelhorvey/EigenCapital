import pandas as pd
import numpy as np

def calculate_expectancy(trades: pd.DataFrame) -> dict:
    """
    Calculates detailed expectancy and tail risk metrics.
    """
    if len(trades) == 0:
        return {'n_trades': 0, 'expectancy': 0}
        
    wins = trades[trades['pnl'] > 0]['pnl']
    losses = trades[trades['pnl'] < 0]['pnl']
    
    if len(trades) == 0: return {'n_trades': 0}
    
    win_rate = len(wins) / len(trades)
    avg_win = wins.mean() if not wins.empty else 0
    avg_loss = losses.abs().mean() if not losses.empty else 0
    
    # Expectancy = (P(W) * E[W]) - (P(L) * E[L])
    expectancy = (win_rate * avg_win) - ((1 - win_rate) * avg_loss)
    rrr = avg_win / (avg_loss + 1e-9)
    
    # Recovery and Skew
    total_profit = wins.sum()
    max_dd = trades['pnl'].cumsum().expanding().max() - trades['pnl'].cumsum()
    max_drawdown = max_dd.max()
    recovery_factor = total_profit / (max_drawdown + 1e-9)
    
    return {
        'expectancy': round(expectancy, 6),
        'win_rate': round(win_rate, 4),
        'avg_win': round(avg_win, 6),
        'avg_loss': round(avg_loss, 6),
        'rrr': round(rrr, 2),
        'n_trades': len(trades),
        'max_loss': round(losses.min(), 6) if not losses.empty else 0,
        'recovery_factor': round(recovery_factor, 2),
        'profit_factor': round(total_profit / (losses.abs().sum() + 1e-9), 2)
    }

def run_expectancy_audit(signals: pd.DataFrame, returns: pd.Series):
    """
    Audits expectancy across regimes and confidence thresholds.
    """
    df = signals.copy()
    df['forward_returns'] = returns.shift(-1)
    
    # PnL = signal * multiplier * return
    df['pnl'] = df['signal'] * df['risk_multiplier'] * df['forward_returns']
    
    regimes = df['regime'].unique()
    results = {}
    
    print(f"\n{'='*20} EXPECTANCY AUDIT {'='*20}")
    
    for r in regimes:
        regime_df = df[df['regime'] == r]
        # Only count rows where a signal was generated
        trades = regime_df[regime_df['signal'] != 0]
        
        metrics = calculate_expectancy(trades)
        results[r] = metrics
        
        print(f"\nRegime: {r.upper()}")
        if metrics['n_trades'] > 0:
            print(f"  Expectancy:    {metrics['expectancy']}")
            print(f"  Win Rate:      {metrics['win_rate']:.2%}")
            print(f"  Profit Factor: {metrics.get('profit_factor', 0)}")
            print(f"  Recovery:      {metrics['recovery_factor']}")
            print(f"  RRR:           {metrics['rrr']}")
            print(f"  Trades:        {metrics['n_trades']}")
        else:
            print("  No trades generated.")
        
    return results

if __name__ == "__main__":
    try:
        # 1. Load Data
        signals = pd.read_parquet("data/processed/EURUSD_signals.parquet")
        data = pd.read_parquet("data/raw/EURUSD_1d.parquet")
        returns = data['close'].pct_change().loc[signals.index]
        
        run_expectancy_audit(signals, returns)
        
    except Exception as e:
        import traceback
        traceback.print_exc()
