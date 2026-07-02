import logging

from shared.model import XGBoostModel
from shared.pnl import DefaultPnLStrategy
from shared.signal import FixedThresholdStrategy
from shared.sizing import VolTargetSizing

_logger = logging.getLogger("eigencapital.registry")

_BASELINE_CLASSES = {
    "model": XGBoostModel,
    "signal": FixedThresholdStrategy,
    "sizing": VolTargetSizing,
    "pnl": DefaultPnLStrategy,
}


class StrategyRegistry:
    _instance = None

    def __init__(self):
        self._models = {}
        self._signal = {}
        self._sizing = {}
        self._pnl = {}
        self._features = {}

    @classmethod
    def get_instance(cls) -> "StrategyRegistry":
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance

    @classmethod
    def reset_instance(cls) -> None:
        cls._instance = None

    def register_defaults(self, assets: list) -> None:
        for asset in assets:
            self._models.setdefault(asset, XGBoostModel())
            self._signal.setdefault(asset, FixedThresholdStrategy())
            self._sizing.setdefault(asset, VolTargetSizing())
            self._pnl.setdefault(asset, DefaultPnLStrategy())
            self._features.setdefault(asset, None)

    def get_model(self, asset: str):
        if asset not in self._models:
            self._models[asset] = XGBoostModel()
        return self._models[asset]

    def get_signal(self, asset: str):
        if asset not in self._signal:
            self._signal[asset] = FixedThresholdStrategy()
        return self._signal[asset]

    def get_sizing(self, asset: str):
        if asset not in self._sizing:
            self._sizing[asset] = VolTargetSizing()
        return self._sizing[asset]

    def get_pnl(self, asset: str):
        if asset not in self._pnl:
            self._pnl[asset] = DefaultPnLStrategy()
        return self._pnl[asset]

    def get_features(self, asset: str):
        return self._features.get(asset)

    def register_model(self, asset: str, impl) -> None:
        self._assert_baseline("model", impl)
        self._models[asset] = impl

    def register_signal(self, asset: str, impl) -> None:
        self._assert_baseline("signal", impl)
        self._signal[asset] = impl

    def register_sizing(self, asset: str, impl) -> None:
        self._assert_baseline("sizing", impl)
        self._sizing[asset] = impl

    def register_pnl(self, asset: str, impl) -> None:
        self._assert_baseline("pnl", impl)
        self._pnl[asset] = impl

    def register_features(self, asset: str, impl) -> None:
        self._assert_baseline("features", impl)
        self._features[asset] = impl

    def _assert_baseline(self, category: str, impl) -> None:
        expected = _BASELINE_CLASSES[category]
        if not isinstance(impl, expected):
            _logger.warning(
                "Registry: %s impl %s is not baseline %s (allowed for future use, no behavior change in live)",
                category,
                type(impl).__name__,
                expected.__name__,
            )

    def validate_strategies(self, asset: str, strategies: dict) -> None:
        for category, expected_cls in _BASELINE_CLASSES.items():
            key = f"_{category}" if category != "features" else "_feature_pipeline"
            actual = strategies.get(key)
            if actual is not None and not isinstance(actual, expected_cls):
                _logger.warning(
                    "Validation [%s]: %s is %s, expected %s",
                    asset,
                    category,
                    type(actual).__name__,
                    expected_cls.__name__,
                )


def get_factory(asset: str) -> dict:
    registry = StrategyRegistry.get_instance()
    return {
        "model": registry.get_model(asset),
        "signal": registry.get_signal(asset),
        "sizing": registry.get_sizing(asset),
        "pnl": registry.get_pnl(asset),
        "features": registry.get_features(asset),
    }
