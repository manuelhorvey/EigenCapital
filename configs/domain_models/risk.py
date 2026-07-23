"""Risk-domain typed configuration models.

Phase 3: typed layer over the legacy defaults flatten. Reads from a
future configs/domains/risk/*.yaml tree via the mirror, or falls back
to legacy YAML keys with the matching path.
"""

from __future__ import annotations

from dataclasses import MISSING, Field, dataclass, field
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

    Sourced from ``configs/domains/risk/halt.yaml`` via
    ``PaperConfigRegistry``. Falls back to typed defaults when
    the domain file is absent.
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

    rolling_window_bars: int | None = None
    """Rolling window in bars for training data truncation.

    When set, training uses only the last N rows of features. Defaults to
    None — the effective window is determined by ``retrain_window * 252``
    at runtime in ``asset_engine.py``, so training uses the full configured
    retrain window instead of being silently capped at a hardcoded value.
    Per-asset overrides via ``rolling_window_bars`` in asset YAML still
    take precedence when explicitly set.
    """
    churn_ratio_threshold: float = 0.35
    cooldown_half_life_hours: float = 4.0
    cooldown_max_penalty_pct: float = 20.0
    entry_defer_max_bars: int = 5
    min_flip_interval_bars: int = 3
    min_confidence: float = 55.0
    min_confidence_buy: float = 45.0
    """Direction-conditional confidence threshold for BUY signals.

    BUY signals have systematically lower win rates (portfolio avg ~41%)
    than SELL signals (~72%). A lower threshold lets in more BUY trades
    at calibrated confidence levels, capturing alpha that would otherwise
    be filtered out. Default is 10pp below the global min_confidence.

    Falls back to ``min_confidence`` if not set, preserving backward
    compatibility with existing configs.
    """
    min_confidence_sell: float = 55.0
    """Direction-conditional confidence threshold for SELL signals.

    SELL signals are well-calibrated (WR ~72%), so the standard threshold
    is appropriate. Falls back to ``min_confidence`` if not set.
    """
    max_entry_slippage_pct: float = 2.0
    profit_lock_threshold_pct: float = 15.0
    max_position_pct_of_equity: float = 0.15
    max_risk_per_trade_pct: float = 2.0
    min_risk_per_trade_pct: float = 0.001
    risk_tiers: list[dict] = field(default_factory=list)
    """Risk-by-capital tiered profile.

    List of ``{threshold: float, risk_pct: float}`` dicts evaluated
    descending threshold. Dynamically overrides ``max_risk_per_trade_pct``
    based on current account equity. Empty list = disabled (uses flat
    ``max_risk_per_trade_pct``). Configured in ``sizing.yaml``.
    """
    min_viable_position_pct: float = 0.01
    size_taper_start_dd: float = -0.05
    size_taper_end_dd: float = -0.15
    size_taper_min: float = 0.50
    max_positions_per_asset: int = 2
    max_positions_per_cluster: int = 3
    """Maximum concurrent positions in the same correlated cluster.

    When a signal's asset belongs to a correlated cluster group (e.g. CHF:
    EURCHF, USDCHF, NZDCHF, CADCHF, GBPCHF), and that cluster already has
    *max_positions_per_cluster* positions with the same dominant side, the
    signal is rejected.  This prevents concentrated risk from correlated
    pairs moving together against the portfolio.
    """
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

    assets: frozenset[str] = field(
        default_factory=lambda: frozenset(
            {
                "CADCHF",
                "NZDCHF",
                "EURAUD",
                "EURCHF",  # Calibrated signal is 100% SELL despite raw BUY bias
                "GBPCHF",  # Calibrated signal is 100% SELL
                # GBPJPY — removed 2026-07-23: SELL_ONLY but SELL R=-15.99; removed from portfolio
                "NZDCAD",  # Added 2026-07-23: SELL R=+57.63 vs BUY R=-67.14 (n=201)
            }
        )
    )

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
        """Build :class:`RiskConfig` from the legacy monolithic config dict.

        Parameters
        ----------
        data
            Raw parsed YAML dict (legacy format).
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
        def _default_for_field(f: Field) -> Any:
            """Return the effective default for a dataclass field.

            ``field(default_factory=list)`` creates a field whose default
            is stored as a factory, not as a class-level attribute.
            ``getattr(SizingConfig, f.name)`` raises ``AttributeError``
            for such fields, so we resolve the default via
            ``f.default`` or ``f.default_factory``.
            """
            if f.default is not MISSING:
                return f.default
            if f.default_factory is not MISSING:
                return f.default_factory()
            return None

        sizing_kw = {
            f.name: _coerce(
                _default_for_field(f),
                defaults.get(_legacy_key(f.name), _default_for_field(f)),
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
        sell_list = defaults.get("sell_only_assets") or [
            "CADCHF",
            "NZDCHF",
            "EURAUD",
            "EURCHF",
            "GBPCHF",
            # GBPJPY — removed 2026-07-23: removed from portfolio
            "NZDCAD",
        ]
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
