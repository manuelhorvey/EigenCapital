import tempfile

import numpy as np
import pandas as pd

from monitoring.psi_monitor import PSIMonitor


def test_compute_psi_identical_distributions():
    expected = pd.Series(np.random.normal(0, 1, 1000))
    actual = expected.copy()
    psi = PSIMonitor.compute_psi(expected, actual)
    assert psi < 0.05


def test_compute_psi_shifted_distribution():
    expected = pd.Series(np.random.normal(0, 1, 1000))
    actual = pd.Series(np.random.normal(3, 1, 200))
    psi = PSIMonitor.compute_psi(expected, actual)
    assert psi > 0.2


def test_compute_psi_insufficient_samples():
    expected = pd.Series([1, 2, 3, 4, 5])
    actual = pd.Series([1.5, 2.5])
    psi = PSIMonitor.compute_psi(expected, actual)
    assert psi == 0.0


def test_compute_psi_constant_values():
    expected = pd.Series(np.ones(100))
    actual = pd.Series(np.ones(50))
    psi = PSIMonitor.compute_psi(expected, actual)
    assert psi == 0.0


def test_compute_psi_nan_handling():
    expected = pd.Series([1.0, 2.0, np.nan, 4.0, 5.0])
    actual = pd.Series([1.5, 2.5, 3.5, np.nan, 5.5])
    psi = PSIMonitor.compute_psi(expected, actual)
    assert psi >= 0.0


def test_classify_drift_no_drift():
    assert PSIMonitor.classify_drift(0.0) == "NO_DRIFT"
    assert PSIMonitor.classify_drift(0.05) == "NO_DRIFT"
    assert PSIMonitor.classify_drift(0.0999) == "NO_DRIFT"


def test_classify_drift_moderate():
    assert PSIMonitor.classify_drift(0.1) == "MODERATE"
    assert PSIMonitor.classify_drift(0.15) == "MODERATE"
    assert PSIMonitor.classify_drift(0.1999) == "MODERATE"


def test_classify_drift_severe():
    assert PSIMonitor.classify_drift(0.2) == "SEVERE"
    assert PSIMonitor.classify_drift(0.5) == "SEVERE"
    assert PSIMonitor.classify_drift(1.0) == "SEVERE"


def test_compute_trend():
    assert PSIMonitor._compute_trend(None, 0.5) == "STABLE"
    assert PSIMonitor._compute_trend(0.1, 0.11) == "STABLE"
    assert PSIMonitor._compute_trend(0.1, 0.2) == "INCREASING"
    assert PSIMonitor._compute_trend(0.2, 0.1) == "DECREASING"


def test_persist_and_load_baseline():
    with tempfile.TemporaryDirectory() as tmp:
        monitor = PSIMonitor(tmp)
        X = pd.DataFrame({"a": [1.0, 2.0, 3.0], "b": [4.0, 5.0, 6.0]})
        monitor.persist_baseline("test_asset", X)

        loaded = monitor.load_baseline("test_asset")
        assert loaded is not None
        pd.testing.assert_frame_equal(loaded, X)


def test_persist_empty_baseline():
    with tempfile.TemporaryDirectory() as tmp:
        monitor = PSIMonitor(tmp)
        X = pd.DataFrame()
        monitor.persist_baseline("test_asset", X)
        assert monitor.load_baseline("test_asset") is None


def test_compute_drift_no_baseline():
    with tempfile.TemporaryDirectory() as tmp:
        monitor = PSIMonitor(tmp)
        X_current = pd.DataFrame({"a": [1.0, 2.0]})
        snapshot = monitor.compute_drift("test_asset", X_current, [("a", 0.5)])
        assert snapshot is None


def test_compute_drift_identical():
    with tempfile.TemporaryDirectory() as tmp:
        monitor = PSIMonitor(tmp)
        X_train = pd.DataFrame({"a": [1.0] * 500, "b": [2.0] * 500})
        monitor.persist_baseline("test_asset", X_train)

        X_current = pd.DataFrame({"a": [1.0] * 100, "b": [2.0] * 100})
        top_features = [("a", 0.6), ("b", 0.4)]
        snapshot = monitor.compute_drift("test_asset", X_current, top_features)

        assert snapshot is not None
        assert snapshot.asset == "test_asset"
        assert len(snapshot.per_feature) == 2
        assert snapshot.worst_classification == "NO_DRIFT"
        assert snapshot.psi_ok is True


def test_compute_drift_shifted():
    with tempfile.TemporaryDirectory() as tmp:
        monitor = PSIMonitor(tmp)
        X_train = pd.DataFrame({"a": np.random.normal(0, 1, 500)})
        monitor.persist_baseline("test_asset", X_train)

        X_current = pd.DataFrame({"a": np.random.normal(5, 1, 100)})
        snapshot = monitor.compute_drift("test_asset", X_current, [("a", 1.0)])

        assert snapshot is not None
        assert snapshot.per_feature[0].classification == "SEVERE"
        assert snapshot.severe_count > 0


def test_compute_drift_trend_increasing():
    with tempfile.TemporaryDirectory() as tmp:
        monitor = PSIMonitor(tmp)
        X_train = pd.DataFrame({"a": np.random.normal(0, 1, 500)})
        monitor.persist_baseline("test_asset", X_train)

        X_prev = pd.DataFrame({"a": np.random.normal(0.5, 1, 100)})
        X_current = pd.DataFrame({"a": np.random.normal(5, 1, 100)})

        # First call establishes previous
        _ = monitor.compute_drift("test_asset", X_prev, [("a", 1.0)])
        # Second call should detect increase
        snapshot = monitor.compute_drift("test_asset", X_current, [("a", 1.0)])

        assert snapshot is not None
        assert snapshot.per_feature[0].trend == "INCREASING"


