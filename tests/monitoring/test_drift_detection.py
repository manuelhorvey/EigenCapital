import numpy as np
import pandas as pd
import pytest

from monitoring.drift_detection import (
    calculate_psi,
    column_group_psi,
    grouped_feature_psi,
    signal_distribution_drift,
    confidence_drift,
    ks_drift,
    DriftDetector,
    STRUCTURAL_PSI_COLUMNS,
)


# ── Fixtures ─────────────────────────────────────────────────────────────────


@pytest.fixture
def train():
    np.random.seed(42)
    n = 500
    return pd.DataFrame(
        {
            "ema_spread": np.random.randn(n),
            "adx": np.random.uniform(10, 40, n),
            "rsi": np.random.uniform(30, 70, n),
            "bb_zscore": np.random.randn(n) * 2,
            "slope_20": np.random.randn(n) * 0.01,
            "curvature_10": np.random.randn(n) * 0.001,
            "path_efficiency_63": np.random.uniform(0.2, 0.8, n),
            "skew": np.random.randn(n) * 0.5,
            "kurt": np.random.randn(n) + 3,
            "tail_ratio": np.random.uniform(1, 5, n),
            "P_trend": np.random.uniform(0, 1, n),
            "P_range": np.random.uniform(0, 1, n),
            "P_volatile": np.random.uniform(0, 1, n),
            "regime_confidence": np.random.uniform(0.5, 1, n),
            "regime_contrast": np.random.uniform(-1, 1, n),
            "regime_entropy": np.random.uniform(0, 1, n),
            "transition_risk": np.random.uniform(0, 0.5, n),
            "ema_contrast": np.random.randn(n),
            "slope_contrast": np.random.randn(n),
            "path_contrast": np.random.randn(n),
        }
    )


@pytest.fixture
def live(train):
    return train.copy()


# ── calculate_psi ────────────────────────────────────────────────────────────


def test_calculate_psi_identical_distributions():
    expected = pd.Series(np.random.normal(0, 1, 1000))
    actual = expected.copy()
    psi = calculate_psi(expected, actual)
    assert psi < 0.05


def test_calculate_psi_shifted():
    expected = pd.Series(np.random.normal(0, 1, 500))
    actual = pd.Series(np.random.normal(3, 1, 200))
    psi = calculate_psi(expected, actual)
    assert psi > 0.1


def test_calculate_psi_insufficient_data():
    assert calculate_psi(pd.Series([1, 2, 3]), pd.Series([1.5])) == 0.0


def test_calculate_psi_empty_actual():
    assert calculate_psi(pd.Series([1, 2, 3] * 100), pd.Series([], dtype=float)) == 0.0


def test_calculate_psi_constant_values():
    assert calculate_psi(pd.Series(np.ones(100)), pd.Series(np.ones(50))) == 0.0


def test_calculate_psi_with_inf():
    expected = pd.Series([1.0, 2.0, np.inf, 4.0, 5.0])
    actual = pd.Series([1.5, 2.5, 3.5, -np.inf, 5.5])
    psi = calculate_psi(expected, actual)
    assert psi >= 0.0


# ── column_group_psi ─────────────────────────────────────────────────────────


def test_column_group_psi_identical(train):
    psi = column_group_psi(train, train, STRUCTURAL_PSI_COLUMNS)
    assert psi < 0.05


def test_column_group_psi_no_common_columns():
    train = pd.DataFrame({"a": [1, 2, 3]})
    live = pd.DataFrame({"b": [4, 5, 6]})
    assert column_group_psi(train, live, ["a"]) == 0.0


# ── grouped_feature_psi ──────────────────────────────────────────────────────


def test_grouped_feature_psi_keys(train):
    result = grouped_feature_psi(train, train)
    assert "feature_psi" in result
    assert "structural_psi" in result
    assert "behavioral_psi" in result
    assert "interaction_psi" in result


def test_grouped_feature_psi_identical(train):
    result = grouped_feature_psi(train, train)
    assert result["feature_psi"] < 0.05


# ── signal_distribution_drift ────────────────────────────────────────────────


def test_signal_distribution_drift_identical():
    bt = {"BUY": 0.5, "SELL": 0.3, "FLAT": 0.2}
    live = {"BUY": 50, "SELL": 30, "FLAT": 20}
    assert signal_distribution_drift(live, bt) < 0.01


def test_signal_distribution_drift_empty():
    assert signal_distribution_drift({}, {"BUY": 1.0}) == 0.0


def test_signal_distribution_drift_different():
    bt = {"BUY": 0.9, "SELL": 0.1}
    live = {"BUY": 10, "SELL": 90}
    assert signal_distribution_drift(live, bt) > 0.3


# ── confidence_drift ─────────────────────────────────────────────────────────


def test_confidence_drift_identical():
    assert confidence_drift(0.75, 0.75) == 0.0


def test_confidence_drift_different():
    assert confidence_drift(0.5, 0.8) == pytest.approx(0.3)


# ── ks_drift ─────────────────────────────────────────────────────────────────


def test_ks_drift_identical(train):
    d = ks_drift(train, train, "ema_spread")
    assert d < 0.05


def test_ks_drift_missing_feature():
    train = pd.DataFrame({"a": [1, 2, 3]})
    live = pd.DataFrame({"b": [4, 5, 6]})
    assert ks_drift(train, live, "a") == 0.0


# ── DriftDetector ────────────────────────────────────────────────────────────


def test_detector_check_feature_psi_passes(train):
    detector = DriftDetector()
    result = detector.check_feature_psi(train, train)
    assert result["passed"] is True


def test_detector_check_signal_drift():
    detector = DriftDetector()
    result = detector.check_signal_drift({"BUY": 50, "SELL": 50}, {"BUY": 0.5, "SELL": 0.5})
    assert result["passed"] is True


def test_detector_check_confidence_drift():
    detector = DriftDetector()
    result = detector.check_confidence_drift(0.75, 0.75)
    assert result["passed"] is True


def test_detector_check_ks_drift(train):
    detector = DriftDetector()
    result = detector.check_ks_drift(train, train, ["ema_spread", "rsi"])
    assert result["ema_spread"]["passed"] is True
    assert result["rsi"]["passed"] is True


def test_detector_full_check(train):
    detector = DriftDetector()
    result = detector.full_check(
        train,
        train,
        {"BUY": 50, "SELL": 30, "FLAT": 20},
        {"BUY": 0.5, "SELL": 0.3, "FLAT": 0.2},
        0.75,
        0.75,
        ks_features=["ema_spread"],
    )
    assert "feature_psi" in result
    assert "signal_distribution" in result
    assert "confidence" in result
    assert "ks_drift" in result
    assert result["feature_psi"]["passed"] is True


def test_detector_custom_thresholds():
    detector = DriftDetector(psi_threshold=0.1, signal_drift_threshold=0.05)
    assert detector.psi_threshold == 0.1
    assert detector.signal_drift_threshold == 0.05


def test_detector_full_check_with_none_ks_features(train):
    detector = DriftDetector()
    result = detector.full_check(
        train,
        train,
        {"BUY": 100},
        {"BUY": 1.0},
        0.8,
        0.8,
        ks_features=None,
    )
    assert "ks_drift" in result
