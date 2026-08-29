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

import json
import os
import tomllib
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List

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
    allowed_symbols: Dict[str, str] = field(
        default_factory=lambda: {
            "US30": "indices",
            "AUDJPY": "forex_excluded",
            "USOIL": "energy",
            "AUDUSD": "forex",
            "AUDCHF": "forex",
            "AUDCAD": "forex",
            "NZDJPY": "forex_excluded",
            "GBPJPY": "forex_excluded",
            "AUDNZD": "forex",
            "NZDUSD": "forex",
            "NZDCHF": "forex",
            "NZDCAD": "forex",
            "GBPUSD": "forex",
            "GBPCHF": "forex",
            "GBPCAD": "forex",
            "CHFJPY": "forex_excluded",
            "EURJPY": "forex_excluded",
            "USDJPY": "forex_excluded",
            "CADJPY": "forex_excluded",
            "XAUUSD": "metals",
            "EURUSD": "forex",
            "EURCHF": "forex",
            "USDCHF": "forex",
            "EURCAD": "forex",
            "USDCAD": "forex",
            "CADCHF": "forex",
            "GBPNZD": "forex",
            "EURGBP": "forex",
            "EURNZD": "forex",
            "GBPAUD": "forex",
            "EURAUD": "forex",
            "BTCUSD": "crypto",
        }
    )

    @classmethod
    def from_dict(cls, d: Dict[str, Any]) -> BrokerConfig:
        fields = {f.name for f in cls.__dataclass_fields__.values()}
        return cls(**{k: v for k, v in d.items() if k in fields})


@dataclass(frozen=True)
class CapitalConfig:
    """Capital boundary and campaign configuration."""

    max_equity: float = 5100.0  # $5K + 2% buffer for P&L drift
    max_drawdown_pct: float = 20.0
    max_daily_loss: float = 250.0
    max_total_drawdown: float = 1000.0
    max_position_size: float = 5000.0
    max_order_notional: float = 5000.0
    max_concurrent_positions: int = 19
    campaign_duration_days: int = 30
    max_spread: float = 0.0015
    max_slippage: float = 0.0008
    max_execution_divergence: float = 0.004

    @classmethod
    def from_dict(cls, d: Dict[str, Any]) -> CapitalConfig:
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
    # R4-specific parameters (used by rebalance loop)
    skip_months: int = 1  # months to skip from 12-month momentum
    vol_lookback_signal: int = 60  # days for vol scaling in signal
    risk_lookback: int = 20  # days for regime conditioning

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
    max_orders_per_cycle: int = 8  # max orders per rebalance cycle
    loop_interval_seconds: int = 3600  # default loop interval (1 hour)

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
class WatchdogConfig:
    """Watchdog thresholds for blind-window detection."""

    stale_after_seconds: float = 300.0
    blind_after_seconds: float = 900.0
    contain_after_seconds: float = 3600.0

    @classmethod
    def from_dict(cls, d: Dict[str, Any]) -> WatchdogConfig:
        fields = {f.name for f in cls.__dataclass_fields__.values()}
        return cls(**{k: v for k, v in d.items() if k in fields})


@dataclass(frozen=True)
class ReconciliationConfig:
    """Reconciliation thresholds."""

    stale_threshold_seconds: float = 86400.0

    @classmethod
    def from_dict(cls, d: Dict[str, Any]) -> ReconciliationConfig:
        fields = {f.name for f in cls.__dataclass_fields__.values()}
        return cls(**{k: v for k, v in d.items() if k in fields})


@dataclass(frozen=True)
class DataConfig:
    """Data fetching parameters."""

    fetch_bars: int = 300

    @classmethod
    def from_dict(cls, d: Dict[str, Any]) -> DataConfig:
        fields = {f.name for f in cls.__dataclass_fields__.values()}
        return cls(**{k: v for k, v in d.items() if k in fields})


@dataclass(frozen=True)
class LiveRiskConfig:
    """Live trading risk envelope — qualification-specific limits.

    These are STRICTER than the general RiskConfig and are the
    authoritative source for the live rebalance loop risk envelope.
    """

    max_concurrent_positions: int = 19
    max_position_notional: float = 2_500.0
    max_order_notional: float = 2_500.0
    max_per_position_loss_pct: float = 0.10
    max_account_drawdown_pct: float = 0.10
    max_daily_loss: float = 250.0
    min_equity: float = 4_000.0
    require_sl_on_positions: bool = False
    t0_equity: float = 5_010.94

    @classmethod
    def from_dict(cls, d: Dict[str, Any]) -> LiveRiskConfig:
        fields = {f.name for f in cls.__dataclass_fields__.values()}
        return cls(**{k: v for k, v in d.items() if k in fields})

    def to_dict(self) -> Dict[str, Any]:
        return {k: v for k, v in self.__dict__.items() if not k.startswith("_")}

    def compute_fingerprint(self) -> str:
        """Deterministic fingerprint of the live risk envelope."""
        import hashlib

        payload = json.dumps(self.to_dict(), sort_keys=True).encode("utf-8")
        return hashlib.sha256(payload).hexdigest()


