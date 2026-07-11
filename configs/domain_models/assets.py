"""Per-asset typed configuration model.

Phase 3: reads from configs/domains/assets/<NAME>.yaml + shared bundle.
The loading provider lives in :mod:`configs.paper_config_registry`
(Phase 11); here we only declare the typed contract.

The model intentionally defines **only** the per-asset unique surface
plus composed sub-structures (``regime_geometry`` / ``adaptive_exit`` /
``shadow_sltp`` / ``dynamic_sltp``). Anything else stays as raw dict
interim until the corresponding domain model is promoted.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from configs.domain_models.risk import ExitConfig


@dataclass(frozen=True)
class RegimeBand:
    """One band (GREEN/YELLOW/RED) of an asset's regime-geometry block."""

    sl_mult: float = 1.0
    tp_mult: float = 1.0


@dataclass(frozen=True)
class RegimeGeometry:
    """3-color regime sensitivity multipliers.

    All three bands default to the legacy ``(1.0, 1.0)`` multiplier
    because the global ``execution.governance.regime_geometry`` block
    in the YAML uses the identity multiplier. Per-asset overrides are
    captured here when they deviate from that global pattern.
    """

    green: RegimeBand = field(default_factory=RegimeBand)
    yellow: RegimeBand = field(default_factory=RegimeBand)
    red: RegimeBand = field(default_factory=RegimeBand)

    @classmethod
    def from_dict(cls, raw: dict | None) -> RegimeGeometry:
        if not raw:
            return cls()
        return cls(
            green=RegimeBand(
                sl_mult=float((raw.get("GREEN") or {}).get("sl_mult", 1.0)),
                tp_mult=float((raw.get("GREEN") or {}).get("tp_mult", 1.0)),
            ),
            yellow=RegimeBand(
                sl_mult=float((raw.get("YELLOW") or {}).get("sl_mult", 1.0)),
                tp_mult=float((raw.get("YELLOW") or {}).get("tp_mult", 1.0)),
            ),
            red=RegimeBand(
                sl_mult=float((raw.get("RED") or {}).get("sl_mult", 1.0)),
                tp_mult=float((raw.get("RED") or {}).get("tp_mult", 1.0)),
            ),
        )

    def to_legacy_dict(self) -> dict:
        return {
            "GREEN": {"sl_mult": self.green.sl_mult, "tp_mult": self.green.tp_mult},
            "YELLOW": {"sl_mult": self.yellow.sl_mult, "tp_mult": self.yellow.tp_mult},
            "RED": {"sl_mult": self.red.sl_mult, "tp_mult": self.red.tp_mult},
        }


@dataclass(frozen=True)
class ShadowSLTPConfig:
    """Live-but-documented shadow-SL/TP engine config (paper-only)."""

    enabled: bool = True
    method: str = "trailing"
    trailing_activation_mult: float = 1.0
    trailing_distance_mult: float = 1.0
    atr_period: int = 14

    @classmethod
    def from_dict(cls, raw: dict | None) -> ShadowSLTPConfig:
        if not raw:
            return cls()
        return cls(
            enabled=bool(raw.get("enabled", True)),
            method=str(raw.get("method", "trailing")),
            trailing_activation_mult=float(raw.get("trailing_activation_mult", 1.0)),
            trailing_distance_mult=float(raw.get("trailing_distance_mult", 1.0)),
            atr_period=int(raw.get("atr_period", 14)),
        )


@dataclass(frozen=True)
class DynamicSLTPConfig:
    """Live-but-documented dynamic SL/TP engine config."""

    enabled: bool = True
    method: str = "trailing"
    trailing_activation_mult: float = 1.0
    trailing_distance_mult: float = 1.0
    min_rr_ratio: float = 1.5

    @classmethod
    def from_dict(cls, raw: dict | None) -> DynamicSLTPConfig:
        if not raw:
            return cls()
        return cls(
            enabled=bool(raw.get("enabled", True)),
            method=str(raw.get("method", "trailing")),
            trailing_activation_mult=float(raw.get("trailing_activation_mult", 1.0)),
            trailing_distance_mult=float(raw.get("trailing_distance_mult", 1.0)),
            min_rr_ratio=float(raw.get("min_rr_ratio", 1.5)),
        )


