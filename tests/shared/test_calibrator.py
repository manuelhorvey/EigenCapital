"""Tests for ``shared/calibration/calibrator.py`` — calibration models."""

import numpy as np

from shared.calibration.calibrator import (
    BetaCalibrator,
    BinnedCalibrator,
    DirectionalCalibrator,
    PlattCalibrator,
    compute_ece,
)

# ═══════════════════════════════════════════════════════════════════
# compute_ece
# ═══════════════════════════════════════════════════════════════════


class TestComputeECE:
    def test_perfect_calibration_returns_low_ece(self):
        # Single bin with perfect alignment
        probs = np.array([0.0, 0.5, 0.5, 1.0])
        outcomes = np.array([0, 0, 1, 1])
        ece = compute_ece(probs, outcomes, n_bins=4)
        assert ece >= 0.0

    def test_miscalibration_returns_positive(self):
        probs = np.array([0.9, 0.9, 0.9, 0.1, 0.1, 0.1])
        outcomes = np.array([0, 0, 0, 1, 1, 1])
        ece = compute_ece(probs, outcomes, n_bins=2)
        assert ece > 0.3

    def test_returns_zero_when_fewer_than_n_bins(self):
        ece = compute_ece(np.array([0.5, 0.6]), np.array([1, 0]), n_bins=10)
        assert ece == 0.0


# ═══════════════════════════════════════════════════════════════════
# BinnedCalibrator
# ═══════════════════════════════════════════════════════════════════


class TestBinnedCalibrator:
    def test_fit_and_calibrate(self):
        cal = BinnedCalibrator(n_bins=5)
        p_long = np.array([0.1, 0.2, 0.3, 0.7, 0.8, 0.9])
        outcomes = np.array([0, 0, 0, 1, 1, 1])
        cal.fit(p_long, outcomes)
        assert cal.fitted is True
        result = cal.calibrate(np.array([0.25, 0.75]))
        assert 0.0 < result[0] < 1.0
        assert 0.0 < result[1] < 1.0

    def test_calibrate_returns_clipped_values(self):
        cal = BinnedCalibrator(n_bins=5)
        cal.fit(np.array([0.1, 0.2, 0.3, 0.7, 0.8, 0.9]), np.array([0, 0, 0, 1, 1, 1]))
        result = cal.calibrate(np.array([0.0, 1.0]))
        assert result[0] >= 0.001
        assert result[1] <= 0.999

    def test_not_fitted_returns_raw(self):
        cal = BinnedCalibrator(n_bins=5)
        result = cal.calibrate(np.array([0.5, 0.6]))
        assert np.allclose(result, [0.5, 0.6])

    def test_save_and_load(self, tmp_path):
        cal = BinnedCalibrator(n_bins=5)
        cal.fit(np.array([0.1, 0.3, 0.7, 0.9]), np.array([0, 0, 1, 1]))
        path = tmp_path / "calibrator.json"
        cal.save(str(path))
        loaded = BinnedCalibrator.load(str(path))
        assert loaded.fitted is True
        assert loaded.n_bins == 5

    def test_save_and_load_unfitted(self, tmp_path):
        cal = BinnedCalibrator(n_bins=10)
        path = tmp_path / "unfitted.json"
        cal.save(str(path))
        loaded = BinnedCalibrator.load(str(path))
        assert loaded.fitted is False
        assert loaded.n_bins == 10


# ═══════════════════════════════════════════════════════════════════
# BetaCalibrator
# ═══════════════════════════════════════════════════════════════════


