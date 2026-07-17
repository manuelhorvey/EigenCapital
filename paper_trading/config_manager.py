import contextlib
import logging
import os
import stat
from collections.abc import Iterator
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

# Strict write-mode guard for Phase 12.1
# When the legacy mirror exists on disk, the domain tree is still the
# authoritative source and drift on promoted keys triggers a warning.
# Set to "1" to silence the warning (legacy mirror remains derived-only;
# it cannot promote keys it does not own).
ENABLE_LEGACY_EDITS = "ENABLE_LEGACY_EDITS"

# Sentinel meaning "no explicit path was supplied".
# In Phase 12.7 the legacy configs/paper_trading.yaml file was deleted
# and PaperConfigRegistry reads exclusively from configs/domains/.
# Callers that pass an explicit path still get the legacy-mirror overlay
# (test fixtures, ad-hoc YAML overlays).
_LEGACY_FALLBACK_PATH = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "configs",
    "paper_trading.yaml",
)
# Default behaviour when no path is supplied: skip the legacy mirror
# entirely and load from PaperConfigRegistry only. Tests that need the
# legacy mirror pass an explicit ``path`` argument.
DEFAULT_CONFIG_PATH: str | None = None


def _validate_engine_config_hand_rolled(
    *,
    capital: float,
    position_size: float,
    rebalance: str,
    retrain_window: int,
    data_source: str,
    portfolio_drawdown_limit: float,
    mt5_bridge_port: int,
) -> None:
    """Hand-rolled config validation fallback (used when pydantic is unavailable).

    Mirrors the same checks that ``EngineConfigValidation`` enforces, so the
    two code paths are equivalent.  Raises ``ValueError`` on first failure.
    """
    errors: list[str] = []
    if capital <= 0:
        errors.append(f"capital must be positive, got {capital}")
    if not 0 < position_size <= 1.0:
        errors.append(f"position_size must be in (0, 1], got {position_size}")
    if rebalance not in ("daily", "weekly", "monthly", "none"):
        errors.append(f"rebalance must be 'daily', 'weekly', 'monthly', or 'none', got '{rebalance}'")
    if retrain_window < 1:
        errors.append(f"retrain_window must be >= 1, got {retrain_window}")
    if data_source not in ("yfinance", "mt5"):
        errors.append(f"data_source must be 'yfinance' or 'mt5', got '{data_source}'")
    if not -1.0 <= portfolio_drawdown_limit <= 0.0:
        errors.append(f"portfolio_drawdown_limit must be in [-1.0, 0.0], got {portfolio_drawdown_limit}")
    if mt5_bridge_port <= 0 or mt5_bridge_port > 65535:
        errors.append(f"mt5.bridge_port must be in [1, 65535], got {mt5_bridge_port}")
    if errors:
        raise ValueError("EngineConfig validation failed:\n  " + "\n  ".join(errors))



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
        # Resolution order: Vault KV v2 → env vars → YAML defaults
        from shared.vault_secrets import resolve_mt5_credentials

        resolved = resolve_mt5_credentials(config_data=data)
        account = int(resolved.get("account", data.get("account", 0)))
        password = resolved.get("password", data.get("password", ""))
        server = resolved.get("server", data.get("server", ""))

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
                "EURCHF",
                "GBPCHF",
                "GBPJPY",
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
    alerting: dict = field(default_factory=dict)

    def __post_init__(self) -> None:
        # Pydantic compositional guard layer — validates at construction time
        # with structured error messages, while keeping EngineConfig as a
        # plain dataclass for full backward compatibility (~80 call sites).
        #
        # NOTE: pydantic.ValidationError IS a subclass of ValueError in
        # Pydantic v2, so it propagates naturally to existing callers that
        # catch ValueError.  No broad ``except Exception`` wrapper needed.
        try:
            from configs.pydantic_models import EngineConfigValidation
        except ImportError:
            # Fall back to hand-rolled validation if pydantic is unavailable
            # (e.g. minimal dependency install, older lock file without it).
            # The hand-rolled logic is a dead-man's switch; the Pydantic path
            # is the primary validation engine.
            _validate_engine_config_hand_rolled(
                capital=self.capital,
                position_size=self.position_size,
                rebalance=self.rebalance,
                retrain_window=self.retrain_window,
                data_source=self.data_source,
                portfolio_drawdown_limit=self.portfolio_drawdown_limit,
                mt5_bridge_port=self.mt5.bridge_port,
            )
            return

        # Pydantic path — ValidationError (ValueError subclass) propagates
        # naturally to callers.  No wrapper needed.
        EngineConfigValidation(
            capital=self.capital,
            position_size=self.position_size,
            rebalance=self.rebalance,
            retrain_window=self.retrain_window,
            data_source=self.data_source,
            portfolio_drawdown_limit=self.portfolio_drawdown_limit,
            mt5_bridge_port=self.mt5.bridge_port,
        )

    @classmethod
    def _deep_merge(cls, base: dict, overrides: dict) -> dict:
        """Recursively merge *overrides* into *base*, mutating *base* in place.

        Scalars in *overrides* replace values in *base*.
        Nested dicts are merged key-by-key at every depth level.
        Lists are replaced entirely (not merged).
        """
        for key, value in overrides.items():
            if key in ("description",):
                continue
            if isinstance(value, dict) and isinstance(base.get(key), dict):
                cls._deep_merge(base[key], value)
            else:
                base[key] = value
        return base

    @classmethod
    def _merge_mode_overrides(cls, base: dict, mode_overrides: dict) -> dict:
        """Deep-merge mode overrides into a copy of *base*."""
        return cls._deep_merge(dict(base), mode_overrides)

    retention: dict = field(
        default_factory=lambda: {
            "trades_days": 365,
            "attribution_days": 365,
            "equity_history_days": 90,
            "trace_days": 30,
            "wal_days": 90,
            "log_days": 14,
            "shadow_feedback_days": 90,
            "shadow_memory_days": 60,
        }
    )

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
                data.get("defaults", {}).get("sell_only_assets", [])
                or [
                    "CADCHF",
                    "NZDCHF",
                    "EURAUD",
                    "EURCHF",
                    "GBPCHF",
                    "GBPJPY",
                ]
            ),
            portfolio=data.get("portfolio", {}),
            execution=execution,
            optimizations=data.get("optimizations", {}),
            mt5=MT5Config.from_dict(data.get("mt5", {})),
            data_source=data.get("data_source", "yfinance"),
            alerting=data.get("alerting", {}),
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
            "retention": dict(self.retention),
        }


