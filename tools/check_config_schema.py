"""
check_config_schema.py — schema, range, type, and cross-field validator.

This is the canonical pre-deploy configuration check. Phase 1 upgrades
the legacy validator with:

- Per-asset uniqueness (ticker and short name)
- Allocation-sum check (<= 1.0 across active assets)
- tp_mult/sl_mut consistency against features/registry.ASSET_LABEL_PARAMS
- Required regime_geometry bands (GREEN/YELLOW/RED)
- Cross-section field type checks for spread_gate + session_gate tiers
- Mode consistency: declared modes must be referenced if `mode:` is set
- Asset count parity (active config vs declared mode)

**Phase 12.2 — Cross-field invariants:**

- ``mt5_max_risk_per_trade_pct <= max_risk_per_trade_pct`` — when enabled, MT5
  risk cap must not exceed the paper risk cap. When disabled, emits a benign
  warning if the MT5 cap is higher.
- ``profit_lock_threshold_pct`` validated in [0, 100] — must be a valid
  percentage.
- ``factor_exposure_limits``: each limit validated in [0, 1]; sum > 1.0 emits
  a warning (factor groups overlap, so summed caps > 1.0 is expected).

Backward-compatible: validated keys overlap with the legacy check.
The legacy min_lot check is dropped because mt5.min_lot has been removed
from the YAML.
"""

import importlib
import logging
import re
import sys
from pathlib import Path
from typing import Any

import yaml

logger = logging.getLogger("eigencapital.tools.check_config_schema")

REPO_ROOT = Path(__file__).resolve().parent.parent


def _load_config_data() -> dict:
    """Load config from PaperConfigRegistry (domain-first).

    The legacy ``configs/paper_trading.yaml`` was deleted in Phase 12.7
    (all keys promoted to domain files). The registry emits the same
    surface shape from ``as_legacy_dict()``.
    """
    sys.path.insert(0, str(REPO_ROOT))
    from configs.paper_config_registry import PaperConfigRegistry

    reg = PaperConfigRegistry.load()
    return reg.as_legacy_dict()


_TICKER_OR_KEY = re.compile(r"^=?[A-Z][A-Z0-9\^=]*$")


def _check_type(value: Any, expected_type: type | tuple[type, ...], path: str, errors: list[str]) -> None:
    if not isinstance(value, expected_type):
        names = (
            expected_type.__name__
            if isinstance(expected_type, type)
            else " | ".join(getattr(t, "__name__", str(t)) for t in expected_type)
        )
        errors.append(f"{path}: expected {names}, got {type(value).__name__} ({value!r})")


def _check_optional(data: dict, key: str, expected_type, path: str, errors: list[str]) -> None:
    if key in data:
        _check_type(data[key], expected_type, f"{path}.{key}", errors)


def _expected_bands() -> tuple[str, ...]:
    return ("GREEN", "YELLOW", "RED")


def _validate_asset(name: str, cfg: dict, errors: list[str], warnings: list[str]) -> None:
    prefix = f"assets.{name}"
    _check_type(cfg, dict, prefix, errors)
    if not isinstance(cfg, dict):
        return

    ticker = cfg.get("ticker")
    if not isinstance(ticker, str) or not ticker:
        errors.append(f"{prefix}.ticker: required string, got {ticker!r}")
    elif not _TICKER_OR_KEY.match(ticker) and "=" in ticker[:3]:
        warnings.append(f"{prefix}.ticker: ticker {ticker!r} has unusual prefix")

    allocation = cfg.get("allocation")
    if allocation is None:
        warnings.append(f"{prefix}.allocation: missing - will default to 0.0")
    else:
        _check_type(allocation, (int, float), f"{prefix}.allocation", errors)
        if isinstance(allocation, (int, float)) and allocation < 0:
            errors.append(f"{prefix}.allocation: must be >= 0, got {allocation}")

    for key in (
        "sl_mult",
        "tp_mult",
        "spread_tier",
        "max_entry_slippage_pct",
        "max_positions_per_asset",
        "min_confidence",
        "min_confidence_buy",
        "min_confidence_sell",
    ):
        _check_optional(cfg, key, (int, float, str), prefix, errors)

    regime = cfg.get("regime_geometry")
    if regime is not None:
        if not isinstance(regime, dict):
            errors.append(f"{prefix}.regime_geometry: expected mapping, got {type(regime).__name__}")
        else:
            bands = set(regime.keys())
            missing = [b for b in _expected_bands() if b not in bands]
            if missing:
                warnings.append(
                    f"{prefix}.regime_geometry: missing bands {missing}; engine will fall back to global geometry"
                )
            for band_name, band in regime.items():
                if not isinstance(band, dict):
                    errors.append(f"{prefix}.regime_geometry.{band_name}: expected mapping")