@dataclass(frozen=True)
class AssetConfig:
    """Per-asset catalog entry covering live-trade dimensions only.

    Notes
    -----
    The Phase 7 split moves each asset block to its own
    ``configs/domains/assets/<NAME>.yaml`` file. The legacy YAML
    carried ~30 keys per asset block; ~25 of them were duplicated
    boilerplate that this model promotes to typed defaults.
    """

    name: str
    """Short asset name (YAML key, e.g. ``USDCAD``)."""

    ticker: str
    """Raw ticker used by feature pipelines (e.g. ``USDCAD=X``)."""

    allocation: float
    sl_mult: float
    tp_mult: float
    spread_tier: str | None = None
    max_depth: int | None = None
    min_confidence: float | None = None
    min_confidence_buy: float | None = None
    """Direction-conditional override: lower threshold for BUY signals.

    Per-asset override of the global ``defaults.min_confidence_buy``.
    When set, applies only to BUY/LONG signals; SELL signals still use
    ``min_confidence_sell`` or the global default.
    """
    min_confidence_sell: float | None = None
    """Direction-conditional override: threshold for SELL signals."""
    max_entry_slippage_pct: float | None = None
    max_positions_per_asset: int | None = None
    weekend_eligible: bool = False
    weekend_allocation_multiplier: float = 0.5
    regime_geometry: RegimeGeometry = field(default_factory=RegimeGeometry)
    adaptive_exit: ExitConfig = field(default_factory=ExitConfig)
    shadow_sltp: ShadowSLTPConfig = field(default_factory=ShadowSLTPConfig)
    dynamic_sltp: DynamicSLTPConfig = field(default_factory=DynamicSLTPConfig)
    # Carrier bag for keys that have not yet been promoted to typed fields
    extras: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_dict(cls, name: str, raw: dict, defaults_exit: ExitConfig) -> AssetConfig:
        cfg = raw.get("config") or {}
        ae = dict(defaults_exit.__dict__)  # start from default
        ae.update(cfg.get("adaptive_exit") or {})  # overlay per-asset
        adaptive = ExitConfig(
            enabled=bool(ae.get("enabled", True)),
            be_lock_r=float(ae.get("be_lock_r", getattr(defaults_exit, "be_lock_r"))),
            trail_activation_r=float(ae.get("trail_activation_r", getattr(defaults_exit, "trail_activation_r"))),
            trail_retrace_pct=float(ae.get("trail_retrace_pct", getattr(defaults_exit, "trail_retrace_pct"))),
            max_hold_candles=int(ae.get("max_hold_candles", getattr(defaults_exit, "max_hold_candles"))),
            time_decay_start=int(ae.get("time_decay_start", getattr(defaults_exit, "time_decay_start"))),
            scale_out_fraction=float(ae.get("scale_out_fraction", getattr(defaults_exit, "scale_out_fraction"))),
            scale_out_r=float(ae.get("scale_out_r", getattr(defaults_exit, "scale_out_r"))),
        )

        # Tag carriers that have not been promoted yet.
        known_typed = {
            "ticker",
            "allocation",
            "sl_mult",
            "tp_mult",
            "spread_tier",
            "max_depth",
            "min_confidence",
            "min_confidence_buy",
            "min_confidence_sell",
            "max_entry_slippage_pct",
            "max_positions_per_asset",
            "weekend_eligible",
            "weekend_allocation_multiplier",
            "regime_geometry",
            "config",
        }
        extras = {k: v for k, v in raw.items() if k not in known_typed and not isinstance(v, (dict, list))}

        return cls(
            name=name,
            ticker=str(raw.get("ticker", name)),
            allocation=float(raw.get("allocation", 0.0)),
            sl_mult=float(raw.get("sl_mult", 1.0)),
            tp_mult=float(raw.get("tp_mult", 1.0)),
            spread_tier=raw.get("spread_tier"),
            max_depth=raw.get("max_depth"),
            min_confidence=raw.get("min_confidence"),
            max_entry_slippage_pct=raw.get("max_entry_slippage_pct"),
            max_positions_per_asset=raw.get("max_positions_per_asset"),
            min_confidence_buy=raw.get("min_confidence_buy"),
            min_confidence_sell=raw.get("min_confidence_sell"),
            weekend_eligible=bool(raw.get("weekend_eligible", False)),
            weekend_allocation_multiplier=float(raw.get("weekend_allocation_multiplier", 0.5)),
            regime_geometry=RegimeGeometry.from_dict(raw.get("regime_geometry")),
            adaptive_exit=adaptive,
            shadow_sltp=ShadowSLTPConfig.from_dict(cfg.get("shadow_sltp")),
            dynamic_sltp=DynamicSLTPConfig.from_dict(cfg.get("dynamic_sltp")),
            extras=extras,
        )

    def to_legacy_dict(self) -> dict:
        """Re-serialize to the legacy per-asset block shape.

        Used by the Phase 4 mirror to re-emit legacy ``paper_trading.yaml``
        after editing domain files. Verifies round-trip equivalence with
        the original row through tests/test_domain_loader_equivalence.py.
        """
        body: dict[str, Any] = {
            "ticker": self.ticker,
            "allocation": self.allocation,
            "sl_mult": self.sl_mult,
            "tp_mult": self.tp_mult,
        }
        if self.spread_tier is not None:
            body["spread_tier"] = self.spread_tier
        if self.max_depth is not None:
            body["max_depth"] = self.max_depth
        if self.min_confidence is not None:
            body["min_confidence"] = self.min_confidence
        if self.min_confidence_buy is not None:
            body["min_confidence_buy"] = self.min_confidence_buy
        if self.min_confidence_sell is not None:
            body["min_confidence_sell"] = self.min_confidence_sell
        if self.max_entry_slippage_pct is not None:
            body["max_entry_slippage_pct"] = self.max_entry_slippage_pct
        if self.max_positions_per_asset is not None:
            body["max_positions_per_asset"] = self.max_positions_per_asset
        if self.weekend_eligible:
            body["weekend_eligible"] = True
            body["weekend_allocation_multiplier"] = self.weekend_allocation_multiplier

        geometry = self.regime_geometry.to_legacy_dict()
        body["regime_geometry"] = geometry

        body["config"] = {
            "shadow_sltp": {
                "enabled": self.shadow_sltp.enabled,
                "method": self.shadow_sltp.method,
                "trailing_activation_mult": self.shadow_sltp.trailing_activation_mult,
                "trailing_distance_mult": self.shadow_sltp.trailing_distance_mult,
                "atr_period": self.shadow_sltp.atr_period,
            }
            if self.shadow_sltp.atr_period != 14
            else {
                "enabled": self.shadow_sltp.enabled,
                "method": self.shadow_sltp.method,
                "trailing_activation_mult": self.shadow_sltp.trailing_activation_mult,
                "trailing_distance_mult": self.shadow_sltp.trailing_distance_mult,
            },
            "dynamic_sltp": {
                "enabled": self.dynamic_sltp.enabled,
                "method": self.dynamic_sltp.method,
                "trailing_activation_mult": self.dynamic_sltp.trailing_activation_mult,
                "trailing_distance_mult": self.dynamic_sltp.trailing_distance_mult,
                "min_rr_ratio": self.dynamic_sltp.min_rr_ratio,
            },
            "adaptive_exit": {
                "enabled": self.adaptive_exit.enabled,
                "be_lock_r": self.adaptive_exit.be_lock_r,
                "trail_activation_r": self.adaptive_exit.trail_activation_r,
                "trail_retrace_pct": self.adaptive_exit.trail_retrace_pct,
                "max_hold_candles": self.adaptive_exit.max_hold_candles,
                "time_decay_start": self.adaptive_exit.time_decay_start,
            },
        }
        body.update(self.extras)
        return body


def assets_from_legacy(
    assets_block: dict[str, dict],
    defaults_exit: ExitConfig,
) -> dict[str, AssetConfig]:
    """Bulk-load all assets from the legacy ``assets:`` block."""
    out: dict[str, AssetConfig] = {}
    for name, raw in assets_block.items():
        out[name] = AssetConfig.from_dict(name, raw or {}, defaults_exit)
    return out