_MISSING = object()


def _diff_keys(left: dict, right: dict, prefix: str = "") -> list[str]:
    """Return flat key paths where two dicts differ.

    Recursive; only reports leaf-level mismatches. Keys present in one
    but not the other are listed under their path.
    """
    diffs: list[str] = []
    all_keys = set(left) | set(right)
    for k in sorted(all_keys):
        path = f"{prefix}.{k}" if prefix else str(k)
        lv = left.get(k, _MISSING)
        rv = right.get(k, _MISSING)
        if isinstance(lv, dict) and isinstance(rv, dict):
            diffs.extend(_diff_keys(lv, rv, path))
        elif lv is not rv and lv != rv:
            diffs.append(path)
    return diffs


def _warn_on_legacy_drift(requested_path: Path, registry_dict: dict) -> None:
    """Warn if the default legacy file has drifted from the domain tree.

    Phase 12.1 strict write-mode: the domain tree is the authoritative
    source. The legacy file is a derived mirror — operator edits should go to
    the corresponding file under configs/domains/. Set the env var
    ``ENABLE_LEGACY_EDITS`` to silence this warning.
    """
    if os.environ.get(ENABLE_LEGACY_EDITS):
        return
    if not requested_path.exists():
        return
    on_disk = yaml.safe_load(requested_path.read_text()) or {}
    if on_disk == registry_dict:
        return
    diff_paths = _diff_keys(on_disk, registry_dict)
    # Only warn when the diff touches keys the domain tree owns
    # (not legacy_extras that are expected to differ)
    logger.warning(
        "STRICT-WRITE: the legacy mirror differs from the domain tree on "
        "%d key(s): %s.  Operator edits should go to configs/domains/ — "
        "the legacy file is a derived mirror.  Set %s=1 to silence.",
        len(diff_paths),
        ", ".join(diff_paths[:20]) + ("..." if len(diff_paths) > 20 else ""),
        ENABLE_LEGACY_EDITS,
    )