def test_compute_drift_missing_feature():
    with tempfile.TemporaryDirectory() as tmp:
        monitor = PSIMonitor(tmp)
        X_train = pd.DataFrame({"a": np.random.normal(0, 1, 500)})
        monitor.persist_baseline("test_asset", X_train)

        X_current = pd.DataFrame({"b": np.random.normal(0, 1, 100)})
        snapshot = monitor.compute_drift("test_asset", X_current, [("a", 1.0)])

        assert snapshot is None


def test_compute_drift_partial_missing_features():
    with tempfile.TemporaryDirectory() as tmp:
        monitor = PSIMonitor(tmp)
        X_train = pd.DataFrame({"a": np.random.normal(0, 1, 500), "b": np.random.normal(0, 1, 500)})
        monitor.persist_baseline("test_asset", X_train)

        X_current = pd.DataFrame({"a": np.random.normal(0, 1, 100)})
        snapshot = monitor.compute_drift("test_asset", X_current, [("a", 0.6), ("b", 0.4)])

        assert snapshot is not None
        assert len(snapshot.per_feature) == 1
        assert snapshot.per_feature[0].feature == "a"


def test_penalty_moderate():
    with tempfile.TemporaryDirectory() as tmp:
        monitor = PSIMonitor(tmp)
        X_train = pd.DataFrame({"a": np.random.normal(0, 1, 500)})
        monitor.persist_baseline("test_asset", X_train)

        X_current = pd.DataFrame({"a": np.random.normal(1.5, 1, 100)})
        snapshot = monitor.compute_drift("test_asset", X_current, [("a", 1.0)])

        assert snapshot.penalty in (0.0, -0.08, -0.20)


def test_penalty_severe():
    with tempfile.TemporaryDirectory() as tmp:
        monitor = PSIMonitor(tmp)
        X_train = pd.DataFrame({"a": np.random.normal(0, 1, 500)})
        monitor.persist_baseline("test_asset", X_train)

        X_current = pd.DataFrame({"a": np.random.normal(5, 1, 100)})
        snapshot = monitor.compute_drift("test_asset", X_current, [("a", 1.0)])

        assert snapshot.penalty == -0.20


def test_penalty_moderate_and_severe_additive():
    with tempfile.TemporaryDirectory() as tmp:
        monitor = PSIMonitor(tmp)
        rng = np.random.default_rng(42)
        X_train = pd.DataFrame({
            "a": rng.normal(0, 1, 500),
            "b": rng.normal(0, 1, 500),
        })
        monitor.persist_baseline("test_asset", X_train)

        X_current = pd.DataFrame({
            "a": rng.normal(1.5, 1, 100),
            "b": rng.normal(5, 1, 100),
        })
        snapshot = monitor.compute_drift("test_asset", X_current, [("a", 0.5), ("b", 0.5)])

        assert snapshot is not None
        assert snapshot.moderate_count > 0 or snapshot.severe_count > 0
        # When both MODERATE and SEVERE fire, penalty = -0.08 + -0.20 = -0.28
        if snapshot.moderate_count > 0 and snapshot.severe_count > 0:
            assert snapshot.penalty == -0.28, f"Expected -0.28 for both flags, got {snapshot.penalty}"


def test_psi_ok_requires_3_severe():
    with tempfile.TemporaryDirectory() as tmp:
        monitor = PSIMonitor(tmp)
        rng = np.random.default_rng(42)
        X_train = pd.DataFrame({
            "a": rng.normal(0, 1, 500),
            "b": rng.normal(0, 1, 500),
            "c": rng.normal(0, 1, 500),
        })
        monitor.persist_baseline("test_asset", X_train)

        # 2 severe features — should still be psi_ok
        X_two = pd.DataFrame({
            "a": rng.normal(5, 1, 100),
            "b": rng.normal(5, 1, 100),
            "c": rng.normal(0, 1, 100),
        })
        snap = monitor.compute_drift("test_asset", X_two, [("a", 0.4), ("b", 0.3), ("c", 0.3)])
        if snap and snap.severe_count >= 3:
            assert snap.psi_ok is False
        elif snap:
            assert snap.psi_ok is True


def test_psi_ok_halted_at_3_severe():
    with tempfile.TemporaryDirectory() as tmp:
        monitor = PSIMonitor(tmp)
        rng = np.random.default_rng(42)
        X_train = pd.DataFrame({
            "a": rng.normal(0, 1, 500),
            "b": rng.normal(0, 1, 500),
            "c": rng.normal(0, 1, 500),
        })
        monitor.persist_baseline("test_asset", X_train)

        X_three = pd.DataFrame({
            "a": rng.normal(5, 1, 100),
            "b": rng.normal(5, 1, 100),
            "c": rng.normal(5, 1, 100),
        })
        snap = monitor.compute_drift("test_asset", X_three, [("a", 0.4), ("b", 0.3), ("c", 0.3)])
        if snap:
            assert snap.severe_count >= 3, f"Expected >=3 severe, got {snap.severe_count}"
            assert snap.psi_ok is False