@dataclass(frozen=True)
class EigenCapitalConfig:
    """Top-level configuration for EigenCapital."""

    environment: str = "production"
    broker: BrokerConfig = field(default_factory=BrokerConfig)
    capital: CapitalConfig = field(default_factory=CapitalConfig)
    live_risk: LiveRiskConfig = field(default_factory=LiveRiskConfig)
    strategy: StrategyConfig = field(default_factory=StrategyConfig)
    health: HealthConfig = field(default_factory=HealthConfig)
    execution: ExecutionConfig = field(default_factory=ExecutionConfig)
    alerts: AlertConfig = field(default_factory=AlertConfig)
    watchdog: WatchdogConfig = field(default_factory=WatchdogConfig)
    reconciliation: ReconciliationConfig = field(default_factory=ReconciliationConfig)
    data: DataConfig = field(default_factory=DataConfig)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "environment": self.environment,
            "broker": self.broker.__dict__,
            "capital": self.capital.__dict__,
            "live_risk": self.live_risk.__dict__,
            "strategy": self.strategy.__dict__,
            "health": self.health.__dict__,
            "execution": self.execution.__dict__,
            "alerts": self.alerts.__dict__,
            "watchdog": self.watchdog.__dict__,
            "reconciliation": self.reconciliation.__dict__,
            "data": self.data.__dict__,
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


def _load_toml(path: Path, required: bool = False) -> Dict[str, Any]:
    """Load a TOML file.

    Args:
        path: Path to TOML file.
        required: If True, raise FileNotFoundError when missing.
    """
    if not path.exists():
        if required:
            raise FileNotFoundError(f"Required config file missing: {path}")
        return {}
    with open(path, "rb") as f:
        return tomllib.load(f)


def load_config(environment: str = "production") -> EigenCapitalConfig:
    """Load configuration for the specified environment.

    Merge order:
    1. Base defaults (hardcoded in dataclasses)
    2. configs/base.toml (optional — shared overrides across environments)
    3. configs/{environment}/config.toml (environment-specific overrides)
    """
    # Load base config (optional — environment config provides all production values)
    base_path = CONFIGS_DIR / "base.toml"
    base_data = _load_toml(base_path, required=False)

    # Load environment config
    env_path = CONFIGS_DIR / environment / "config.toml"
    env_data = _load_toml(env_path)

    # Merge
    merged = _deep_merge(base_data, env_data)

    # Build config objects
    broker = BrokerConfig.from_dict(merged.get("broker", {}))
    capital = CapitalConfig.from_dict(merged.get("capital", {}))
    live_risk = LiveRiskConfig.from_dict(merged.get("live_risk", {}))
    strategy = StrategyConfig.from_dict(merged.get("strategy", {}))
    health = HealthConfig.from_dict(merged.get("health", {}))
    execution = ExecutionConfig.from_dict(merged.get("execution", {}))
    alerts = AlertConfig.from_dict(merged.get("alerts", {}))
    watchdog = WatchdogConfig.from_dict(merged.get("watchdog", {}))
    reconciliation = ReconciliationConfig.from_dict(merged.get("reconciliation", {}))
    data_config = DataConfig.from_dict(merged.get("data", {}))

    return EigenCapitalConfig(
        environment=environment,
        broker=broker,
        capital=capital,
        live_risk=live_risk,
        strategy=strategy,
        health=health,
        execution=execution,
        alerts=alerts,
        watchdog=watchdog,
        reconciliation=reconciliation,
        data=data_config,
    )


# ── Symbol Mapping Fingerprint (EC-AUD-009) ──────────────────────


def compute_symbol_mapping_fingerprint(config: EigenCapitalConfig) -> str:
    """EC-AUD-009: Deterministic fingerprint of the broker-symbol mapping.

    Detects drift between the frozen R4 manifest and live broker universe.
    Changes to allowed_symbols change this fingerprint → blocks trading.
    """
    import hashlib

    # Canonical representation: sorted symbol→classification mapping
    symbols = dict(sorted(config.broker.allowed_symbols.items()))
    payload = json.dumps(symbols, sort_keys=True).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


# ── Config Validation (EC-AUD-006) ────────────────────────────────


def validate_config_consistency(config: EigenCapitalConfig) -> list[str]:
    """EC-AUD-006: Validate safety-critical config consistency.

    Ensures live_risk is authoritative and catches dangerous inconsistencies
    between capital, risk, and live_risk sections.

    Returns a list of warning/error messages. Empty = all consistent.
    """
    warnings: list[str] = []
    lr = config.live_risk
    cap = config.capital

    # live_risk.min_equity must be >= capital floor
    if lr.min_equity > cap.max_equity:
        warnings.append(
            f"CRITICAL: live_risk.min_equity (${lr.min_equity:,.0f}) > "
            f"capital.max_equity (${cap.max_equity:,.0f}) — would block all trading"
        )

    # live_risk.max_daily_loss must be positive and reasonable
    if lr.max_daily_loss <= 0:
        warnings.append("CRITICAL: live_risk.max_daily_loss must be positive")
    elif lr.max_daily_loss > lr.min_equity * 0.5:
        warnings.append(
            f"WARNING: live_risk.max_daily_loss (${lr.max_daily_loss:,.0f}) > 50% of min_equity — unusually large"
        )

    # live_risk.max_concurrent_positions must be positive
    if lr.max_concurrent_positions <= 0:
        warnings.append("CRITICAL: live_risk.max_concurrent_positions must be positive")

    # capital.max_concurrent_positions is legacy; live_risk should be authoritative
    if cap.max_concurrent_positions != lr.max_concurrent_positions:
        warnings.append(
            f"INFO: capital.max_concurrent_positions ({cap.max_concurrent_positions}) != "
            f"live_risk.max_concurrent_positions ({lr.max_concurrent_positions}) — "
            f"live_risk is authoritative for risk gates"
        )

    # Drawdown pct sanity
    if lr.max_account_drawdown_pct <= 0 or lr.max_account_drawdown_pct > 1.0:
        warnings.append(
            f"CRITICAL: live_risk.max_account_drawdown_pct ({lr.max_account_drawdown_pct}) must be in (0, 1.0]"
        )

    return warnings


# ── Singleton ─────────────────────────────────────────────────────

_config: EigenCapitalConfig | None = None


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
