import logging
import os
import stat
from dataclasses import dataclass, field
from pathlib import Path

import yaml
from dotenv import load_dotenv

load_dotenv()

logger = logging.getLogger("eigencapital.config_manager")

_SENSITIVE_ENV_VARS = frozenset(
    {
        "MT5_PASSWORD",
        "MT5_ACCOUNT",
        "OPENCODE_ZEN_API_KEY",
        "QUANTFORGE_API_TOKEN",
        "PAGERDUTY_ROUTING_KEY",
        "SLACK_WEBHOOK_URL",
    }
)

_DOTENV_PATH = Path(".env").absolute()


def _warn_on_insecure_dotenv() -> None:
    """Log a warning if .env exists with world-readable permissions."""
    if not _DOTENV_PATH.exists():
        return
    try:
        mode = _DOTENV_PATH.stat().st_mode
        if mode & stat.S_IROTH:
            exposed = [k for k in _SENSITIVE_ENV_VARS if os.environ.get(k)]
            logger.warning(
                ".env is world-readable (permissions=0%o). Run: chmod 600 .env. Exposed vars: %s",
                mode & 0o777,
                ", ".join(exposed) if exposed else "(none detected)",
            )
    except OSError:
        pass


_warn_on_insecure_dotenv()

# Shared MT5 bridge port — single source of truth
DEFAULT_MT5_BRIDGE_PORT = 9879

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
        "expected_prob_conf": 0.65,
        "prob_drift_min_samples": 10,
    }


@dataclass
class MT5Config:
    enabled: bool = False
    account: int = 0
    password: str = ""
    server: str = ""
    bridge_host: str = "127.0.0.1"
    bridge_port: int = DEFAULT_MT5_BRIDGE_PORT
    symbol_map_path: str = ""

    @classmethod
    def from_dict(cls, data: dict) -> "MT5Config":
        # YAML values are defaults; env vars take precedence (security)
        account = int(os.environ.get("MT5_ACCOUNT") or data.get("account", 0))
        password = os.environ.get("MT5_PASSWORD", data.get("password", ""))
        server = os.environ.get("MT5_SERVER", data.get("server", ""))

        return cls(
            enabled=data.get("enabled", False),
            account=account,
            password=password,
            server=server,
            bridge_host=data.get("bridge_host", "127.0.0.1"),
            bridge_port=int(data.get("bridge_port", DEFAULT_MT5_BRIDGE_PORT)),
            symbol_map_path=data.get("symbol_map_path", ""),
        )


