"""Tests for paper_trading/shadow/model.py — ShadowModelRunner."""

import struct
import tempfile
from pathlib import Path

import numpy as np
import xgboost as xgb
import pytest

from paper_trading.shadow.model import ShadowModelRunner, ShadowModelSpec


@pytest.fixture
def dummy_model_path():
    """Train a tiny XGB model on synthetic data and save to temp file."""
    rng = np.random.default_rng(42)
    X = rng.normal(0, 1, (200, 4))
    y = (X[:, 0] + X[:, 1] > 0).astype(int)
    model = xgb.XGBClassifier(n_estimators=10, max_depth=2, random_state=42)
    model.fit(X, y)
    with tempfile.NamedTemporaryFile(suffix=".json", delete=False) as f:
        model.save_model(f.name)
        yield Path(f.name)
    try:
        Path(f.name).unlink()
    except OSError:
        pass


class TestShadowModelRunner:
    def test_load_and_run(self, dummy_model_path):
        runner = ShadowModelRunner("test_model", str(dummy_model_path))
        feat = {"a": 0.5, "b": -0.3, "c": 1.2, "d": 0.0}
        result = runner.run(feat, feature_hash="abc123")
        assert result is not None
        assert result.shadow_id == "test_model"
        assert result.feature_hash == "abc123"
        assert result.signal in ("BUY", "SELL", "HOLD")
        assert 0 <= result.proba_long <= 1
        assert 0 <= result.proba_short <= 1

    def test_returns_none_for_nonexistent_model(self):
        runner = ShadowModelRunner("ghost", "/nonexistent/model.json")
        result = runner.run({"a": 1.0})
        assert result is None

    def test_produces_reasonable_signal(self, dummy_model_path):
        runner = ShadowModelRunner("test", str(dummy_model_path))
        feat = {f"f{i}": 0.0 for i in range(4)}
        result = runner.run(feat)
        assert result is not None
        assert isinstance(result.confidence, float)
        assert result.confidence >= 0


class TestShadowModelSpec:
    def test_spec_dataclass(self):
        spec = ShadowModelSpec(id="v2", model_path="/tmp/m.json", model_type="xgboost", status="offline")
        assert spec.id == "v2"
        assert spec.status == "offline"
