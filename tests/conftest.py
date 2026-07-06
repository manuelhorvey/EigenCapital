import numpy as np
import pandas as pd
import pytest

from shared.registry import StrategyRegistry


@pytest.fixture(autouse=True)
def _reset_global_singletons():
    """Reset global singletons before each test to prevent test pollution.

    Singletons tracked:
        - StrategyRegistry: registered assets persist across tests
        - CalibrationRegistry: handled by get_or_load key isolation
        - ExperimentContext: handled by test isolation
    """
    StrategyRegistry.reset_instance()


@pytest.fixture
def sample_price_data():
    np.random.seed(42)
    prices = 100 + np.cumsum(np.random.randn(100) * 0.5)
    return pd.DataFrame({"close": prices, "high": prices * 1.01, "low": prices * 0.99, "volume": 1000000})


@pytest.fixture
def sample_macro_data():
    return pd.DataFrame({
        "fed_funds": np.full(100, 2.5),
        "ecb_rate": np.full(100, 1.0),
        "us_2y": np.full(100, 3.0),
        "dxy": np.full(100, 96.0),
    })