@dataclass
class EngineConfig:
    capital: float = 100_000
    position_size: float = 0.95
    rebalance: str = "daily"
    retrain_freq: str = "annual"
    retrain_window: int = 5
    research_mode: bool = False
    api_token: str = ""
    mode: str = "production"
    modes: dict = field(default_factory=dict)
    halt: dict = field(default_factory=_default_halt)
    assets: dict = field(default_factory=dict)
    vol_baselines: dict = field(default_factory=dict)
    regime_geometry: dict = field(default_factory=dict)
    execution_defaults: dict = field(default_factory=dict)
    portfolio_drawdown_limit: float = -0.15
    narrative_config: dict = field(default_factory=dict)
    liquidity_config: dict = field(default_factory=dict)
    defaults: dict = field(default_factory=dict)
    sell_only_assets: frozenset = field(
        default_factory=lambda: frozenset(
            {
                "CADCHF",
                "NZDCHF",
                "EURAUD",
            }
        )
    )
    portfolio: dict = field(default_factory=dict)
    execution: dict = field(default_factory=dict)
    optimizations: dict = field(
        default_factory=lambda: {
            "truncate_inference": "auto",
            "batch_http": True,
            "sqlite_state": True,
            "vectorized_labels": True,
            "async_diagnostics": True,
            "regime_conviction_flip_gate": {
                "enabled": False,
                "regime_margin_threshold": 0.35,
                "confidence_threshold": 0.50,
                "min_bars_in_regime": 3,
            },
        }
    )
    mt5: MT5Config = field(default_factory=MT5Config)
    data_source: str = "yfinance"  # "yfinance" or "mt5"

    def __post_init__(self) -> None:
        errors: list[str] = []
        if self.capital <= 0:
            errors.append(f"capital must be positive, got {self.capital}")
        if not 0 < self.position_size <= 1.0:
            errors.append(f"position_size must be in (0, 1], got {self.position_size}")
        if self.rebalance not in ("daily", "weekly", "monthly", "none"):
            errors.append(f"rebalance must be 'daily', 'weekly', 'monthly', or 'none', got '{self.rebalance}'")
        if self.retrain_window < 1:
            errors.append(f"retrain_window must be >= 1, got {self.retrain_window}")
        if self.data_source not in ("yfinance", "mt5"):
            errors.append(f"data_source must be 'yfinance' or 'mt5', got '{self.data_source}'")
        if not -1.0 <= self.portfolio_drawdown_limit <= 0.0:
            errors.append(f"portfolio_drawdown_limit must be in [-1.0, 0.0], got {self.portfolio_drawdown_limit}")
        if self.mt5.bridge_port <= 0 or self.mt5.bridge_port > 65535:
            errors.append(f"mt5.bridge_port must be in [1, 65535], got {self.mt5.bridge_port}")
        if errors:
            raise ValueError("EngineConfig validation failed:\n  " + "\n  ".join(errors))

    @classmethod
    def _merge_mode_overrides(cls, base: dict, mode_overrides: dict) -> dict:
        """Deep-merge mode overrides into base config dict.

        Top-level scalars from mode_overrides replace base values.
        Nested dicts (e.g. defaults) are merged key-by-key.
        Lists are replaced (not merged).
        """
        merged = dict(base)
        for key, value in mode_overrides.items():
            if key in ("description",):
                continue
            if isinstance(value, dict) and isinstance(merged.get(key), dict):
                merged[key] = {**merged[key], **value}
            else:
                merged[key] = value
        return merged

    @classmethod
    def from_dict(cls, data: dict) -> "EngineConfig":
        halt = dict(data.get("halt", _default_halt()))
        defaults_halt = _default_halt()
        for k, v in defaults_halt.items():
            halt.setdefault(k, v)

        execution = data.get("execution", {}) or {}
        governance = execution.get("governance", {}) or {}

        # Resolve mode overrides after base load
        mode_name = data.get("mode", "production")
        modes = data.get("modes", {})
        mode_overrides = modes.get(mode_name, {})
        if mode_overrides:
            data = cls._merge_mode_overrides(data, mode_overrides)

        api_token = os.environ.get("EIGENCAPITAL_API_TOKEN", data.get("api_token", ""))

        return cls(
            mode=mode_name,
            modes=modes,
            capital=data.get("capital", 100_000),
            position_size=data.get("position_size", 0.95),
            rebalance=data.get("rebalance", "daily"),
            retrain_freq=data.get("retrain_freq", "annual"),
            retrain_window=data.get("retrain_window", 5),
            research_mode=data.get("research_mode", False),
            api_token=api_token,
            halt=halt,
            assets=data.get("assets", {}),
            vol_baselines=data.get("vol_baselines", {}),
            regime_geometry=governance.get("regime_geometry") or data.get("regime_geometry", {}),
            execution_defaults=data.get("execution_defaults", {}),
            portfolio_drawdown_limit=data.get("portfolio_drawdown_limit", -0.15),
            narrative_config=governance.get("narrative_config") or data.get("narrative_config", {}),
            liquidity_config=governance.get("liquidity_config") or data.get("liquidity_config", {}),
            defaults=data.get("defaults", {}),
            sell_only_assets=frozenset(
                data.get("defaults", {}).get("sell_only_assets", []) or ["CADCHF", "NZDCHF", "EURAUD"]
            ),
            portfolio=data.get("portfolio", {}),
            execution=execution,
            optimizations=data.get("optimizations", {}),
            mt5=MT5Config.from_dict(data.get("mt5", {})),
            data_source=data.get("data_source", "yfinance"),
        )

    def to_dict(self) -> dict:
        return {
            "mode": self.mode,
            "modes": self.modes,
            "capital": self.capital,
            "position_size": self.position_size,
            "rebalance": self.rebalance,
            "retrain_freq": self.retrain_freq,
            "retrain_window": self.retrain_window,
            "research_mode": self.research_mode,
            "halt": self.halt,
            "assets": self.assets,
            "vol_baselines": self.vol_baselines,
            "regime_geometry": self.regime_geometry,
            "execution_defaults": self.execution_defaults,
            "portfolio_drawdown_limit": self.portfolio_drawdown_limit,
            "narrative_config": self.narrative_config,
            "liquidity_config": self.liquidity_config,
            "defaults": self.defaults,
            "portfolio": self.portfolio,
            "optimizations": self.optimizations,
        }


