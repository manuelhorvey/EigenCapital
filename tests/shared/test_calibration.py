"""Tests for the calibration module."""

import numpy as np
import pytest

from shared.calibration import BetaCalibrator, BinnedCalibrator, CalibrationRegistry, ECETracker
from shared.calibration.calibrator import compute_ece

# ── Fixtures ──────────────────────────────────────────────────────────────────


@pytest.fixture
def simple_miscalibrated():
    """Systematically overconfident probabilities: predicts 0.3-0.8 but actual
    threshold is 0.6, creating a clear miscalibration pattern."""
    rng = np.random.default_rng(42)
    p_long = rng.uniform(0.3, 0.8, 500)
    outcomes = (p_long > 0.6).astype(int)
    return p_long, outcomes


@pytest.fixture
def perfect_data():
    """Perfectly calibrated: P(outcome=1) ≈ predicted probability.
    Uses many samples so binomial noise is small."""
    rng = np.random.default_rng(123)
    probs = np.linspace(0.05, 0.95, 1000)
    outcomes = rng.binomial(1, probs)
    return probs, outcomes


# ── BinnedCalibrator ──────────────────────────────────────────────────────────


class TestBinnedCalibrator:
    def test_fit_and_calibrate(self):
        p_long = np.array([0.1, 0.2, 0.3, 0.4, 0.5, 0.6, 0.7, 0.8, 0.9])
        outcomes = np.array([0, 0, 0, 0, 1, 1, 1, 1, 1])
        cal = BinnedCalibrator(n_bins=5).fit(p_long, outcomes)
        result = cal.calibrate(np.array([0.25, 0.55, 0.85]))
        assert all(0.001 <= r <= 0.999 for r in result)
        assert cal.fitted

    def test_perfect_calibration(self, perfect_data):
        p_long, outcomes = perfect_data
        ece = compute_ece(p_long, outcomes)
        assert ece < 0.12

    def test_miscalibrated_improves(self, simple_miscalibrated):
        p_long, outcomes = simple_miscalibrated
        ece_before = compute_ece(p_long, outcomes)
        cal = BinnedCalibrator(n_bins=10).fit(p_long, outcomes)
        p_cal = cal.calibrate(p_long)
        ece_after = compute_ece(p_cal, outcomes)
        assert ece_after < ece_before * 0.9

    def test_bin_edge(self):
        p_long = np.array([0.0, 0.1, 0.2, 0.3, 0.4, 0.5, 0.6, 0.7, 0.8, 0.9, 1.0])
        outcomes = np.array([0, 0, 0, 0, 0, 1, 1, 1, 1, 1, 1])
        cal = BinnedCalibrator(n_bins=5).fit(p_long, outcomes)
        result = cal.calibrate(np.array([0.0, 0.5, 1.0]))
        assert all(0.001 <= r <= 0.999 for r in result)
        assert result[2] >= result[0]

    def test_sparse_bins(self):
        p_long = np.array([0.05, 0.15, 0.25, 0.35, 0.45, 0.55, 0.65, 0.75, 0.85, 0.95])
        outcomes = np.array([0, 0, 0, 0, 0, 1, 1, 1, 1, 1])
        cal = BinnedCalibrator(n_bins=10, min_samples_per_bin=5).fit(p_long, outcomes)
        # Each bin should have 1 sample, below min_samples_per_bin=5,
        # so all bins should use neutral 0.5 fallback
        assert cal.bin_empirical_probs is not None
        assert all(emp == 0.5 for emp in cal.bin_empirical_probs)

    def test_save_load(self, tmp_path):
        p_long = np.array([0.1, 0.2, 0.3, 0.4, 0.5, 0.6, 0.7, 0.8, 0.9])
        outcomes = np.array([0, 0, 0, 0, 1, 1, 1, 1, 1])
        cal = BinnedCalibrator(n_bins=5).fit(p_long, outcomes)
        path = tmp_path / "test_cal.json"
        cal.save(str(path))
        loaded = BinnedCalibrator.load(str(path))
        assert loaded.fitted
        for raw in [0.1, 0.5, 0.9]:
            assert abs(cal.calibrate(np.array([raw]))[0] - loaded.calibrate(np.array([raw]))[0]) < 0.01

    def test_single_value(self):
        p_long = np.full(50, 0.7)
        outcomes = np.ones(50, dtype=int)
        cal = BinnedCalibrator(n_bins=5).fit(p_long, outcomes)
        result = cal.calibrate(np.array([0.7]))
        assert 0.001 <= result[0] <= 0.999

    def test_not_fitted_returns_raw(self):
        cal = BinnedCalibrator(n_bins=5)
        result = cal.calibrate(np.array([0.5]))
        assert result[0] == 0.5


