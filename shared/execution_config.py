from dataclasses import dataclass, fields

import numpy as np


@dataclass
class ExecutionConfig:
    """Configurable parameters for execution degradation models."""

    # ── Spread expansion ──────────────────────────────────────────
    base_spread_bps: float = 0.5  # 0.5 bps for FX majors
    spread_vol_slope: float = 2.0  # multiple per vol z-score > 1
    spread_max_bps: float = 50.0  # cap at 50 bps in extreme stress

    # ── Market impact ─────────────────────────────────────────────
    impact_model: str = "none"  # none, linear, square_root
    impact_coeff: float = 0.1
    avg_daily_volume: float = 1e9  # 1B notional

    # ── Stop-loss gap risk ────────────────────────────────────────
    base_gap_bps: float = 0.5  # base gap noise (0.5 bps)
    gap_vol_slope: float = 3.0  # gap grows nonlinearly with vol
    gap_max_bps: float = 300.0  # 3% max gap (flash crash scenario)

    # ── Partial fills / liquidity ─────────────────────────────────
    fill_vol_threshold: float = 2.0  # vol z-score above this reduces fill rate
    fill_prob_slope: float = -0.12  # fill prob drops 12pp per z-score > threshold
    min_fill_prob: float = 0.60  # never below 60% fill rate

    # ── Execution delay ───────────────────────────────────────────
    delay_vol_threshold: float = 2.5  # vol z-score above this introduces delay
    delay_bars_max: int = 2  # max bars of execution delay
    latency_bps: float = 0.5  # base execution latency (slippage) in bps

    # ── Volatility computation ────────────────────────────────────
    vol_window: int = 21  # rolling window for vol estimation


def btc_execution_config() -> ExecutionConfig:
    """BTC-specific execution parameters."""
    return ExecutionConfig(
        base_spread_bps=2.0,
        spread_vol_slope=3.0,
        spread_max_bps=150.0,
        base_gap_bps=2.0,
        gap_vol_slope=5.0,
        gap_max_bps=1000.0,
        fill_vol_threshold=1.5,
        fill_prob_slope=-0.20,
        min_fill_prob=0.30,
        delay_vol_threshold=2.0,
        delay_bars_max=3,
        latency_bps=2.0,
    )


DEFAULT_EXECUTION_CONFIGS = {"BTC": btc_execution_config(), "default": ExecutionConfig()}


def compute_slippage_cost(vol_zscore: np.ndarray, config: ExecutionConfig) -> np.ndarray:
    """Spread expansion as a function of volatility z-score."""
    excess = np.maximum(0.0, vol_zscore - 1.0)
    spread_bps = config.base_spread_bps * (1.0 + config.spread_vol_slope * excess)
    spread_bps += config.latency_bps  # Apply constant latency penalty
    spread_bps = np.minimum(spread_bps, config.spread_max_bps)
    return spread_bps / 10000.0  # bps → decimal


def execution_config_from_dict(data: dict | None) -> ExecutionConfig:
    """Build ExecutionConfig from a YAML-style dict (merges over defaults)."""
    if not data:
        return ExecutionConfig()
    valid = {f.name for f in fields(ExecutionConfig)}
    kwargs = {k: v for k, v in data.items() if k in valid}
    return ExecutionConfig(**kwargs)


def build_execution_configs(
    assets: dict,
    defaults: dict | None = None,
) -> dict[str, ExecutionConfig]:
    """Per-asset execution configs for PaperBroker and survival sim."""
    base = execution_config_from_dict(defaults)
    configs: dict[str, ExecutionConfig] = {"default": base}
    for name, spec in assets.items():
        ticker = spec.get("ticker", name)
        overrides = spec.get("execution_config") or {}
        merged = {
            "base_spread_bps": base.base_spread_bps,
            "spread_vol_slope": base.spread_vol_slope,
            "spread_max_bps": base.spread_max_bps,
            "impact_model": base.impact_model,
            "impact_coeff": base.impact_coeff,
            "avg_daily_volume": base.avg_daily_volume,
            "vol_window": base.vol_window,
            "latency_bps": base.latency_bps,
        }
        merged.update(overrides)
        cfg = execution_config_from_dict(merged)
        configs[ticker] = cfg
        configs[name] = cfg
    if "BTC" not in configs and "BTC-USD" not in configs and "BTCUSD" not in configs:
        configs["BTC"] = btc_execution_config()
        configs["BTC-USD"] = configs["BTC"]
        configs["BTCUSD"] = configs["BTC"]
    return configs


def compute_market_impact(position_notional: float, config: ExecutionConfig) -> float:
    """Market impact as a function of trade size relative to ADV."""
    if config.impact_model == "none" or config.avg_daily_volume <= 0:
        return 0.0

    participation_rate = position_notional / config.avg_daily_volume
    if config.impact_model == "linear":
        impact_bps = config.impact_coeff * participation_rate * 10000.0
    elif config.impact_model == "square_root":
        impact_bps = config.impact_coeff * np.sqrt(participation_rate) * 10000.0
    else:
        return 0.0

    return impact_bps / 10000.0
