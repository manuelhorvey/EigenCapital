"""Centralized Configuration Loader.

Loads configuration from TOML files in the configs/ directory.
Supports environment-specific overrides:
  configs/
    base.toml           # Shared defaults
    production/         # Production overrides
    development/        # Development overrides
    paper/              # Paper trading overrides
    research/           # Research overrides

Usage:
    from eigencapital.config import load_config, get_config

    config = load_config("production")
    broker = config.broker
    capital = config.capital
"""

from __future__ import annotations

import os
import tomllib
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional


# ── Config paths ──────────────────────────────────────────────────

CONFIGS_DIR = Path(__file__).parent.parent.parent / "configs"


@dataclass(frozen=True)
class BrokerConfig:
    """Broker connection and validation configuration."""

    account_id: str = "436921728"
    account_name: str = "EigenCapital-R4-Trial"
    environment: str = "demo"  # "live" or "demo"
    broker_name: str = "exness"
    platform: str = "mt5"
    server: str = "Exness-MT5Trial9"
    max_spread: float = 0.0015
    max_slippage: float = 0.0008
    min_volume: float = 0.01
    max_volume: float = 1.0
    allowed_symbols: Dict[str, str] = field(default_factory=lambda: {
        "EURUSDm": "forex",
        "GBPUSDm": "forex",
        "USDJPYm": "forex",
        "AUDUSDm": "forex",
        "USDCADm": "forex",
        "USDCHFm": "forex",
        "NZDUSDm": "forex",
        "XAUUSDm": "metals",
        "XAGUSDm": "metals",
        "US500m": "indices",
        "US30m": "indices",
        "USTECm": "indices",
        "BTCUSDm": "crypto",
        "ETHUSDm": "crypto",
        "USOILm": "energy",
    })

    @classmethod
    def from_dict(cls, d: Dict[str, Any]) -> BrokerConfig:
        fields = {f.name for f in cls.__dataclass_fields__.values()}
        return cls(**{k: v for k, v in d.items() if k in fields})


@dataclass(frozen=True)
class CapitalConfig:
    """Capital boundary and campaign configuration."""

    max_equity: float = 5000.0
    max_drawdown_pct: float = 20.0
    max_daily_loss: float = 250.0
    max_total_drawdown: float = 1000.0
    max_position_size: float = 500.0
    max_order_notional: float = 250.0
    max_concurrent_positions: int = 8
    campaign_duration_days: int = 30
    max_spread: float = 0.0015
    max_slippage: float = 0.0008
    max_execution_divergence: float = 0.004

    @classmethod
    def from_dict(cls, d: Dict[str, Any]) -> CapitalConfig:
        fields = {f.name for f in cls.__dataclass_fields__.values()}
        return cls(**{k: v for k, v in d.items() if k in fields})


@dataclass(frozen=True)
class RiskConfig:
    """Risk policy configuration."""

    max_drawdown_pct: float = 10.0
    daily_loss_limit: float = 5000.0
    weekly_loss_limit: float = 15000.0
    max_gross_leverage: float = 2.0
    max_net_leverage: float = 1.5
    max_position_count: int = 10
    min_equity: float = 50000.0
    max_position_notional: float = 500000.0
    max_position_risk_pct: float = 20.0
    max_strategy_exposure_pct: float = 30.0
    max_asset_class_exposure_pct: float = 40.0
    max_concentration_pct: float = 25.0
    kill_switch: bool = False

    @classmethod
    def from_dict(cls, d: Dict[str, Any]) -> RiskConfig:
        fields = {f.name for f in cls.__dataclass_fields__.values()}
        return cls(**{k: v for k, v in d.items() if k in fields})


@dataclass(frozen=True)
class StrategyConfig:
    """R4 strategy configuration."""

    name: str = "risk_conditioned_continuation"
    version: str = "R4.0"
    manifest_fingerprint: str = "aaab6c00dc05a09a380af7fbd705cc8c241ea69023b6a8ddc8d5e7f0b82b2beb"
    data_terminal_id: str = "436921728"
    vol_target_annual: float = 0.10
    vol_lookback: int = 20
    signal_lookback_short: int = 63
    signal_lookback_long: int = 252
    rebalance_frequency: str = "weekly"
    transaction_cost_bps: float = 10.0
    slippage_bps: float = 5.0

    @classmethod
    def from_dict(cls, d: Dict[str, Any]) -> StrategyConfig:
        fields = {f.name for f in cls.__dataclass_fields__.values()}
        return cls(**{k: v for k, v in d.items() if k in fields})


