import logging

import numpy as np
import pandas as pd

from shared.volatility import (
    VOLATILITY_PRIMITIVE_VERSION,
    VolatilityPrimitive,
    compute_atr_pct,
)


def apply_triple_barrier(
    df: pd.DataFrame,
    pt_sl: list | None = None,
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

    Vectorized implementation uses ``sliding_window_view`` to eliminate
    the O(N×V) Python loop, replacing it with O(N) numpy operations.
    """
    if pt_sl is None:
        pt_sl = [1, 1]

    if vol_primitive is not None:
        target = compute_atr_pct(df, period=vol_primitive.period)
        vol_method = f"atr_{vol_primitive.mode}"
    elif target is None:
        target = _ewm_vol(df["close"])
        vol_method = "ewm_100"
    else:
        vol_method = "explicit"

    df = df.loc[target.index].copy()
    close = df["close"].values
    vol = target.values
    n = len(close)
    vb = vertical_barrier

    # Initialize labels to 0 (no touch / outside lookahead window)
    labels = np.zeros(n, dtype=int)

    if n <= vb:
        df["label"] = pd.Series(labels, index=df.index)
        df.attrs["vol_method"] = vol_method
        df.attrs["vol_primitive_version"] = VOLATILITY_PRIMITIVE_VERSION
        return df

    # Rolling window view: shape (n - vb, vb + 1)
    windows = np.lib.stride_tricks.sliding_window_view(close, vb + 1)

    # Current price and vol for each window start
    curr = windows[:, 0]  # shape (n - vb,)
    vol_slice = vol[: n - vb]

    # Barrier prices
    upper = curr * (1.0 + vol_slice * pt_sl[0])
    lower = curr * (1.0 - vol_slice * pt_sl[1])

    # Future prices (exclude current bar)
    future = windows[:, 1:]  # shape (n - vb, vb)

    # Find first hit for each barrier
    # np.argmax returns first True, or 0 if none are True
    hit_upper = np.argmax(future >= upper[:, None], axis=1)
    hit_lower = np.argmax(future <= lower[:, None], axis=1)

    # Detect no-hit cases: argmax returns 0 but the first future price
    # may not actually hit the barrier
    no_upper_hit = ~np.any(future >= upper[:, None], axis=1)
    no_lower_hit = ~np.any(future <= lower[:, None], axis=1)
    hit_upper[no_upper_hit] = vb  # sentinel past lookahead
    hit_lower[no_lower_hit] = vb

    # Label: +1 if upper hit first, -1 if lower hit first, 0 otherwise
    labeled = np.full(n - vb, 0, dtype=int)
    upper_first = hit_upper < hit_lower
    lower_first = hit_lower < hit_upper
    labeled[upper_first] = 1
    labeled[lower_first] = -1

    labels[: n - vb] = labeled
    # Last vb rows remain 0 (no complete lookahead window)

    df["label"] = pd.Series(labels, index=df.index)
    df.attrs["vol_method"] = vol_method
    df.attrs["vol_primitive_version"] = VOLATILITY_PRIMITIVE_VERSION
    return df


def _ewm_vol(close: pd.Series, span: int = 100) -> pd.Series:
    """Legacy EWM volatility estimate (span=100)."""
    returns = np.log(close.astype(float) / close.astype(float).shift(1))
    return returns.ewm(span=span).std().dropna()


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    logger = logging.getLogger(__name__)
    # Test with dummy data or load the downloaded EURUSD data
    try:
        data = pd.read_parquet("data/raw/EURUSD_1d.parquet")
        logger.info("Loaded %d rows for labeling.", len(data))

        # Apply labels
        labeled_data = apply_triple_barrier(data, pt_sl=[2, 2], vertical_barrier=10)

        logger.info("\nLabel Distribution:")
        logger.info("\n%s", labeled_data["label"].value_counts(normalize=True))

        # Save labeled data
        labeled_data.to_parquet("data/processed/EURUSD_labeled.parquet")
        logger.info("\nSaved labeled data to data/processed/EURUSD_labeled.parquet")
    except (OSError, ValueError, TypeError, KeyError, FileNotFoundError) as e:
        import traceback

        traceback.print_exc()
        logger.error("Test failed: %s", e)