def load_config(path: str | None = None) -> EngineConfig:
    """Load and return EngineConfig via the typed paper registry.

    Phase 11.2 routes through ``configs.paper_config_registry.PaperConfigRegistry``
    which reads domain YAMLs first and falls back to the legacy file.

    Call-site contract:
      - Default path (configs/paper_trading.yaml): PaperConfigRegistry's
        domain-first precedence applies. Domain tree wins; legacy is
        fallback for unpromoted keys.
      - Explicit path (test fixtures, mode overlays, CI): the supplied
        YAML is treated as authoritative for any key it carries. Domain
        files fill in the rest. This preserves the pre-Phase 11 contract
        where custom legacy YAMLs could override.
    """
    if path is None:
        path = DEFAULT_CONFIG_PATH
    if os.path.exists(path):
        try:
            from configs.paper_config_registry import DOMAINS_DIR, PaperConfigRegistry

            requested_path = Path(path).resolve()
            default_path = Path(DEFAULT_CONFIG_PATH).resolve()

            reg = PaperConfigRegistry.load(legacy_path=requested_path, domains_dir=DOMAINS_DIR)
            typed = reg.as_legacy_dict()

            # Explicit-path overrides take precedence over the domain tree
            # only when the caller passed something other than the default
            # paper_trading.yaml (test fixtures, ad-hoc overlays).
            if requested_path != default_path:
                raw = yaml.safe_load(requested_path.read_text()) or {}
                _deep_overlay(typed, raw)

            logger.info(
                "Loaded config from %s (registry: %d assets, %d legacy extras)",
                path,
                len(reg.assets),
                len(reg.legacy_extras),
            )
            return EngineConfig.from_dict(typed)
        except Exception as e:  # noqa: BLE001 - fall back to legacy path
            logger.warning(
                "PaperConfigRegistry failed (%s); falling back to legacy YAML parser",
                e,
            )
    else:
        logger.warning("Config file %s not found; using defaults", path)
    if os.path.exists(path):
        with open(path) as f:
            data = yaml.safe_load(f) or {}
        return EngineConfig.from_dict(data)
    return EngineConfig()


def _deep_overlay(target: dict, source: dict) -> None:
    """In-place merge: ``source`` overrides ``target`` at every level."""
    for k, v in source.items():
        if isinstance(v, dict) and isinstance(target.get(k), dict):
            _deep_overlay(target[k], v)
        else:
            target[k] = v


_GLOBAL_CONFIG: EngineConfig | None = None


def get_config(path: str | None = None, override: EngineConfig | None = None) -> EngineConfig:
    """Load and return the global config.

    Args:
        path: Optional config file path. Defaults to ``configs/paper_trading.yaml``.
        override: Optional pre-built config to return. Skips loading entirely.
            Useful for testing and multi-instance scenarios.

    Returns:
        The active ``EngineConfig`` instance (either the override,
        the cached global, or a freshly-loaded one).
    """
    if override is not None:
        return override
    global _GLOBAL_CONFIG
    if _GLOBAL_CONFIG is None:
        _GLOBAL_CONFIG = load_config(path)
    return _GLOBAL_CONFIG


def reset_config() -> None:
    global _GLOBAL_CONFIG
    _GLOBAL_CONFIG = None
