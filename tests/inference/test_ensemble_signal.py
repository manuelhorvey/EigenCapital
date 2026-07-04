import numpy as np
import pandas as pd

from paper_trading.inference.ensemble import EnsembleSignal
from shared.signal import FixedThresholdStrategy


def test_combine_and_expand_extreme_short_has_valid_short_confidence():
    ensemble = EnsembleSignal(base_weight=0.6, ensemble_threshold=0.15)

    proba, signals = ensemble.combine_and_expand(np.array([0.0102]))

    assert signals.tolist() == [-1]
    assert proba.shape == (1, 3)
    assert proba[0].tolist() == [0.9898, 0.0, 0.0102]
    assert np.all(proba >= 0.0)
    assert np.all(proba <= 1.0)
    assert np.allclose(proba.sum(axis=1), 1.0)

    result = FixedThresholdStrategy().compute(
        proba,
        pd.Index([pd.Timestamp("2026-06-19")]),
        threshold=0.45,
        close=pd.Series([4158.731], index=[pd.Timestamp("2026-06-19")]),
        position_size=1.0,
    )

    assert result.signal_type == "SELL"
    assert result.confidence_pct == 98.98
    latest = result.signal_data.iloc[-1]
    assert latest["prob_short"] == 0.9898
    assert latest["prob_long"] == 0.0102


def test_combine_and_expand_neutral_band_stays_flat_downstream():
    ensemble = EnsembleSignal(base_weight=0.6, ensemble_threshold=0.15)

    proba, signals = ensemble.combine_and_expand(np.array([0.5]))

    assert signals.tolist() == [0]
    assert proba[0].tolist() == [0.0, 1.0, 0.0]

    result = FixedThresholdStrategy().compute(
        proba,
        pd.Index([pd.Timestamp("2026-06-19")]),
        threshold=0.45,
        close=pd.Series([1.0], index=[pd.Timestamp("2026-06-19")]),
        position_size=1.0,
    )

    assert result.signal_type == "FLAT"
    assert result.confidence_pct == 0.0
