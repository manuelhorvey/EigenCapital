import numpy as np
import pandas as pd


def calculate_regime_performance(signals: pd.DataFrame, returns: pd.Series) -> dict:
    """
    Calculates PnL and metrics decomposed by market regime.

    Args:
        signals: DataFrame with 'regime' and 'signal' (or position size).
        returns: Series of asset returns aligned with signals.

    Returns:
        dict: Performance metrics per regime.
    """
    df = signals.copy()

    # IMPORTANT: Signals are generated at the end of bar t.
    # The trade occurs at the open of bar t+1.
    # Therefore, we must align signal[t] with return[t+1].
    df["returns"] = returns.shift(-1)

    # Strategy return = position size * next bar return
    df["strategy_returns"] = df["signal"] * df["risk_multiplier"] * df["returns"]

    regimes = df["regime"].unique()
    metrics = {}

    for regime in regimes:
        regime_df = df[df["regime"] == regime]

        if len(regime_df) == 0:
            continue

        r_sum = regime_df["strategy_returns"].sum()
        r_mean = regime_df["strategy_returns"].mean()
        r_std = regime_df["strategy_returns"].std()

        sharpe = np.sqrt(252) * r_mean / r_std if r_std > 0 else 0

        metrics[regime] = {
            "total_return": r_sum,
            "sharpe": sharpe,
            "count": len(regime_df),
            "win_rate": (regime_df["strategy_returns"] > 0).mean(),
        }

    return metrics


if __name__ == "__main__":
    try:
        signals = pd.read_parquet("data/processed/EURUSD_signals.parquet")
        data = pd.read_parquet("data/raw/EURUSD_1d.parquet")
        returns = data["close"].pct_change().loc[signals.index]

        perf = calculate_regime_performance(signals, returns)

        print("\nRegime Performance Decomposition:")
        for regime, m in perf.items():
            print(f"\nRegime: {regime.upper()}")
            print(f"  Total Return: {m['total_return']:.4f}")
            print(f"  Sharpe Ratio: {m['sharpe']:.2f}")
            print(f"  Win Rate:     {m['win_rate']:.2%}")
            print(f"  Sample Count: {m['count']}")

    except Exception as e:  # noqa: BLE001
        import traceback

        traceback.print_exc()
        print(f"Performance metrics test failed: {e}")