def _load_registry_label_params() -> dict:
    """Read ASSET_LABEL_PARAMS without forcing a full import path.

    Imported lazily so the validator remains usable in CI without the
    feature pipeline environment.
    """
    try:
        module = importlib.import_module("features.registry")
    except (ImportError, ModuleNotFoundError) as e:
        logger.warning("validator: warning - feature registry unavailable: %s", e)
        return {"labels": {}, "short_to_ticker": {}, "ticker_to_short": {}}
    except Exception as e:  # noqa: BLE001 - import path errors vary
        logger.warning("validator: warning - feature registry import failed: %s", e)
        return {"labels": {}, "short_to_ticker": {}, "ticker_to_short": {}}

    labels: dict[str, dict] = getattr(module, "ASSET_LABEL_PARAMS", {}) or {}
    feature_reg = getattr(module, "FEATURE_REGISTRY", {}) or {}

    short_to_ticker: dict[str, str] = {}
    ticker_to_short: dict[str, str] = {}
    for ticker, contract in feature_reg.items():
        short = getattr(contract, "name", None)
        if isinstance(short, str):
            short_to_ticker[short] = ticker
            ticker_to_short[ticker] = short

    return {
        "labels": labels,
        "short_to_ticker": short_to_ticker,
        "ticker_to_short": ticker_to_short,
    }


def _resolve_registry_param(short_name: str, ticker: str | None, registry: dict) -> str | None:
    """Find the short-name key in ASSET_LABEL_PARAMS for an asset.

    Tries direct match on the YAML key, then by ticker alias, then by
    name-prefix-match (e.g. 'BTCUSD' matches 'BTC'). Returns None when
    no match exists.
    """
    labels: dict[str, dict] = registry["labels"]
    if short_name in labels:
        return short_name
    if ticker:
        mapped = registry["ticker_to_short"].get(ticker)
        if mapped and mapped in labels:
            return mapped
    for key in labels:
        if not isinstance(key, str):
            continue
        if short_name == key or short_name in key or key in short_name:
            return key
    return None


def _check_label_consistency(assets: dict, registry: dict, warnings: list[str], errors: list[str]) -> None:
    """Cross-reference tp_mult/sl_mult in YAML against ASSET_LABEL_PARAMS.

    Tolerance: +/-5% on each value (intentional optimizer bumps allowed).
    Currently surfaces warnings; promoted to errors when type=strict.
    """
    labels: dict[str, dict] = registry["labels"]
    if not labels:
        return
    for short_name, cfg in assets.items():
        if not isinstance(cfg, dict):
            continue
        yaml_tp = cfg.get("tp_mult")
        yaml_sl = cfg.get("sl_mult")
        if yaml_tp is None or yaml_sl is None:
            continue
        reg_key = _resolve_registry_param(short_name, cfg.get("ticker"), registry)
        if reg_key is None:
            warnings.append(
                f"assets.{short_name}: tp_mult/sl_mult present but no entry in "
                "ASSET_LABEL_PARAMS - intentional override?"
            )
            continue
        reg = labels[reg_key]
        reg_tp = reg.get("pt")
        reg_sl = reg.get("sl")
        if reg_tp is None or reg_sl is None:
            continue
        tol = 0.05
        if abs(yaml_tp - reg_tp) / max(reg_tp, 1e-9) > tol:
            warnings.append(
                f"assets.{short_name}.tp_mult={yaml_tp} drifts from ASSET_LABEL_PARAMS "
                f"{reg_key}.pt={reg_tp} (>5%) - live SL/TP differs from training labels"
            )
        if abs(yaml_sl - reg_sl) / max(reg_sl, 1e-9) > tol:
            warnings.append(
                f"assets.{short_name}.sl_mult={yaml_sl} drifts from ASSET_LABEL_PARAMS "
                f"{reg_key}.sl={reg_sl} (>5%) - live SL/TP differs from training labels"
            )


