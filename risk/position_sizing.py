import pandas as pd


def calculate_position_size(
    signal_df: pd.DataFrame, base_risk: float = 0.01, account_value: float = 100000
) -> pd.Series:
    """
    Calculates position sizes based on signals and regime multipliers.

    Args:
        signal_df: DataFrame with 'signal' and 'risk_multiplier'.
        base_risk: Percentage of account to risk per trade (e.g., 0.01 for 1%).
        account_value: Total account equity.

    Returns:
        pd.Series: Position size in units/lots.
    """
    # For simulation, we return the relative size (multiplier)
    # as we don't have asset price/volatility here yet.
    # A value of 1.0 means full base risk.
    return signal_df["signal"] * signal_df["risk_multiplier"]


if __name__ == "__main__":
    try:
        signals = pd.read_parquet("data/processed/EURUSD_signals.parquet")
        sizes = calculate_position_size(signals)
        print("\nPosition Sizes (Sample):")
        print(sizes.tail())
    except (FileNotFoundError, pd.errors.EmptyDataError, ValueError) as e:
        print(f"Position sizing test failed: {e}")
