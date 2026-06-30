import sys
from pathlib import Path

import yaml

REPO_ROOT = Path(__file__).resolve().parent.parent
CONFIG_PATH = REPO_ROOT / "configs" / "paper_trading.yaml"


def _check_type(value, expected_type, path: str, errors: list[str]) -> None:
    if not isinstance(value, expected_type):
        errors.append(f"{path}: expected {expected_type.__name__}, got {type(value).__name__} ({value!r})")


def _check_optional(data: dict, key: str, expected_type, path: str, errors: list[str]) -> None:
    if key in data:
        _check_type(data[key], expected_type, f"{path}.{key}", errors)


def _validate_asset(name: str, cfg: dict, errors: list[str]) -> None:
    prefix = f"assets.{name}"
    _check_type(cfg, dict, prefix, errors)
    if not isinstance(cfg, dict):
        return
    ticker = cfg.get("ticker")
    if not isinstance(ticker, str) or not ticker:
        errors.append(f"{prefix}.ticker: required string, got {ticker!r}")
    allocation = cfg.get("allocation")
    if allocation is not None:
        _check_type(allocation, (int, float), f"{prefix}.allocation", errors)
    _check_optional(cfg, "sl_mult", (int, float), prefix, errors)
    _check_optional(cfg, "tp_mult", (int, float), prefix, errors)
    _check_optional(cfg, "spread_tier", str, prefix, errors)
    _check_optional(cfg, "max_entry_slippage_pct", (int, float), prefix, errors)


def validate(config_path: str | None = None) -> int:
    path = Path(config_path or CONFIG_PATH)
    if not path.exists():
        print(f"FAILED: Config file not found: {path}")
        return 1

    try:
        with open(path) as f:
            data = yaml.safe_load(f)
    except yaml.YAMLError as e:
        print(f"FAILED: YAML parse error: {e}")
        return 1

    if not isinstance(data, dict):
        print("FAILED: Config root must be a mapping")
        return 1

    errors: list[str] = []

    # Top-level required/type checks
    capital = data.get("capital", 0)
    _check_type(capital, (int, float), "capital", errors)
    if isinstance(capital, (int, float)) and capital <= 0:
        errors.append(f"capital must be positive, got {capital}")

    pos_size = data.get("position_size", 0.95)
    _check_type(pos_size, (int, float), "position_size", errors)
    if isinstance(pos_size, (int, float)) and not (0 < pos_size <= 1.0):
        errors.append(f"position_size must be in (0, 1], got {pos_size}")

    _check_type(data.get("rebalance", ""), str, "rebalance", errors)
    _check_type(data.get("data_source", ""), str, "data_source", errors)

    if data.get("rebalance") not in ("daily", "weekly", "monthly", "none", ""):
        errors.append(f"rebalance: invalid value '{data.get('rebalance')}'")

    if data.get("data_source") not in ("yfinance", "mt5", ""):
        errors.append(f"data_source: invalid value '{data.get('data_source')}'")

    # Portfolio drawdown limit
    dd = data.get("portfolio_drawdown_limit", -0.15)
    _check_type(dd, (int, float), "portfolio_drawdown_limit", errors)
    if isinstance(dd, (int, float)) and not (-1.0 <= dd <= 0.0):
        errors.append(f"portfolio_drawdown_limit must be in [-1.0, 0.0], got {dd}")

    # mt5 section
    mt5 = data.get("mt5", {})
    _check_type(mt5, dict, "mt5", errors)
    if isinstance(mt5, dict):
        _check_optional(mt5, "enabled", bool, "mt5", errors)
        _check_optional(mt5, "bridge_port", int, "mt5", errors)
        if isinstance(mt5.get("bridge_port"), int):
            port = mt5["bridge_port"]
            if not (1 <= port <= 65535):
                errors.append(f"mt5.bridge_port must be in [1, 65535], got {port}")
        _check_optional(mt5, "bridge_host", str, "mt5", errors)
        _check_optional(mt5, "min_lot", (int, float), "mt5", errors)

    # assets section
    assets = data.get("assets", {})
    _check_type(assets, dict, "assets", errors)
    if isinstance(assets, dict):
        for name, cfg in assets.items():
            _validate_asset(name, cfg, errors)

    # defaults section
    defaults = data.get("defaults", {})
    _check_type(defaults, dict, "defaults", errors)
    if isinstance(defaults, dict):
        _check_optional(defaults, "min_confidence", (int, float), "defaults", errors)
        _check_optional(defaults, "max_position_pct_of_equity", (int, float), "defaults", errors)
        _check_optional(defaults, "max_risk_per_trade_pct", (int, float), "defaults", errors)
        _check_optional(defaults, "portfolio_max_leverage", (int, float), "defaults", errors)
        _check_optional(defaults, "sell_only_assets", list, "defaults", errors)
        _check_optional(defaults, "spread_gate", dict, "defaults", errors)
        _check_optional(defaults, "session_gate", dict, "defaults", errors)
        _check_optional(defaults, "stacking", dict, "defaults", errors)

    # ensemble section
    ensemble = data.get("ensemble", {})
    _check_type(ensemble, dict, "ensemble", errors)
    if isinstance(ensemble, dict):
        _check_optional(ensemble, "base_weight", (int, float), "ensemble", errors)
        _check_optional(ensemble, "threshold", (int, float), "ensemble", errors)

    # calibration section
    cal = data.get("calibration", {})
    _check_type(cal, dict, "calibration", errors)
    if isinstance(cal, dict):
        _check_optional(cal, "enabled", bool, "calibration", errors)
        _check_optional(cal, "method", str, "calibration", errors)

    # portfolio section
    pf = data.get("portfolio", {})
    _check_type(pf, dict, "portfolio", errors)
    if isinstance(pf, dict):
        _check_optional(pf, "weight_method", str, "portfolio", errors)

    # execution section
    exec_cfg = data.get("execution", {})
    _check_type(exec_cfg, dict, "execution", errors)

    # alerting
    alert = data.get("alerting", {})
    _check_type(alert, dict, "alerting", errors)

    if errors:
        print(f"FAILED: {len(errors)} config schema violation(s):")
        for e in errors:
            print(f"  - {e}")
        return 1

    asset_count = len(data.get("assets", {}))
    depth = len(data.get("defaults", {}).get("sell_only_assets", []))
    print(f"PASSED: config schema valid ({asset_count} assets, {depth} sell-only assets).")
    return 0


if __name__ == "__main__":
    sys.exit(validate())