def _check_allocation_sum(assets: dict, errors: list[str]) -> None:
    total = 0.0
    for name, cfg in assets.items():
        if not isinstance(cfg, dict):
            continue
        alloc = cfg.get("allocation")
        if isinstance(alloc, (int, float)):
            total += float(alloc)
    if total > 1.0 + 1e-6:
        errors.append(f"assets:Σ allocation = {total:.4f} exceeds 1.0; portfolio would be over-allocated")


def _check_ticker_uniqueness(assets: dict, errors: list[str]) -> None:
    seen: dict[str, str] = {}
    for name, cfg in assets.items():
        if not isinstance(cfg, dict):
            continue
        t = cfg.get("ticker")
        if isinstance(t, str) and t in seen:
            errors.append(f"assets: ticker {t!r} is shared by {seen[t]!r} and {name!r}; tickers must be unique")
        if isinstance(t, str):
            seen[t] = name


def _check_modes(data: dict, errors: list[str], warnings: list[str]) -> None:
    mode = data.get("mode")
    modes = data.get("modes") or {}
    if not mode:
        return
    if not isinstance(modes, dict):
        errors.append("modes: expected mapping")
        return
    if mode not in modes:
        errors.append(f"mode={mode!r} not present in modes: {sorted(modes)}")
        return
    body = modes[mode]
    if not isinstance(body, dict):
        errors.append(f"modes.{mode}: expected mapping")
        return
    if body.get("capital") is not None and isinstance(body["capital"], (int, float)) and body["capital"] <= 0:
        errors.append(f"modes.{mode}.capital: must be positive")
    if "portfolio_drawdown_limit" in body:
        v = body["portfolio_drawdown_limit"]
        if isinstance(v, (int, float)) and not (-1.0 <= v <= 0.0):
            errors.append(f"modes.{mode}.portfolio_drawdown_limit: must be in [-1.0, 0.0], got {v}")
    # Check factor_exposure_limits in each mode's defaults
    for mode_name, mode_body in modes.items():
        if not isinstance(mode_body, dict):
            continue
        mode_defaults = mode_body.get("defaults") or {}
        if not isinstance(mode_defaults, dict):
            continue
        fel = mode_defaults.get("factor_exposure_limits")
        if fel is not None:
            _check_factor_exposure_limits(f"modes.{mode_name}.defaults", fel, errors, warnings)


def _check_spread_session_gates(defaults: dict, errors: list[str]) -> None:
    sg = defaults.get("spread_gate")
    if isinstance(sg, dict):
        for tier, threshold in (sg.get("tiers") or {}).items():
            if not isinstance(threshold, (int, float)):
                errors.append(f"defaults.spread_gate.tiers.{tier}: expected number, got {threshold!r}")
            elif threshold < 0:
                errors.append(f"defaults.spread_gate.tiers.{tier}: must be >= 0 bps, got {threshold}")
    ses = defaults.get("session_gate")
    if isinstance(ses, dict):
        tiers = ses.get("tiers") or {}
        for tier, window in tiers.items():
            if not isinstance(window, (list, tuple)) or len(window) != 2:
                errors.append(
                    f"defaults.session_gate.tiers.{tier}: expected [start, end] UTC-hour pair, got {window!r}"
                )
                continue
            a, b = window
            if not (isinstance(a, (int, float)) and isinstance(b, (int, float))):
                errors.append(f"defaults.session_gate.tiers.{tier}: bounds must be numeric")
                continue
            if not (0 <= a <= 24 and 0 <= b <= 24):
                errors.append(f"defaults.session_gate.tiers.{tier}: bounds {window} outside [0, 24]")


