import pytest

from shared.registry import StrategyRegistry, get_factory
from shared.model import XGBoostModel
from shared.signal import FixedThresholdStrategy
from shared.sizing import VolTargetSizing
from shared.pnl import DefaultPnLStrategy


# ── StrategyRegistry ─────────────────────────────────────────────────────────


@pytest.fixture(autouse=True)
def reset_registry():
    StrategyRegistry.reset_instance()
    yield
    StrategyRegistry.reset_instance()


def test_singleton():
    r1 = StrategyRegistry.get_instance()
    r2 = StrategyRegistry.get_instance()
    assert r1 is r2


def test_register_defaults_creates_entries():
    registry = StrategyRegistry.get_instance()
    registry.register_defaults(["EURUSD", "BTC"])
    assert isinstance(registry.get_model("EURUSD"), XGBoostModel)
    assert isinstance(registry.get_signal("EURUSD"), FixedThresholdStrategy)
    assert isinstance(registry.get_sizing("EURUSD"), VolTargetSizing)
    assert isinstance(registry.get_pnl("EURUSD"), DefaultPnLStrategy)
    assert registry.get_features("EURUSD") is None


def test_get_model_creates_on_demand():
    registry = StrategyRegistry.get_instance()
    model = registry.get_model("UNKNOWN")
    assert isinstance(model, XGBoostModel)


def test_get_signal_creates_on_demand():
    registry = StrategyRegistry.get_instance()
    signal = registry.get_signal("UNKNOWN")
    assert isinstance(signal, FixedThresholdStrategy)


def test_get_sizing_creates_on_demand():
    registry = StrategyRegistry.get_instance()
    sizing = registry.get_sizing("UNKNOWN")
    assert isinstance(sizing, VolTargetSizing)


def test_get_pnl_creates_on_demand():
    registry = StrategyRegistry.get_instance()
    pnl = registry.get_pnl("UNKNOWN")
    assert isinstance(pnl, DefaultPnLStrategy)


def test_get_features_returns_none_by_default():
    registry = StrategyRegistry.get_instance()
    features = registry.get_features("UNKNOWN")
    assert features is None


def test_register_model():
    registry = StrategyRegistry.get_instance()
    model = XGBoostModel()
    registry.register_model("TEST", model)
    assert registry.get_model("TEST") is model


def test_register_signal():
    registry = StrategyRegistry.get_instance()
    signal = FixedThresholdStrategy()
    registry.register_signal("TEST", signal)
    assert registry.get_signal("TEST") is signal


def test_reset_instance():
    registry = StrategyRegistry.get_instance()
    registry.register_defaults(["EURUSD"])
    StrategyRegistry.reset_instance()
    new_registry = StrategyRegistry.get_instance()
    assert new_registry is not registry


def test_get_factory_returns_dict():
    registry = StrategyRegistry.get_instance()
    registry.register_defaults(["EURUSD"])
    factory = get_factory("EURUSD")
    assert "model" in factory
    assert "signal" in factory
    assert "sizing" in factory
    assert "pnl" in factory
    assert "features" in factory


def test_validate_strategies_does_not_crash():
    registry = StrategyRegistry.get_instance()
    strategies = {
        "_model": XGBoostModel(),
        "_signal": FixedThresholdStrategy(),
        "_sizing": VolTargetSizing(),
        "_pnl": DefaultPnLStrategy(),
        "_feature_pipeline": None,
    }
    registry.validate_strategies("EURUSD", strategies)


def test_register_model_with_warning(caplog):
    registry = StrategyRegistry.get_instance()
    model = FixedThresholdStrategy()
    registry.register_model("TEST", model)
    assert "not baseline" in caplog.text


def test_register_signal_with_warning(caplog):
    registry = StrategyRegistry.get_instance()
    signal = XGBoostModel()
    registry.register_signal("TEST", signal)
    assert "not baseline" in caplog.text