# ── BetaCalibrator ────────────────────────────────────────────────────────────


class TestBetaCalibrator:
    def test_fit_and_calibrate(self):
        rng = np.random.default_rng(42)
        p_long = rng.uniform(0.1, 0.9, 500)
        outcomes = (p_long > 0.5).astype(int)
        cal = BetaCalibrator().fit(p_long, outcomes)
        result = cal.calibrate(np.array([0.1, 0.5, 0.9]))
        assert all(0.001 <= r <= 0.999 for r in result)
        assert cal.fitted

    def test_monotonic(self):
        rng = np.random.default_rng(42)
        p_long = rng.uniform(0.1, 0.9, 500)
        outcomes = (p_long > 0.5).astype(int)
        cal = BetaCalibrator().fit(p_long, outcomes)
        test_vals = np.array([0.1, 0.25, 0.4, 0.5, 0.6, 0.75, 0.9])
        calibrated = cal.calibrate(test_vals)
        assert np.all(np.diff(calibrated) >= -1e-6)

    def test_save_load(self, tmp_path):
        rng = np.random.default_rng(42)
        p_long = rng.uniform(0.1, 0.9, 500)
        outcomes = (p_long > 0.5).astype(int)
        cal = BetaCalibrator().fit(p_long, outcomes)
        path = tmp_path / "test_beta.json"
        cal.save(str(path))
        loaded = BetaCalibrator.load(str(path))
        assert loaded.fitted
        for raw in [0.1, 0.5, 0.9]:
            assert abs(cal.calibrate(np.array([raw]))[0] - loaded.calibrate(np.array([raw]))[0]) < 0.01


# ── compute_ece ───────────────────────────────────────────────────────────────


class TestComputeECE:
    def test_perfect(self, perfect_data):
        p_long, outcomes = perfect_data
        ece = compute_ece(p_long, outcomes, n_bins=5)
        assert ece < 0.05

    def test_bad(self):
        p_long = np.full(200, 0.5)
        outcomes = np.ones(200, dtype=int)
        ece = compute_ece(p_long, outcomes, n_bins=10)
        assert ece > 0.4


# ── CalibrationRegistry ───────────────────────────────────────────────────────


class TestCalibrationRegistry:
    def test_register_and_calibrate(self):
        p_long = np.array([0.1, 0.2, 0.3, 0.4, 0.5, 0.6, 0.7, 0.8, 0.9])
        outcomes = np.array([0, 0, 0, 0, 1, 1, 1, 1, 1])
        cal = BinnedCalibrator(n_bins=5).fit(p_long, outcomes)
        registry = CalibrationRegistry()
        registry.register("EURUSD", cal)
        result = registry.calibrate("EURUSD", 0.5)
        assert 0.001 <= result <= 0.999

    def test_no_calibrator(self):
        registry = CalibrationRegistry()
        result = registry.calibrate("UNKNOWN", 0.5)
        assert result == 0.5

    def test_save_load_all(self, tmp_path):
        cal_dir = tmp_path / "calibration"
        p1 = np.array([0.1, 0.2, 0.3, 0.4, 0.5, 0.6, 0.7, 0.8, 0.9])
        o1 = np.array([0, 0, 0, 0, 1, 1, 1, 1, 1])
        rng = np.random.default_rng(42)
        p2 = rng.uniform(0.1, 0.9, 500)
        o2 = (p2 > 0.5).astype(int)

        registry = CalibrationRegistry()
        registry.register("EURUSD", BinnedCalibrator(n_bins=5).fit(p1, o1))
        registry.register("GBPUSD", BetaCalibrator().fit(p2, o2))
        count = registry.save_all(str(cal_dir))
        assert count == 2

        loaded = CalibrationRegistry()
        lcount = loaded.load_all(str(cal_dir))
        assert lcount == 2
        assert loaded.get("EURUSD") is not None
        assert loaded.get("GBPUSD") is not None
        eur_result = loaded.calibrate("EURUSD", 0.5)
        assert 0.001 <= eur_result <= 0.999

    def test_empty_load(self, tmp_path):
        registry = CalibrationRegistry()
        count = registry.load_all(str(tmp_path / "nonexistent"))
        assert count == 0