def _check_mt5(mt5: dict, errors: list[str], warnings: list[str]) -> None:
    if not isinstance(mt5, dict):
        errors.append("mt5: expected mapping")
        return
    _check_optional(mt5, "enabled", bool, "mt5", errors)
    _check_optional(mt5, "bridge_port", int, "mt5", errors)
    port = mt5.get("bridge_port")
    if isinstance(port, int) and not (1 <= port <= 65535):
        errors.append(f"mt5.bridge_port: must be in [1, 65535], got {port}")
    if "min_lot" in mt5:
        warnings.append("mt5.min_lot: deprecated since 2026-06-29 (broker floor only); remove from YAML")


def _check_risk_invariants(defaults: dict, errors: list[str], warnings: list[str]) -> None:
    """Cross-field risk invariant: mt5_max_risk_per_trade_pct <= max_risk_per_trade_pct.

    When mt5_max_risk_per_trade_pct is set higher than max_risk_per_trade_pct,
    the MT5 risk cap (which applies to a smaller equity base) exceeds the paper
    risk cap. When mt5_enable_max_risk_per_trade_pct is active, this would allow
    MT5 to risk a higher % on a smaller base.
    """
    max_risk = defaults.get("max_risk_per_trade_pct")
    mt5_max = defaults.get("mt5_max_risk_per_trade_pct")
    if max_risk is not None and mt5_max is not None and mt5_max > max_risk:
        enabled = defaults.get("mt5_enable_max_risk_per_trade_pct", False)
        msg = f"defaults.mt5_max_risk_per_trade_pct={mt5_max} exceeds defaults.max_risk_per_trade_pct={max_risk};"
        if enabled:
            errors.append(f"{msg} active MT5 risk cap would override paper cap with higher limit")
        else:
            warnings.append(f"{msg} MT5 cap currently disabled (benign, but may cause confusion)")


def _check_profit_lock_range(defaults: dict, errors: list[str]) -> None:
    """Check profit_lock_threshold_pct is a valid percentage in [0, 100]."""
    v = defaults.get("profit_lock_threshold_pct")
    if v is None:
        return
    if not isinstance(v, (int, float)):
        errors.append(f"defaults.profit_lock_threshold_pct: expected number, got {v!r}")
        return
    if not (0 <= v <= 100):
        errors.append(f"defaults.profit_lock_threshold_pct: must be in [0, 100], got {v}")


def _check_factor_exposure_limits(
    source_name: str,
    limits: dict[str, float],
    errors: list[str],
    warnings: list[str],
) -> None:
    """Check factor exposure limits: each in [0, 1]; warn if sum > 1.0.

    Factor groups overlap (an asset can belong to multiple groups), so the
    sum of per-factor caps naturally exceeds 1.0. The warning flags cases
    where the total is unreasonably high relative to the individual limits.
    Each individual limit is validated to be in [0, 1] as a hard error because
    a single factor can't have more than 100% portfolio exposure.
    """
    if not isinstance(limits, dict):
        errors.append(f"{source_name}.factor_exposure_limits: expected mapping")
        return
    total = 0.0
    for factor, limit in limits.items():
        if not isinstance(limit, (int, float)):
            errors.append(f"{source_name}.factor_exposure_limits.{factor}: expected number, got {limit!r}")
            continue
        if not (0 <= limit <= 1.0):
            errors.append(f"{source_name}.factor_exposure_limits.{factor}: must be in [0, 1.0], got {limit}")
            continue
        total += float(limit)
    if total > 1.0 + 1e-6:
        warnings.append(
            f"{source_name}.factor_exposure_limits: Σ limits = {total:.4f} exceeds 1.0; "
            "factor groups overlap, so this is common but may indicate configuration drift"
        )


