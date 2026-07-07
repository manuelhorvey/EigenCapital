"""Tests for shared/constrained_weights.py."""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest


class TestFactorConstrainedWeights:
    def test_empty_returns_empty(self):
        from shared.constrained_weights import factor_constrained_weights

        returns = pd.DataFrame()
        result = factor_constrained_weights(returns)
        assert result == {}

    def test_single_asset_returns_full_weight(self):
        from shared.constrained_weights import factor_constrained_weights

        returns = pd.DataFrame({"A": [0.01, -0.02, 0.03]})
        result = factor_constrained_weights(returns)
        assert result == {"A": 1.0}

    def test_two_assets_returns_dict(self):
        from shared.constrained_weights import factor_constrained_weights

        np.random.seed(42)
        returns = pd.DataFrame({"A": np.random.randn(50), "B": np.random.randn(50)})
        result = factor_constrained_weights(returns)
        assert isinstance(result, dict)
        assert set(result.keys()) == {"A", "B"}
        for w in result.values():
            assert 0 <= w <= 1


class TestFactorConstrainedWeightsV2:
    def test_empty_returns_empty(self):
        from shared.constrained_weights import factor_constrained_weights_v2

        returns = pd.DataFrame()
        result = factor_constrained_weights_v2(returns)
        assert result == {}

    def test_single_asset_returns_full_weight(self):
        from shared.constrained_weights import factor_constrained_weights_v2

        returns = pd.DataFrame({"A": [0.01, -0.02, 0.03]})
        result = factor_constrained_weights_v2(returns)
        assert result == {"A": 1.0}

    def test_two_assets_returns_weights_summing_to_one(self):
        from shared.constrained_weights import factor_constrained_weights_v2

        np.random.seed(42)
        returns = pd.DataFrame({"A": np.random.randn(50), "B": np.random.randn(50)})
        result = factor_constrained_weights_v2(returns)
        assert isinstance(result, dict)
        assert set(result.keys()) == {"A", "B"}
        total = sum(result.values())
        assert abs(total - 1.0) < 0.01
