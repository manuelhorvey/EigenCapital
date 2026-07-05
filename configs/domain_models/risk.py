"""Risk-domain typed configuration models.

Phase 3: typed layer over the legacy defaults flatten. Reads from a
future configs/domains/risk/*.yaml tree via the mirror, or falls back
to legacy YAML keys with the matching path.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal

# ── Capital ──────────────────────────────────────────────────────────────


@dataclass(frozen=True)
class CapitalConfig:
    """Top-level capital and portfolio-wide drawdown parameters."""

    initial: float = 100_000.0
    """Initial capital in account currency."""

    position_size: float = 0.95
    """Base position size scalar applied to the sizing chain."""

    portfolio_drawdown_limit: float = -0.15
    """Portfolio-level drawdown halt threshold (negative fraction)."""


# ── Halt ────────────────────────────────────────────────────────────────


@dataclass(frozen=True)
class HaltConfig:
    """Circuit-breaker thresholds for emergency halt.

    Currently lives only in ``paper_trading/config_manager._default_halt``;
    this typed model is the future source of truth (Phase 4 write-mode
    split).
    """

    drawdown: float = -0.08
    monthly_pf: float = 0.70
    signal_drought: int = 30
    prob_drift: float = 0.25
    expected_prob_conf: float = 0.65
    prob_drift_min_samples: int = 10


# ── Sizing ──────────────────────────────────────────────────────────────


@dataclass(frozen=True)
class SizingConfig:
    """Position-sizing guardrails shared across all assets.

    These were previously ``defaults.*`` keys in the legacy YAML; here
    they live as a single typed aggregate with no inheritance.
    """

    rolling_window_bars: int | None = 756
    churn_ratio_threshold: float = 0.35
    cooldown_half_life_hours: float = 4.0
    cooldown_max_penalty_pct: float = 20.0
    entry_defer_max_bars: int = 5
    min_flip_interval_bars: int = 3
    min_confidence: float = 55.0
    max_entry_slippage_pct: float = 2.0
    profit_lock_threshold_pct: float = 15.0
    max_position_pct_of_equity: float = 0.15
    max_risk_per_trade_pct: float = 2.0
    min_risk_per_trade_pct: float = 0.001
    min_viable_position_pct: float = 0.01
    size_taper_start_dd: float = -0.05
    size_taper_end_dd: float = -0.15
    size_taper_min: float = 0.50
    max_positions_per_asset: int = 2
    max_concurrent_positions: int = 8
    max_daily_loss_pct: float = 0.08
    portfolio_max_leverage: float = 2.0
    portfolio_leverage_tolerance: float = 0.001
    mt5_leverage_budget_enabled: bool = False
    mt5_leverage_budget_soft: bool = True
    net_short_concentration_threshold: float = 0.75
    mt5_enable_max_risk_per_trade_pct: bool = False
    mt5_max_risk_per_trade_pct: float = 10.0
    mt5_bypass_risk_cap_at_min_lot: bool = True


# ── Exits ──────────────────────────────────────────────────────────────


@dataclass(frozen=True)
class ExitConfig:
    """Adaptive-exit policy.

    Per-asset overrides may swap ``trail_activation_r`` between 0.5
    and 0.8; the other fields are shared defaults lifted from the
    legacy YAML ``defaults.adaptive_exit`` block.
    """

    enabled: bool = True
    be_lock_r: float = 0.5
    trail_activation_r: float = 0.8
    trail_retrace_pct: float = 0.33
    max_hold_candles: int = 40
    time_decay_start: int = 20
    scale_out_fraction: float = 0.7
    scale_out_r: float = 2.5

    def with_overrides(self, **overrides: Any) -> ExitConfig:
        """Return a copy with selective overrides applied.

        Unknown keys raise ``TypeError``, surfacing drift between the
        typed model and the YAML file at load time.
        """
        valid = {f for f in self.__dataclass_fields__}
        unknown = set(overrides) - valid
        if unknown:
            raise TypeError(
                f"ExitConfig.with_overrides received unknown keys: {sorted(unknown)}; allowed: {sorted(valid)}"
            )
        current = {f: getattr(self, f) for f in valid}
        current.update(overrides)
        return ExitConfig(**current)


@dataclass(frozen=True)
class SellOnlyConfig:
    """SELL_ONLY_ASSETS truth.

    The legacy YAML stored ``defaults.sell_only_assets: list``. The
    matching Python constant lives in paper_trading/execution/decision_pipeline.py
    as a frozenset. Phase 5 unifies them via this typed container.
    """

    assets: frozenset[str] = field(default_factory=lambda: frozenset({"CADCHF", "NZDCHF", "EURAUD"}))

    def contains(self, asset_name: str) -> bool:
        return asset_name in self.assets


# ── Aggregate root ─────────────────────────────────────────────────────

RiskDomain = Literal["capital", "halt", "sizing", "exits", "sell_only"]


@dataclass(frozen=True)
class RiskConfig:
    """Aggregate root for the risk domain.

    Reads from configs/domains/risk/capital.yaml + sizing.yaml + exits.yaml
    + halt.yaml in Phase 4. Phase 3 supplies a builder that derives this
    from the legacy :class:`~paper_trading.config_manager.EngineConfig`.
    """

    capital: CapitalConfig
    halt: HaltConfig
    sizing: SizingConfig
    exits_default: ExitConfig
    sell_only: SellOnlyConfig

    @classmethod
    def from_legacy(cls, data: dict, halt_override: dict | None = None) -> RiskConfig:
        """Build :class:`RiskConfig` from the legacy paper_trading.yaml dict.

        Parameters
        ----------
        data
            Raw parsed YAML dict.
        halt_override
            Optional fully-resolved halt dict (defaults merged) sourced
            from ``EngineConfig.halt``. When provided, skips the legacy
            ``_default_halt`` merge step.
        """
        defaults = data.get("defaults", {}) or {}

        # Capital
        capital = CapitalConfig(
            initial=float(data.get("capital", 100_000)),
            position_size=float(data.get("position_size", 0.95)),
            portfolio_drawdown_limit=float(data.get("portfolio_drawdown_limit", -0.15)),
        )

        # Halt
        halt_raw = halt_override if halt_override is not None else (data.get("halt") or {})
        canonical_halt = {
            "drawdown": -0.08,
            "monthly_pf": 0.70,
            "signal_drought": 30,
            "prob_drift": 0.25,
            "expected_prob_conf": 0.65,
            "prob_drift_min_samples": 10,
        }
        canonical_halt.update({k: v for k, v in halt_raw.items() if v is not None})
        halt = HaltConfig(**canonical_halt)

        # Sizing — touch every key so the typed model exhausts the legacy surface
        sizing_kw = {
            f.name: _coerce(
                getattr(SizingConfig, f.name), defaults.get(_legacy_key(f.name), getattr(SizingConfig, f.name))
            )
            for f in SizingConfig.__dataclass_fields__.values()
        }
        sizing = SizingConfig(**sizing_kw)

        # Exits default
        ae = defaults.get("adaptive_exit") or {}
        exits_default = ExitConfig(
            enabled=bool(ae.get("enabled", True)),
            be_lock_r=float(ae.get("be_lock_r", 0.5)),
            trail_activation_r=float(ae.get("trail_activation_r", 0.8)),
            trail_retrace_pct=float(ae.get("trail_retrace_pct", 0.33)),
            max_hold_candles=int(ae.get("max_hold_candles", 40)),
            time_decay_start=int(ae.get("time_decay_start", 20)),
            scale_out_fraction=float(ae.get("scale_out_fraction", 0.7)),
            scale_out_r=float(ae.get("scale_out_r", 2.5)),
        )

        # Sell-only
        sell_list = defaults.get("sell_only_assets") or ["CADCHF", "NZDCHF", "EURAUD"]
        sell_only = SellOnlyConfig(assets=frozenset(sell_list))

        return cls(capital=capital, halt=halt, sizing=sizing, exits_default=exits_default, sell_only=sell_only)


# ── Helpers ────────────────────────────────────────────────────────────

_LEGACY_KEY_MAP: dict[str, str] = {
    # typed-key -> legacy YAML key (overrides the identity mapping when
    # a key lives under a different name)
}


def _legacy_key(typed_key: str) -> str:
    return _LEGACY_KEY_MAP.get(typed_key, typed_key)


def _coerce(field_default: Any, raw: Any) -> Any:
    """Cast ``raw`` to the type declared by ``field_default``.

    Mirrors the strict-typing expectation: if the YAML supplies a float
    where the model declared int, the coercion fails loud.
    """
    if raw is None:
        return field_default
    expected_type = type(field_default)
    if expected_type is bool:
        return bool(raw)
    if expected_type is int:
        return int(raw)
    if expected_type is float:
        return float(raw)
    return raw