@dataclass(frozen=True)
class HealthConfig:
    """Health monitoring configuration."""

    max_snapshot_age_seconds: float = 300.0
    max_recovery_attempts: int = 3
    stale_threshold_seconds: float = 60.0

    @classmethod
    def from_dict(cls, d: Dict[str, Any]) -> HealthConfig:
        fields = {f.name for f in cls.__dataclass_fields__.values()}
        return cls(**{k: v for k, v in d.items() if k in fields})


@dataclass(frozen=True)
class ExecutionConfig:
    """Execution and partial-fill configuration."""

    max_chase_attempts: int = 2
    max_age_seconds: float = 60.0
    max_cumulative_slippage_bps: float = 15.0
    max_order_frequency: int = 10  # per hour

    @classmethod
    def from_dict(cls, d: Dict[str, Any]) -> ExecutionConfig:
        fields = {f.name for f in cls.__dataclass_fields__.values()}
        return cls(**{k: v for k, v in d.items() if k in fields})


@dataclass(frozen=True)
class AlertConfig:
    """Alert delivery configuration."""

    enabled: bool = True
    webhook_url: str = ""
    slack_channel: str = ""
    email_recipients: List[str] = field(default_factory=list)

    @classmethod
    def from_dict(cls, d: Dict[str, Any]) -> AlertConfig:
        fields = {f.name for f in cls.__dataclass_fields__.values()}
        return cls(**{k: v for k, v in d.items() if k in fields})


@dataclass(frozen=True)
class EigenCapitalConfig:
    """Top-level configuration for EigenCapital."""

    environment: str = "production"
    broker: BrokerConfig = field(default_factory=BrokerConfig)
    capital: CapitalConfig = field(default_factory=CapitalConfig)
    risk: RiskConfig = field(default_factory=RiskConfig)
    strategy: StrategyConfig = field(default_factory=StrategyConfig)
    health: HealthConfig = field(default_factory=HealthConfig)
    execution: ExecutionConfig = field(default_factory=ExecutionConfig)
    alerts: AlertConfig = field(default_factory=AlertConfig)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "environment": self.environment,
            "broker": self.broker.__dict__,
            "capital": self.capital.__dict__,
            "risk": self.risk.__dict__,
            "strategy": self.strategy.__dict__,
            "health": self.health.__dict__,
            "execution": self.execution.__dict__,
            "alerts": self.alerts.__dict__,
        }


# ── Config Loading ────────────────────────────────────────────────

def _deep_merge(base: Dict[str, Any], override: Dict[str, Any]) -> Dict[str, Any]:
    """Deep merge two dicts, with override taking precedence."""
    result = base.copy()
    for key, value in override.items():
        if key in result and isinstance(result[key], dict) and isinstance(value, dict):
            result[key] = _deep_merge(result[key], value)
        else:
            result[key] = value
    return result


def _load_toml(path: Path) -> Dict[str, Any]:
    """Load a TOML file, returning empty dict if not found."""
    if not path.exists():
        return {}
    with open(path, "rb") as f:
        return tomllib.load(f)


def load_config(environment: str = "production") -> EigenCapitalConfig:
    """Load configuration for the specified environment.

    Merge order:
    1. Base defaults (hardcoded in dataclasses)
    2. configs/base.json (if exists)
    3. configs/{environment}/config.json (if exists)
    4. Environment variables (EIGENCAPITAL_* prefix)
    """
    # Load base config
    base_path = CONFIGS_DIR / "base.toml"
    base_data = _load_toml(base_path)

    # Load environment config
    env_path = CONFIGS_DIR / environment / "config.toml"
    env_data = _load_toml(env_path)

    # Merge
    merged = _deep_merge(base_data, env_data)

    # Build config objects
    broker = BrokerConfig.from_dict(merged.get("broker", {}))
    capital = CapitalConfig.from_dict(merged.get("capital", {}))
    risk = RiskConfig.from_dict(merged.get("risk", {}))
    strategy = StrategyConfig.from_dict(merged.get("strategy", {}))
    health = HealthConfig.from_dict(merged.get("health", {}))
    execution = ExecutionConfig.from_dict(merged.get("execution", {}))
    alerts = AlertConfig.from_dict(merged.get("alerts", {}))

    return EigenCapitalConfig(
        environment=environment,
        broker=broker,
        capital=capital,
        risk=risk,
        strategy=strategy,
        health=health,
        execution=execution,
        alerts=alerts,
    )


# ── Singleton ─────────────────────────────────────────────────────

_config: Optional[EigenCapitalConfig] = None


def get_config() -> EigenCapitalConfig:
    """Get the loaded configuration, loading if necessary."""
    global _config
    if _config is None:
        env = os.environ.get("EIGENCAPITAL_ENV", "production")
        _config = load_config(env)
    return _config


def reset_config() -> None:
    """Reset the singleton (for testing)."""
    global _config
    _config = None