def load_config(path: str | None = None) -> EngineConfig:
    """Load and return EngineConfig via the typed paper registry.

    The legacy ``configs/paper_trading.yaml`` was deleted in Phase 12.7
    (all keys promoted to domain files). ``PaperConfigRegistry`` now reads
    exclusively from ``configs/domains/`` — the legacy path is no longer
    auto-loaded; it is still accepted as an explicit overlay for test
    fixtures and ad-hoc YAMLs.

    Call-site contract:
      - ``path=None`` (default): PaperConfigRegistry reads only the
        domain tree. The deleted legacy file is not consulted.
      - ``path=<yaml>`` (explicit, must exist): the file is loaded
        as an overlay on top of the registry output (test fixtures,
        ad-hoc overrides).
    """
    from configs.paper_config_registry import DOMAINS_DIR, PaperConfigRegistry

    if path is None:
        # Production default path: domain tree only. No implicit lookup
        # of the deleted legacy mirror file.
        try:
            reg = PaperConfigRegistry.load(domains_dir=DOMAINS_DIR)
            typed = reg.as_legacy_dict()
            logger.info(
                "Loaded config from registry (%d assets, %d legacy extras)",
                len(reg.assets),
                len(reg.legacy_extras),
            )
            return EngineConfig.from_dict(typed)
        except Exception as e:  # noqa: BLE001 — fall back below
            logger.warning("PaperConfigRegistry failed (%s); using defaults", e)
            return EngineConfig()

    # Explicit path: use the file if it exists; overlay its keys onto
    # the registry output. If the path does not exist, treat as defaults.
    requested_path = Path(path).resolve()
    try:
        reg = PaperConfigRegistry.load(legacy_path=requested_path, domains_dir=DOMAINS_DIR)
        typed = reg.as_legacy_dict()

        if requested_path.exists():
            raw = yaml.safe_load(requested_path.read_text()) or {}
            _deep_overlay(typed, raw)

        logger.info(
            "Loaded config from registry + explicit overlay at %s (%d assets, %d legacy extras)",
            requested_path,
            len(reg.assets),
            len(reg.legacy_extras),
        )
        return EngineConfig.from_dict(typed)
    except Exception as e:  # noqa: BLE001 — fall back to direct YAML
        logger.warning(
            "PaperConfigRegistry failed (%s); falling back to direct YAML loader for %s",
            e,
            requested_path,
        )

    if requested_path.exists():
        with open(str(requested_path)) as f:
            data = yaml.safe_load(f) or {}
        return EngineConfig.from_dict(data)
    logger.warning("Config file %s not found; using defaults", str(requested_path))
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
        path: Optional config file path. ``None`` (default) loads from
            the domain tree only — the legacy mirror file was deleted
            in Phase 12.7 and is no longer auto-loaded. Pass an explicit
            path to overlay a YAML on top of the registry output (test
            fixtures, ad-hoc overrides).
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


@contextlib.contextmanager
def config_context(config: EngineConfig) -> Iterator[None]:
    """Temporarily override the global config.

    Usage in tests::

        with config_context(my_config):
            cfg = get_config()
            # cfg is my_config
        # Outside the block, get_config() returns the previous value

    Nesting is supported — the outer value is restored when the inner
    context exits.
    """
    global _GLOBAL_CONFIG
    previous = _GLOBAL_CONFIG
    _GLOBAL_CONFIG = config
    try:
        yield
    finally:
        _GLOBAL_CONFIG = previous


def reset_config() -> None:
    global _GLOBAL_CONFIG
    _GLOBAL_CONFIG = None