# ── ECETracker ────────────────────────────────────────────────────────────────


class TestECETracker:
    def test_record(self):
        tracker = ECETracker(window=200, drift_threshold=0.15)
        rng = np.random.default_rng(42)
        p_long = rng.uniform(0.3, 0.8, 200)
        outcomes = (p_long > 0.6).astype(int)
        for prob, outcome in zip(p_long, outcomes):
            tracker.record("EURUSD", prob, outcome)
        ece = tracker.get_ece("EURUSD")
        assert ece is not None
        assert 0.0 <= ece <= 1.0

    def test_insufficient_data(self):
        tracker = ECETracker(window=200, drift_threshold=0.15)
        for i in range(19):
            tracker.record("EURUSD", 0.5, 1)
        ece = tracker.get_ece("EURUSD")
        assert ece is None

    def test_drift_detection(self):
        tracker = ECETracker(window=200, drift_threshold=0.1)
        rng = np.random.default_rng(42)
        p_long = rng.uniform(0.3, 0.8, 200)
        outcomes = (p_long > 0.6).astype(int)
        for prob, outcome in zip(p_long, outcomes):
            tracker.record("EURUSD", prob, outcome)
        for _ in range(12):
            tracker.update_drift("EURUSD")
        alerts = tracker.drift_alerts()
        assert "EURUSD" in alerts

    def test_drift_clears(self):
        tracker = ECETracker(window=200, drift_threshold=0.1)
        rng = np.random.default_rng(42)
        p_long_bad = rng.uniform(0.3, 0.8, 200)
        outcomes_bad = (p_long_bad > 0.6).astype(int)
        for prob, outcome in zip(p_long_bad, outcomes_bad):
            tracker.record("EURUSD", prob, outcome)
        for _ in range(12):
            tracker.update_drift("EURUSD")
        assert "EURUSD" in tracker.drift_alerts()

        # Push out bad data with well-calibrated data
        p_long_good = np.linspace(0.05, 0.95, 200)
        outcomes_good = rng.binomial(1, p_long_good)
        for prob, outcome in zip(p_long_good, outcomes_good):
            tracker.record("EURUSD", prob, outcome)
        tracker.update_drift("EURUSD")
        alerts = tracker.drift_alerts()
        assert "EURUSD" not in alerts

    def test_multiple_assets(self):
        tracker = ECETracker(window=200, drift_threshold=0.15)
        rng = np.random.default_rng(42)
        p1 = rng.uniform(0.3, 0.8, 200)
        o1 = (p1 > 0.6).astype(int)
        p2 = rng.uniform(0.3, 0.8, 200)
        o2 = (p2 > 0.6).astype(int)
        for prob, outcome in zip(p1, o1):
            tracker.record("EURUSD", prob, outcome)
        for prob, outcome in zip(p2, o2):
            tracker.record("GBPUSD", prob, outcome)
        ece1 = tracker.get_ece("EURUSD")
        ece2 = tracker.get_ece("GBPUSD")
        assert ece1 is not None
        assert ece2 is not None
        assert tracker.get_ece("UNKNOWN") is None


# ── Integration ────────────────────────────────────────────────────────────────


class TestCalibrationIntegration:
    def test_calibration_improves_ece(self, simple_miscalibrated):
        p_long, outcomes = simple_miscalibrated
        ece_before = compute_ece(p_long, outcomes)
        cal = BinnedCalibrator(n_bins=10, min_samples_per_bin=10).fit(p_long, outcomes)
        p_cal = cal.calibrate(p_long)
        ece_after = compute_ece(p_cal, outcomes)
        assert ece_after < ece_before

    def test_calibration_preserves_order(self):
        """Each bin center has many repeats so empirical probs are monotonic."""
        rng = np.random.default_rng(42)
        n_per_bin = 200
        n_bins = 10
        bin_centers = np.linspace(0.05, 0.95, n_bins)
        p_long = np.repeat(bin_centers, n_per_bin)
        outcomes = rng.binomial(1, p_long)
        cal = BinnedCalibrator(n_bins=n_bins).fit(p_long, outcomes)
        p_cal = cal.calibrate(p_long)
        assert np.all(np.diff(p_cal) >= -1e-6)