class TestBetaCalibrator:
    def test_fit_and_calibrate(self):
        cal = BetaCalibrator()
        rng = np.random.default_rng(42)
        p_long = rng.uniform(0.3, 0.7, 200)
        outcomes = (p_long + rng.normal(0, 0.1, 200) > 0.5).astype(int)
        cal.fit(p_long, outcomes)
        result = cal.calibrate(np.array([0.4, 0.6]))
        assert 0.0 < result[0] < 1.0
        assert 0.0 < result[1] < 1.0

    def test_not_fitted_returns_raw(self):
        cal = BetaCalibrator()
        result = cal.calibrate(np.array([0.5, 0.6]))
        assert np.allclose(result, [0.5, 0.6])

    def test_save_and_load(self, tmp_path):
        cal = BetaCalibrator()
        rng = np.random.default_rng(42)
        cal.fit(rng.uniform(0.3, 0.7, 200), (rng.uniform(0.3, 0.7, 200) > 0.5).astype(int))
        path = tmp_path / "beta_cal.json"
        cal.save(str(path))
        loaded = BetaCalibrator.load(str(path))
        assert loaded.fitted is True
        assert abs(loaded.a) > 0

    def test_save_and_load_unfitted(self, tmp_path):
        cal = BetaCalibrator()
        path = tmp_path / "unfitted.json"
        cal.save(str(path))
        loaded = BetaCalibrator.load(str(path))
        assert loaded.fitted is True  # save always writes current params
        assert loaded.a == 1.0


# ═══════════════════════════════════════════════════════════════════
# DirectionalCalibrator
# ═══════════════════════════════════════════════════════════════════