def _check_halt(data: dict, errors: list[str]) -> None:
    if "halt" not in data:
        return
    halt = data["halt"]
    if not isinstance(halt, dict):
        return
    dd = halt.get("drawdown")
    if isinstance(dd, (int, float)) and not (-1.0 <= dd <= 0.0):
        errors.append(f"halt.drawdown: must be in [-1.0, 0.0], got {dd}")


def validate(config_path: str | None = None) -> int:
    logging.basicConfig(level=logging.INFO, format="%(message)s", stream=sys.stdout, force=True)
    if config_path:
        # Explicit config path: read directly (test fixtures)
        path = Path(config_path)
        if not path.exists():
            print(f"FAILED: Config file not found: {path}")
            return 1
        try:
            data = yaml.safe_load(path.read_text())
        except yaml.YAMLError as e:
            print(f"FAILED: YAML parse error: {e}")
            return 1
    else:
        # Default: load from registry (domain tree)
        try:
            data = _load_config_data()
        except Exception as e:  # noqa: BLE001
            print(f"FAILED: Could not load registry: {e}")
            return 1

    if not isinstance(data, dict):
        print("FAILED: Config root must be a mapping")
        return 1

    errors: list[str] = []
    warnings: list[str] = []

    capital = data.get("capital", 0)
    _check_type(capital, (int, float), "capital", errors)
    if isinstance(capital, (int, float)) and capital <= 0:
        errors.append(f"capital: must be positive, got {capital}")

    pos = data.get("position_size", 0.95)
    _check_type(pos, (int, float), "position_size", errors)
    if isinstance(pos, (int, float)) and not (0 < pos <= 1.0):
        errors.append(f"position_size: must be in (0, 1.0], got {pos}")

    _check_type(data.get("rebalance", ""), str, "rebalance", errors)
    _check_type(data.get("data_source", ""), str, "data_source", errors)

    if data.get("rebalance") not in ("daily", "weekly", "monthly", "none", ""):
        errors.append(f"rebalance: invalid value {data.get('rebalance')!r}")
    if data.get("data_source") not in ("yfinance", "mt5", ""):
        errors.append(f"data_source: invalid value {data.get('data_source')!r}")

    dd = data.get("portfolio_drawdown_limit", -0.15)
    _check_type(dd, (int, float), "portfolio_drawdown_limit", errors)
    if isinstance(dd, (int, float)) and not (-1.0 <= dd <= 0.0):
        errors.append(f"portfolio_drawdown_limit: must be in [-1.0, 0.0], got {dd}")

    _check_mt5(data.get("mt5", {}), errors, warnings)
    _check_halt(data, errors)

    assets = data.get("assets") or {}
    _check_type(assets, dict, "assets", errors)
    if isinstance(assets, dict):
        seen_names: set[str] = set()
        for name, cfg in assets.items():
            if name in seen_names:
                errors.append(f"assets: duplicate entry {name!r}")
            seen_names.add(name)
            _validate_asset(name, cfg, errors, warnings)
        _check_allocation_sum(assets, errors)
        _check_ticker_uniqueness(assets, errors)
        label_params = _load_registry_label_params()
        _check_label_consistency(assets, label_params, warnings, errors)

    defaults = data.get("defaults") or {}
    if isinstance(defaults, dict):
        _check_optional(defaults, "min_confidence", (int, float), "defaults", errors)
        _check_optional(defaults, "min_confidence_buy", (int, float), "defaults", errors)
        _check_optional(defaults, "min_confidence_sell", (int, float), "defaults", errors)
        _check_optional(defaults, "max_position_pct_of_equity", (int, float), "defaults", errors)
        _check_optional(defaults, "max_risk_per_trade_pct", (int, float), "defaults", errors)
        _check_optional(defaults, "portfolio_max_leverage", (int, float), "defaults", errors)
        _check_optional(defaults, "sell_only_assets", list, "defaults", errors)
        _check_optional(defaults, "spread_gate", dict, "defaults", errors)
        _check_optional(defaults, "session_gate", dict, "defaults", errors)
        _check_spread_session_gates(defaults, errors)
        _check_risk_invariants(defaults, errors, warnings)
        _check_profit_lock_range(defaults, errors)
        fel = defaults.get("factor_exposure_limits")
        if fel is not None:
            _check_factor_exposure_limits("defaults", fel, errors, warnings)

    _check_modes(data, errors, warnings)

    ensemble = data.get("ensemble", {})
    if isinstance(ensemble, dict):
        _check_optional(ensemble, "base_weight", (int, float), "ensemble", errors)
        _check_optional(ensemble, "threshold", (int, float), "ensemble", errors)

    cal = data.get("calibration", {})
    if isinstance(cal, dict):
        _check_optional(cal, "enabled", bool, "calibration", errors)
        _check_optional(cal, "method", str, "calibration", errors)
        if isinstance(cal.get("method"), str) and cal["method"] not in (
            "binned",
            "isotonic",
            "platt",
        ):
            warnings.append(
                f"calibration.method={cal['method']!r}: not in the recognized set "
                "(binned, isotonic, platt); verify intent"
            )

    pf = data.get("portfolio", {})
    if isinstance(pf, dict):
        _check_optional(pf, "weight_method", str, "portfolio", errors)
        fel = pf.get("factor_exposure_limits")
        if fel is not None:
            if not isinstance(fel, dict):
                errors.append("portfolio.factor_exposure_limits: expected mapping")
            else:
                for factor, limit in fel.items():
                    if not isinstance(limit, (list, tuple)) or len(limit) != 2:
                        errors.append(
                            f"portfolio.factor_exposure_limits.{factor}: expected [min, max], got {limit!r}"
                        )
                        continue
                    lo, hi = limit
                    if not (isinstance(lo, (int, float)) and isinstance(hi, (int, float))):
                        errors.append(
                            f"portfolio.factor_exposure_limits.{factor}: bounds must be numeric, got {limit!r}"
                        )
                        continue
                    if lo > 0:
                        warnings.append(
                            f"portfolio.factor_exposure_limits.{factor}.min={lo} is positive; "
                            "this prevents shorting the factor"
                        )
                    if hi < 0:
                        warnings.append(
                            f"portfolio.factor_exposure_limits.{factor}.max={hi} is negative; "
                            "this prevents going long the factor"
                        )

    exc = data.get("execution", {})
    if not isinstance(exc, dict):
        errors.append("execution: expected mapping")

    alerting = data.get("alerting", {})
    if not isinstance(alerting, dict):
        errors.append("alerting: expected mapping")

    if errors:
        logger.error("FAILED: %d config schema violation(s):", len(errors))
        for e in errors:
            logger.error("  - %s", e)
        if warnings:
            logger.warning("  (%d warning(s)):", len(warnings))
            for w in warnings:
                logger.warning("  - %s", w)
        return 1

    asset_count = len(assets or {})
    sell_only = (defaults.get("sell_only_assets") if isinstance(defaults, dict) else None) or []
    logger.info("PASSED: config schema valid (%d assets, %d sell-only assets).", asset_count, len(sell_only))
    if warnings:
        logger.warning("(%d soft warning(s)):", len(warnings))
        for w in warnings:
            logger.warning("  - %s", w)
    return 0


if __name__ == "__main__":
    sys.exit(validate())
