import numpy as np
import pandas as pd
import pytest

from shared.signal import FixedThresholdStrategy, SignalResult

# ── FixedThresholdStrategy ───────────────────────────────────────────────────


@pytest.fixture
def strategy():
    return FixedThresholdStrategy()


def test_compute_buy_signal(strategy):
    proba = np.array([[0.1, 0.2, 0.7]])
    index = pd.RangeIndex(1)
    close = pd.Series([100.0], index=index)
    result = strategy.compute(proba, index, 0.5, close, 0.5)
    assert isinstance(result, SignalResult)
    assert result.signal_type == "BUY"
    assert result.label == 2


def test_compute_sell_signal(strategy):
    proba = np.array([[0.7, 0.2, 0.1]])
    index = pd.RangeIndex(1)
    close = pd.Series([100.0], index=index)
    result = strategy.compute(proba, index, 0.5, close, 0.5)
    assert result.signal_type == "SELL"
    assert result.label == 0


def test_compute_below_threshold_is_flat(strategy):
    """When neither long nor short exceeds threshold, signal stays 1 (FLAT)."""
    proba = np.array([[0.4, 0.2, 0.4]])
    index = pd.RangeIndex(1)
    close = pd.Series([100.0], index=index)
    result = strategy.compute(proba, index, 0.5, close, 0.5)
    assert result.signal_type == "FLAT"
    assert result.label == 1


def test_compute_threshold_filtering_severe(strategy):
    """Very strict threshold causes no signal to exceed it, resulting in FLAT."""
    proba = np.array([[0.1, 0.8, 0.1]])
    index = pd.RangeIndex(1)
    close = pd.Series([100.0], index=index)
    result = strategy.compute(proba, index, 0.9, close, 0.5)
    assert result.signal_type == "FLAT"
    assert result.label == 1


def test_compute_confidence_pct(strategy):
    proba = np.array([[0.2, 0.1, 0.7]])
    index = pd.RangeIndex(1)
    close = pd.Series([100.0], index=index)
    result = strategy.compute(proba, index, 0.5, close, 0.5)
    assert result.confidence_pct == 70.0


def test_compute_dataframe_shape(strategy):
    proba = np.array([[0.1, 0.2, 0.7], [0.6, 0.2, 0.2], [0.3, 0.4, 0.3]])
    index = pd.RangeIndex(3)
    close = pd.Series([100.0, 101.0, 102.0], index=index)
    result = strategy.compute(proba, index, 0.5, close, 0.5)
    assert len(result.signal_data) == 3
    assert list(result.signal_data.columns) == [
        "close",
        "signal",
        "prob_long",
        "prob_short",
        "prob_neutral",
        "position_size",
    ]


def test_compute_threshold_filtering(strategy):
    """Signal defaults to 1 (FLAT) when neither long nor short exceeds threshold."""
    proba = np.array([[0.1, 0.8, 0.1]])
    index = pd.RangeIndex(1)
    close = pd.Series([100.0], index=index)
    result = strategy.compute(proba, index, 0.9, close, 0.5)
    assert result.signal_type == "FLAT"
    assert result.label == 1


def test_compute_position_size_in_dataframe(strategy):
    proba = np.array([[0.1, 0.1, 0.8]])
    index = pd.RangeIndex(1)
    close = pd.Series([100.0], index=index)
    result = strategy.compute(proba, index, 0.5, close, 0.75)
    assert result.signal_data["position_size"].iloc[0] == 0.75
