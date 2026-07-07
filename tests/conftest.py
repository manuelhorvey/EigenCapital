import logging

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

    # Reset logging state — some imported modules (e.g. benchmarks/microbenchmark)
    # call logging.basicConfig() and setLevel(logging.ERROR) on the eigencapital
    # logger at import time.  This suppresses all WARNING messages from child
    # loggers like eigencapital.config_manager, breaking caplog-based tests.
    # Clean up so every test starts with a clean logging hierarchy.
    _reset_logging()


def _reset_logging() -> None:
    """Reset the eigencapital logger tree to defaults.

    Restores the logger to NOTSET level, clears any handlers added by
    module-level logging.basicConfig() calls, and ensures propagation
    to the root logger is enabled so that caplog can capture messages.
    """
    logger = logging.getLogger("eigencapital")
    logger.setLevel(logging.NOTSET)
    logger.handlers.clear()
    logger.propagate = True


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
