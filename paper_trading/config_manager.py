import logging
import os
from dataclasses import dataclass, field

import yaml

logger = logging.getLogger("quantforge.config_manager")

DEFAULT_CONFIG_PATH = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "configs",
    "paper_trading.yaml",
)


def _default_halt() -> dict:
    return {
        "drawdown": -0.08,
        "monthly_pf": 0.70,
        "signal_drought": 30,
        "prob_drift": 0.25,
    }


@dataclass
class EngineConfig:
    capital: float = 100_000
    position_size: float = 0.95
    rebalance: str = "daily"
    retrain_freq: str = "annual"
    retrain_window: int = 5
    research_mode: bool = False
    halt: dict = field(default_factory=_default_halt)
    satellite: dict = field(default_factory=dict)
    assets: dict = field(default_factory=dict)
    vol_baselines: dict = field(default_factory=dict)
    regime_geometry: dict = field(default_factory=dict)
    execution_defaults: dict = field(default_factory=dict)
    portfolio_drawdown_limit: float = -0.15
    narrative_config: dict = field(default_factory=dict)
    liquidity_config: dict = field(default_factory=dict)
    defaults: dict = field(default_factory=dict)
    execution: dict = field(default_factory=dict)
    optimizations: dict = field(default_factory=lambda: {
        "truncate_inference": "auto",
        "batch_http": True,
        "sqlite_state": True,
        "vectorized_labels": True,
        "async_diagnostics": True,
    })

    @classmethod
    def from_dict(cls, data: dict) -> "EngineConfig":
        halt = dict(data.get("halt", _default_halt()))
        # Ensure halt has all expected keys
        defaults_halt = _default_halt()
        for k, v in defaults_halt.items():
            halt.setdefault(k, v)

        execution = data.get("execution", {})
        governance = execution.get("governance", {})

        return cls(
            capital=data.get("capital", 100_000),
            position_size=data.get("position_size", 0.95),
            rebalance=data.get("rebalance", "daily"),
            retrain_freq=data.get("retrain_freq", "annual"),
            retrain_window=data.get("retrain_window", 5),
            research_mode=data.get("research_mode", False),
            halt=halt,
            satellite=data.get("satellite", {}),
            assets=data.get("assets", {}),
            vol_baselines=data.get("vol_baselines", {}),
            # Prioritize namespaced governance, fallback to top-level
            regime_geometry=governance.get("regime_geometry", data.get("regime_geometry", {})),
            execution_defaults=data.get("execution_defaults", {}),
            portfolio_drawdown_limit=data.get("portfolio_drawdown_limit", -0.15),
            narrative_config=governance.get("narrative_config", data.get("narrative_config", {})),
            liquidity_config=governance.get("liquidity_config", data.get("liquidity_config", {})),
            defaults=data.get("defaults", {}),
            execution=execution,
            optimizations=data.get("optimizations", {}),
        )

    def to_dict(self) -> dict:
        return {
            "capital": self.capital,
            "position_size": self.position_size,
            "rebalance": self.rebalance,
            "retrain_freq": self.retrain_freq,
            "retrain_window": self.retrain_window,
            "research_mode": self.research_mode,
            "halt": self.halt,
            "satellite": self.satellite,
            "assets": self.assets,
            "vol_baselines": self.vol_baselines,
            "regime_geometry": self.regime_geometry,
            "execution_defaults": self.execution_defaults,
            "portfolio_drawdown_limit": self.portfolio_drawdown_limit,
            "narrative_config": self.narrative_config,
            "liquidity_config": self.liquidity_config,
            "defaults": self.defaults,
            "optimizations": self.optimizations,
        }


def load_config(path: str | None = None) -> EngineConfig:
    path = path or DEFAULT_CONFIG_PATH
    if os.path.exists(path):
        with open(path) as f:
            data = yaml.safe_load(f) or {}
        logger.info("Loaded config from %s", path)
        return EngineConfig.from_dict(data)
    logger.warning("Config file %s not found; using defaults", path)
    return EngineConfig()


_GLOBAL_CONFIG: EngineConfig | None = None


def get_config(path: str | None = None) -> EngineConfig:
    global _GLOBAL_CONFIG
    if _GLOBAL_CONFIG is None:
        _GLOBAL_CONFIG = load_config(path)
    return _GLOBAL_CONFIG


def reset_config() -> None:
    global _GLOBAL_CONFIG
    _GLOBAL_CONFIG = None