class TestDirectionalCalibrator:
    def _make_sell_data(self, n=20):
        """Helper: n SELL predictions with ~60% win rate."""
        p_long = np.array([0.1 + 0.05 * (i % 4) for i in range(n)])
        outcomes = np.array([0 if i < n * 4 // 10 else 1 for i in range(n)])
        # Flip: SELL perspective means p_long < 0.5
        return p_long, 1 - outcomes

    def _make_buy_data(self, n=20):
        """Helper: n BUY predictions with ~60% win rate."""
        p_long = np.array([0.6 + 0.05 * (i % 8) for i in range(n)])
        outcomes = np.array([0 if i < n * 4 // 10 else 1 for i in range(n)])
        return p_long, outcomes

    def test_fit_buy_and_sell(self):
        cal = DirectionalCalibrator(n_bins=5, min_samples_per_bin=1)
        sell_plong, sell_out = self._make_sell_data(20)
        buy_plong, buy_out = self._make_buy_data(20)
        p_long = np.concatenate([sell_plong, buy_plong])
        outcomes = np.concatenate([sell_out, buy_out])
        cal.fit(p_long, outcomes)
        assert cal.fitted is True
        assert cal._buy_fitted is True
        assert cal._sell_fitted is True

    def test_calibrate_applies_direction_correctly(self):
        cal = DirectionalCalibrator(n_bins=5, min_samples_per_bin=1)
        sell_plong, sell_out = self._make_sell_data(20)
        buy_plong, buy_out = self._make_buy_data(20)
        p_long = np.concatenate([sell_plong, buy_plong])
        outcomes = np.concatenate([sell_out, buy_out])
        cal.fit(p_long, outcomes)
        result = cal.calibrate(np.array([0.9, 0.1]))
        assert 0.0 < result[0] < 1.0
        assert 0.0 < result[1] < 1.0

    def test_not_fitted_returns_raw(self):
        cal = DirectionalCalibrator()
        result = cal.calibrate(np.array([0.5, 0.6]))
        assert np.allclose(result, [0.5, 0.6])

    def test_save_and_load(self, tmp_path):
        cal = DirectionalCalibrator(n_bins=5, min_samples_per_bin=1)
        sell_plong, sell_out = self._make_sell_data(20)
        buy_plong, buy_out = self._make_buy_data(20)
        p_long = np.concatenate([sell_plong, buy_plong])
        outcomes = np.concatenate([sell_out, buy_out])
        cal.fit(p_long, outcomes)
        path = tmp_path / "dir_cal.json"
        cal.save(str(path))
        loaded = DirectionalCalibrator.load(str(path))
        assert loaded.fitted is True
        assert loaded.n_bins == 5

    def test_fit_with_explicit_predictions(self):
        cal = DirectionalCalibrator(n_bins=5, min_samples_per_bin=1)
        p_long = np.array([0.1, 0.1, 0.1, 0.7, 0.7, 0.7])
        outcomes = np.array([0, 0, 1, 1, 1, 0])
        predictions = np.array([-1, -1, -1, 1, 1, 1])
        cal.fit(p_long, outcomes, predictions=predictions)
        assert cal.fitted is True
        assert cal._buy_fitted is True
        assert cal._sell_fitted is True

    def test_skip_buy_when_insufficient_data(self):
        cal = DirectionalCalibrator(n_bins=5, min_samples_per_bin=10)
        p_long = np.array([0.1, 0.2, 0.9, 0.9])
        cal.fit(p_long, np.array([0, 1, 1, 1]))
        assert not cal._buy_fitted  # only 2 BUY predictions, need 30
        assert not cal._sell_fitted  # only 2 SELL predictions, need 30


# ═══════════════════════════════════════════════════════════════════
# PlattCalibrator
# ═══════════════════════════════════════════════════════════════════


class TestPlattCalibrator:
    def test_fit_and_calibrate(self):
        cal = PlattCalibrator()
        rng = np.random.default_rng(42)
        p_long = rng.uniform(0.3, 0.7, 200)
        outcomes = (p_long + rng.normal(0, 0.1, 200) > 0.5).astype(int)
        cal.fit(p_long, outcomes)
        assert cal.fitted is True
        result = cal.calibrate(np.array([0.4, 0.6]))
        assert 0.0 < result[0] < 1.0
        assert 0.0 < result[1] < 1.0

    def test_handles_compressed_distribution(self):
        """Platt must handle severely compressed p_long (std < 0.05)."""
        cal = PlattCalibrator()
        rng = np.random.default_rng(42)
        # Simulate AUDUSD-like compression: p_long in [0.45, 0.48]
        p_long = rng.uniform(0.45, 0.48, 200)
        outcomes = (rng.uniform(0, 1, 200) > 0.5).astype(int)
        cal.fit(p_long, outcomes)
        assert cal.fitted is True
        # Should produce varied calibrated probabilities
        result = cal.calibrate(np.array([0.45, 0.46, 0.47, 0.48]))
        assert len(np.unique(result.round(3))) > 1  # Not all same value

    def test_monotonic_preserved(self):
        """Platt scaling is monotonic — higher raw → higher calibrated."""
        cal = PlattCalibrator()
        rng = np.random.default_rng(42)
        p_long = rng.uniform(0.3, 0.7, 200)
        outcomes = (p_long + rng.normal(0, 0.1, 200) > 0.5).astype(int)
        cal.fit(p_long, outcomes)
        raw = np.array([0.1, 0.3, 0.5, 0.7, 0.9])
        calib = cal.calibrate(raw)
        assert all(calib[i] <= calib[i + 1] for i in range(len(calib) - 1))

    def test_not_fitted_returns_raw(self):
        cal = PlattCalibrator()
        result = cal.calibrate(np.array([0.5, 0.6]))
        assert np.allclose(result, [0.5, 0.6])

    def test_save_and_load(self, tmp_path):
        cal = PlattCalibrator()
        rng = np.random.default_rng(42)
        p_long = rng.uniform(0.3, 0.7, 200)
        outcomes = (p_long + rng.normal(0, 0.1, 200) > 0.5).astype(int)
        cal.fit(p_long, outcomes)
        path = tmp_path / "platt_cal.json"
        cal.save(str(path))
        loaded = PlattCalibrator.load(str(path))
        assert loaded.fitted is True
        assert abs(loaded.a) > 0
        # Loaded model should produce same predictions
        orig_result = cal.calibrate(np.array([0.4, 0.6]))
        loaded_result = loaded.calibrate(np.array([0.4, 0.6]))
        assert np.allclose(orig_result, loaded_result, atol=1e-6)

    def test_save_and_load_unfitted(self, tmp_path):
        cal = PlattCalibrator()
        path = tmp_path / "unfitted.json"
        cal.save(str(path))
        loaded = PlattCalibrator.load(str(path))
        assert loaded.fitted is True
        assert loaded.a == 1.0


# ═══════════════════════════════════════════════════════════════════
# DirectionalCalibrator with Platt Base
# ═══════════════════════════════════════════════════════════════════


class TestDirectionalPlattCalibrator:
    """DirectionalCalibrator with base_calibrator='platt'."""

    def _make_data(self, n_buy=30, n_sell=30):
        """Generate buy/sell data with directional bias."""
        buy_p = np.array([0.6 + 0.05 * (i % 8) for i in range(n_buy)])
        buy_out = (buy_p > 0.65).astype(int)
        sell_p = np.array([0.2 + 0.05 * (i % 4) for i in range(n_sell)])
        sell_out = (sell_p < 0.25).astype(int)
        p_long = np.concatenate([sell_p, buy_p])
        outcomes = np.concatenate([sell_out, buy_out])
        return p_long, outcomes

    def test_fit_and_calibrate(self):
        cal = DirectionalCalibrator(base_calibrator="platt", min_samples_per_bin=1)
        p_long, outcomes = self._make_data(30, 30)
        cal.fit(p_long, outcomes)
        assert cal.fitted is True
        assert cal._buy_fitted is True
        assert cal._sell_fitted is True
        result = cal.calibrate(np.array([0.9, 0.1]))
        assert 0.0 < result[0] < 1.0
        assert 0.0 < result[1] < 1.0

    def test_directional_ece_improvement(self):
        """Directional Platt should improve BUY calibration specifically."""
        cal = DirectionalCalibrator(base_calibrator="platt", min_samples_per_bin=1)
        rng = np.random.default_rng(42)
        n = 100
        p_long = np.concatenate([
            rng.uniform(0.55, 0.75, n),  # BUY predictions
            rng.uniform(0.25, 0.45, n),  # SELL predictions
        ])
        # Make BUY predictions overconfident (actual WR ~55%)
        buy_out = (rng.uniform(0, 1, n) < 0.55).astype(int)
        sell_out = (rng.uniform(0, 1, n) < 0.65).astype(int)
        outcomes = np.concatenate([buy_out, sell_out])
        cal.fit(p_long, outcomes)
        result = cal.calibrate(p_long)
        assert np.all(result >= 0.001)
        assert np.all(result <= 0.999)

    def test_handles_compressed_distribution(self):
        """Directional Platt must handle compressed p_long distributions."""
        cal = DirectionalCalibrator(base_calibrator="platt", min_samples_per_bin=1)
        rng = np.random.default_rng(42)
        # Simulate compressed range
        p_long = rng.uniform(0.45, 0.52, 200)
        outcomes = (rng.uniform(0, 1, 200) > 0.5).astype(int)
        cal.fit(p_long, outcomes)
        result = cal.calibrate(np.array([0.46, 0.48, 0.50, 0.51]))
        assert np.all(result >= 0.001)
        assert np.all(result <= 0.999)

    def test_not_fitted_returns_raw(self):
        cal = DirectionalCalibrator(base_calibrator="platt")
        result = cal.calibrate(np.array([0.5, 0.6]))
        assert np.allclose(result, [0.5, 0.6])

    def test_save_and_load(self, tmp_path):
        cal = DirectionalCalibrator(base_calibrator="platt", min_samples_per_bin=1)
        p_long, outcomes = self._make_data(30, 30)
        cal.fit(p_long, outcomes)
        path = tmp_path / "dir_platt.json"
        cal.save(str(path))
        loaded = DirectionalCalibrator.load(str(path))
        assert loaded.fitted is True
        assert loaded.base_calibrator_type == "platt"
        # Loaded model should produce same predictions
        orig_result = cal.calibrate(np.array([0.9, 0.1]))
        loaded_result = loaded.calibrate(np.array([0.9, 0.1]))
        assert np.allclose(orig_result, loaded_result, atol=1e-6)
