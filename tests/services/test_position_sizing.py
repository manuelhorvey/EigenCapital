import pandas as pd
from archive.deprecated._position_sizing import calculate_position_size


class TestCalculatePositionSize:
    def test_returns_series(self):
        df = pd.DataFrame({"signal": [1, 0, -1], "risk_multiplier": [1.0, 0.5, 1.0]})
        result = calculate_position_size(df)
        assert isinstance(result, pd.Series)

    def test_signal_zero_when_multiplier_zero(self):
        df = pd.DataFrame({"signal": [1, 0, -1], "risk_multiplier": [0.0, 0.0, 0.0]})
        result = calculate_position_size(df)
        assert (result == 0).all()

    def test_default_parameters(self):
        df = pd.DataFrame({"signal": [1, 0, -1], "risk_multiplier": [1.0, 1.0, 1.0]})
        result = calculate_position_size(df)
        assert len(result) == 3

    def test_returns_signal_times_multiplier(self):
        df = pd.DataFrame({"signal": [1, 2, -1], "risk_multiplier": [0.5, 1.0, 0.25]})
        result = calculate_position_size(df)
        expected = pd.Series([0.5, 2.0, -0.25])
        assert (result == expected).all()

    def test_negative_signal_returns_negative_size(self):
        df = pd.DataFrame({"signal": [-1], "risk_multiplier": [1.0]})
        result = calculate_position_size(df)
        assert result.iloc[0] < 0

    def test_account_value_parameter_accepted(self):
        df = pd.DataFrame({"signal": [1], "risk_multiplier": [1.0]})
        result = calculate_position_size(df, account_value=100000)
        assert isinstance(result, pd.Series)
