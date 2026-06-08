from unittest.mock import MagicMock, patch

import numpy as np
import pandas as pd
import pytest


class TestWalkForwardValidator:
    def test_init(self):
        from backtests.walk_forward import WalkForwardValidator

        ensemble = MagicMock()
        validator = WalkForwardValidator(ensemble, window_years=3, step_years=1)
        assert validator.window_years == 3
        assert validator.step_years == 1
        assert validator.ensemble == ensemble

    @pytest.fixture
    def mock_ensemble(self):
        mock = MagicMock()
        return mock

    @pytest.fixture
    def sample_data(self):
        np.random.seed(42)
        dates = pd.date_range("2018-01-01", "2022-12-31", freq="D")
        n = len(dates)
        X = pd.DataFrame({"f1": np.random.randn(n), "f2": np.random.randn(n)}, index=dates)
        y = pd.Series(np.random.choice([0, 1, 2], size=n), index=dates)
        regimes = pd.Series(np.random.choice(["trend", "range", "volatile"], size=n), index=dates)
        returns = pd.Series(np.random.randn(n) * 0.01, index=dates)
        regime_features = pd.DataFrame({"regime_feature": np.random.randn(n)}, index=dates)
        return X, y, regimes, returns, regime_features

    @patch("backtests.walk_forward.RegimeAwareSignalGenerator")
    def test_run_validation(self, MockSignalGen, mock_ensemble, sample_data):
        from backtests.walk_forward import WalkForwardValidator

        X, y, regimes, returns, regime_features = sample_data

        # Mock signal generator
        mock_gen = MagicMock()
        MockSignalGen.return_value = mock_gen

        # Mock signals output
        sig_dates = X.index[-100:]
        signals = pd.DataFrame(
            {
                "signal": np.random.choice([0, 1, 2], size=100),
                "risk_multiplier": np.ones(100),
            },
            index=sig_dates,
        )
        mock_gen.generate_signals.return_value = signals

        validator = WalkForwardValidator(mock_ensemble, window_years=3, step_years=1)
        result = validator.run_validation(X, y, regimes, returns, regime_features)

        assert isinstance(result, pd.DataFrame)
        assert len(result) > 0
        assert "window" in result.columns
        assert "expectancy" in result.columns
        assert "n_trades" in result.columns


class TestRollingRetrainValidator:
    def test_init(self):
        from backtests.rolling_retrain import RollingRetrainValidator

        ensemble = MagicMock()
        validator = RollingRetrainValidator(ensemble)
        assert validator.config["train_months"] == 18
        assert validator.config["test_months"] == 6

    def test_init_with_custom_config(self):
        from backtests.rolling_retrain import RollingRetrainValidator

        ensemble = MagicMock()
        config = {"train_months": 12, "val_months": 2, "test_months": 4, "step_months": 4}
        validator = RollingRetrainValidator(ensemble, config)
        assert validator.config == config
