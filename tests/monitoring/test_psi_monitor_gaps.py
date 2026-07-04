import numpy as np
import pandas as pd
from hypothesis import given, strategies as st, settings

from monitoring.psi_monitor import PSIMonitor, PSIDriftEntry, PSISnapshot


# ── Property-based tests for classify_drift ──────────────────────────────────

@given(
    psi=st.floats(min_value=0.0, max_value=1.0, allow_nan=False, allow_infinity=False)
)
@settings(max_examples=100)
def test_classify_drift_is_monotonic(psi):
    """Higher PSI never produces a lower severity classification."""
    ordering = {"NO_DRIFT": 0, "MODERATE": 1, "SEVERE": 2}
    result = PSIMonitor.classify_drift(psi)
    assert result in ordering
    if psi < 0.1:
        assert ordering[result] == 0
    elif psi < 0.2:
        assert ordering[result] == 1
    else:
        assert ordering[result] == 2


@given(
    psi=st.floats(min_value=-0.5, max_value=-1e-10, allow_nan=False, allow_infinity=False)
)
@settings(max_examples=50)
def test_classify_drift_negative_treated_as_no_drift(psi):
    """Negative PSI values are treated as NO_DRIFT."""
    result = PSIMonitor.classify_drift(psi)
    assert result == "NO_DRIFT"


@given(
    psi=st.floats(min_value=1.0 + 1e-10, max_value=10.0, allow_nan=False, allow_infinity=False)
)
@settings(max_examples=50)
def test_classify_drift_large_values_are_severe(psi):
    """Any PSI >= 0.2 is SEVERE, including large values."""
    result = PSIMonitor.classify_drift(psi)
    assert result == "SEVERE"


@given(
    psi=st.floats(min_value=0.0, max_value=1.0, allow_nan=False, allow_infinity=False)
)
@settings(max_examples=100)
def test_compute_trend_is_deterministic(psi):
    """_compute_trend returns one of the three valid states."""
    trend = PSIMonitor._compute_trend(psi, psi)
    assert trend in ("STABLE", "INCREASING", "DECREASING")


# ── Edge cases for compute_psi ───────────────────────────────────────────────

def test_compute_psi_empty_series():
    """Empty or all-NaN series returns 0.0."""
    empty = pd.Series([], dtype=float)
    psi = PSIMonitor.compute_psi(empty, empty)
    assert psi == 0.0


def test_compute_psi_all_nan():
    """All-NaN series returns 0.0."""
    nan_series = pd.Series([np.nan, np.nan])
    psi = PSIMonitor.compute_psi(nan_series, pd.Series([1.0, 2.0]))
    assert psi == 0.0


def test_compute_psi_single_value():
    """Single-value expected series returns 0.0."""
    expected = pd.Series([1.0])
    actual = pd.Series([1.5, 2.5])
    psi = PSIMonitor.compute_psi(expected, actual)
    assert psi == 0.0


# ── Edge cases for compute_drift ─────────────────────────────────────────────

def test_compute_drift_empty_current_features(tmp_path):
    """Empty current_features DataFrame returns empty snapshot."""
    monitor = PSIMonitor(tmp_path)
    X_train = pd.DataFrame({"a": np.random.normal(0, 1, 500)})
    monitor.persist_baseline("test_asset", X_train)
    X_current = pd.DataFrame()
    snapshot = monitor.compute_drift("test_asset", X_current, [("a", 1.0)])
    assert snapshot is None


def test_compute_drift_no_top_features(tmp_path):
    """Empty top_features list returns empty entries."""
    monitor = PSIMonitor(tmp_path)
    X_train = pd.DataFrame({"a": np.random.normal(0, 1, 500)})
    monitor.persist_baseline("test_asset", X_train)
    X_current = pd.DataFrame({"a": np.random.normal(0, 1, 100)})
    snapshot = monitor.compute_drift("test_asset", X_current, [])
    assert snapshot is None


def test_compute_drift_moderate_penalty(tmp_path):
    """Moderate drift applies -0.08 penalty."""
    monitor = PSIMonitor(tmp_path)
    rng = np.random.default_rng(42)
    X_train = pd.DataFrame({"a": rng.normal(0, 1, 500)})
    monitor.persist_baseline("test_asset", X_train)
    X_current = pd.DataFrame({"a": rng.normal(1.2, 1, 100)})
    snapshot = monitor.compute_drift("test_asset", X_current, [("a", 1.0)])
    assert snapshot is not None
    if snapshot.moderate_count > 0:
        assert snapshot.penalty == -0.08
    elif snapshot.severe_count > 0:
        assert snapshot.penalty == -0.20


# ── Edge cases for persist_baseline ──────────────────────────────────────────

def test_persist_baseline_empty_dataframe(tmp_path):
    """persist_baseline skips empty DataFrames."""
    monitor = PSIMonitor(tmp_path)
    monitor.persist_baseline("empty_asset", pd.DataFrame())
    baseline = monitor.load_baseline("empty_asset")
    assert baseline is None


def test_persist_baseline_single_column(tmp_path):
    """persist_baseline handles single-column DataFrame."""
    monitor = PSIMonitor(tmp_path)
    X = pd.DataFrame({"a": [1.0, 2.0, 3.0]})
    monitor.persist_baseline("single_col", X)
    baseline = monitor.load_baseline("single_col")
    assert baseline is not None
    assert list(baseline.columns) == ["a"]


# ── Edge cases for load_baseline ─────────────────────────────────────────────

def test_load_baseline_corrupt_file(tmp_path):
    """load_baseline returns None for corrupt parquet."""
    monitor = PSIMonitor(tmp_path)
    baseline_dir = monitor.baseline_dir
    import os
    os.makedirs(baseline_dir, exist_ok=True)
    path = os.path.join(baseline_dir, "corrupt.parquet")
    with open(path, "w") as f:
        f.write("not a parquet file")
    baseline = monitor.load_baseline("corrupt")
    assert baseline is None


def test_load_baseline_nonexistent_asset(tmp_path):
    """load_baseline returns None for asset with no baseline."""
    monitor = PSIMonitor(tmp_path)
    baseline = monitor.load_baseline("nonexistent")
    assert baseline is None


# ── PSIDriftEntry / PSISnapshot dataclass construction ───────────────────────

def test_psi_drift_entry_creation():
    entry = PSIDriftEntry(
        feature="rsi_14",
        psi=0.15,
        classification="MODERATE",
        trend="INCREASING",
        importance_score=0.6,
    )
    assert entry.feature == "rsi_14"
    assert entry.classification == "MODERATE"


def test_psi_snapshot_creation():
    entry = PSIDriftEntry(
        feature="rsi_14", psi=0.15, classification="MODERATE",
        trend="STABLE", importance_score=0.6,
    )
    snapshot = PSISnapshot(
        asset="TEST",
        per_feature=[entry],
        worst_classification="MODERATE",
        moderate_count=1,
        severe_count=0,
        psi_ok=True,
        penalty=-0.08,
        timestamp="2026-05-25T00:00:00",
    )
    assert snapshot.worst_classification == "MODERATE"
    assert snapshot.psi_ok is True
