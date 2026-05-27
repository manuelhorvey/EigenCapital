import numpy as np
import pandas as pd

from shared.volatility import (
    VOLATILITY_PRIMITIVE_VERSION,
    VolatilityPrimitive,
    compute_atr_pct,
)


def apply_triple_barrier(
    df: pd.DataFrame,
    pt_sl: list = [1, 1],
    target: pd.Series = None,
    vertical_barrier: int = 5,
    vol_primitive: VolatilityPrimitive | None = None,
) -> pd.DataFrame:
    """Triple-barrier labeling with a frozen volatility primitive.

    When *vol_primitive* is ``None``, falls back to the legacy EWM vol
    (span=100) for backward compatibility.  When provided, barrier widths
    are computed using the same volatility primitive consumed by the
    live execution engine (``shared.volatility``).

    The volatility method and version are persisted in ``df.attrs``
    for label-metadata traceability.
    """
    if vol_primitive is not None:
        target = compute_atr_pct(df, period=vol_primitive.period)
        vol_method = f"atr_{vol_primitive.mode}"
    elif target is None:
        target = _ewm_vol(df["close"])
        vol_method = "ewm_100"
    else:
        vol_method = "explicit"

    df = df.loc[target.index].copy()
    labels = pd.Series(index=df.index, data=0, dtype=int)

    for i in range(len(df) - vertical_barrier):
        current_price = float(df["close"].iloc[i])
        vol = float(target.iloc[i])

        upper_barrier = current_price * (1.0 + vol * pt_sl[0])
        lower_barrier = current_price * (1.0 - vol * pt_sl[1])

        future_prices = df["close"].iloc[i + 1 : i + vertical_barrier + 1]

        hits_upper = future_prices[future_prices >= upper_barrier]
        hits_lower = future_prices[future_prices <= lower_barrier]

        if not hits_upper.empty and (hits_lower.empty or hits_upper.index[0] < hits_lower.index[0]):
            labels.iloc[i] = 1
        elif not hits_lower.empty and (hits_upper.empty or hits_lower.index[0] < hits_upper.index[0]):
            labels.iloc[i] = -1
        else:
            labels.iloc[i] = 0

    df["label"] = labels
    df.attrs["vol_method"] = vol_method
    df.attrs["vol_primitive_version"] = VOLATILITY_PRIMITIVE_VERSION
    return df


def _ewm_vol(close: pd.Series, span: int = 100) -> pd.Series:
    """Legacy EWM volatility estimate (span=100)."""
    returns = np.log(close.astype(float) / close.astype(float).shift(1))
    return returns.ewm(span=span).std().dropna()


if __name__ == "__main__":
    # Test with dummy data or load the downloaded EURUSD data
    try:
        data = pd.read_parquet("data/raw/EURUSD_1d.parquet")
        print(f"Loaded {len(data)} rows for labeling.")

        # Apply labels
        labeled_data = apply_triple_barrier(data, pt_sl=[2, 2], vertical_barrier=10)

        print("\nLabel Distribution:")
        print(labeled_data["label"].value_counts(normalize=True))

        # Save labeled data
        labeled_data.to_parquet("data/processed/EURUSD_labeled.parquet")
        print("\nSaved labeled data to data/processed/EURUSD_labeled.parquet")
    except Exception as e:
        import traceback

        traceback.print_exc()
        print(f"Test failed: {e}")
