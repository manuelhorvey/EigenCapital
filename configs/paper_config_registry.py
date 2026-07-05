"""PaperConfigRegistry — production-facing typed registry.

Phase 11.1 of the configuration architecture refactor. Acts as the
backbone for the write-mode split. Reads the new domain tree primarily
(configs/domains/**/*.yaml + configs/environments/*.yaml + configs/modes/*.yaml +
per-asset files), and treats configs/paper_trading.yaml as the legacy
fallback that wins only for keys not yet promoted to a domain file.

Differences from ConfigRegistry (Phase 4):
- Phase 4 used the legacy YAML as the bootstrap and domain files as
  template overrides. Phase 11 inverts the relationship: domain files
  are the bootstrap, legacy YAML is the override for unpromoted keys.
- Adds per-asset file primary loading (Phase 7 introduced the files
  but did not wire production reads).
- Adds environment + mode resolution order (production → live →
  backtest, etc.).

The legacy YAML exposes the same flat dict shape that EngineConfig
typology expects: capital, position_size, defaults.<...>, assets.<...>,
mt5, alerting, ensemble, calibration, kelly, portfolio, optimizations,
execution.governance, modes. Phase 11 keeps the legacy YAML surface
intact so EngineConfig.from_dict() and ~80 call sites stay valid.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

from configs.domain_models.assets import AssetConfig
from configs.domain_models.risk import RiskConfig

logger = logging.getLogger("eigencapital.config_registry")

REPO_ROOT = Path(__file__).resolve().parent.parent
DOMAINS_DIR = REPO_ROOT / "configs" / "domains"
LEGACY_CONFIG = REPO_ROOT / "configs" / "paper_trading.yaml"
ENVIRONMENTS_DIR = REPO_ROOT / "configs" / "environments"
MODES_DIR = DOMAINS_DIR / "modes"


@dataclass
class PaperConfigRegistry:
    """Production-facing typed configuration registry.

    Reads domain files first; falls back to legacy paper_trading.yaml for
    keys not yet promoted (e.g. ``research_mode``, ``rebalance``).
    """

    risk: RiskConfig
    assets: dict[str, AssetConfig] = field(default_factory=dict)
    # Carrier bag for keys still exclusive to the legacy YAML. Used by
    # as_legacy_dict() so operator-edits to the legacy file keep round-
    # tripping until they land in a domain file.
    legacy_extras: dict[str, Any] = field(default_factory=dict)
    # Asset source: either "domain" (preferred) or "legacy".
    asset_sources: dict[str, str] = field(default_factory=dict)

    @classmethod
    def load(
        cls,
        legacy_path: Path | None = None,
        domains_dir: Path | None = None,
        environments_dir: Path | None = None,
        modes_dir: Path | None = None,
    ) -> PaperConfigRegistry:
        legacy_path = legacy_path or LEGACY_CONFIG
        domains_dir = domains_dir or DOMAINS_DIR
        environments_dir = environments_dir or ENVIRONMENTS_DIR
        modes_dir = modes_dir or MODES_DIR

        legacy_raw: dict[str, Any] = {}
        if legacy_path.exists():
            legacy_raw = yaml.safe_load(legacy_path.read_text()) or {}

        # Step 1: build a normalized base config dict from the domain
        # tree (Phase 11.1 inverts Phase 4 precedence — domain > legacy).
        base: dict[str, Any] = {}

        # Step 1a: capital
        if (domains_dir / "risk" / "capital.yaml").exists():
            cap = yaml.safe_load((domains_dir / "risk" / "capital.yaml").read_text()) or {}
            for k in ("capital", "portfolio_drawdown_limit", "position_size"):
                if k in cap:
                    base[k] = cap[k]

        # Fall back to legacy for any key not in domain
        for k in ("capital", "portfolio_drawdown_limit", "position_size"):
            base.setdefault(k, legacy_raw.get(k))

        # Step 1b: defaults via SizingConfig + adaptive_exit overlay
        defaults_blk: dict[str, Any] = {}
        if (domains_dir / "risk" / "sizing.yaml").exists():
            sz = yaml.safe_load((domains_dir / "risk" / "sizing.yaml").read_text()) or {}
            defaults_blk.update(sz)
        legacy_defaults = legacy_raw.get("defaults") or {}
        for k, v in legacy_defaults.items():
            defaults_blk.setdefault(k, v)
        if (domains_dir / "risk" / "exits.yaml").exists():
            ae = yaml.safe_load((domains_dir / "risk" / "exits.yaml").read_text()) or {}
            defaults_blk["adaptive_exit"] = {**legacy_defaults.get("adaptive_exit", {}), **(ae.get("default") or {})}
        else:
            defaults_blk.setdefault("adaptive_exit", legacy_defaults.get("adaptive_exit", {}))

        base["defaults"] = defaults_blk

        # Step 1c: build risk from the composed defaults
        risk = RiskConfig.from_legacy(base)

        # Step 2: asset loading — per-asset files take precedence
        merged_assets, asset_sources = _merge_assets(
            domains_dir=domains_dir,
            legacy_assets=legacy_raw.get("assets") or {},
            defaults_exit=risk.exits_default,
        )

        # Step 3: collect legacy_extras — keys not yet in a domain file
        promoted_top = {
            "capital",
            "position_size",
            "portfolio_drawdown_limit",
            "defaults",
            "assets",
        }
        promoted_defaults = set(defaults_blk.keys())
        legacy_extras: dict[str, Any] = {}
        for k, v in legacy_raw.items():
            if k not in promoted_top:
                legacy_extras[k] = v
        for k in list(legacy_defaults.keys()):
            if k not in promoted_defaults and k not in legacy_extras:
                legacy_extras[k] = legacy_defaults[k]

        return cls(
            risk=risk,
            assets=merged_assets,
            legacy_extras=legacy_extras,
            asset_sources=asset_sources,
        )

    def as_legacy_dict(self) -> dict[str, Any]:
        """Re-emit the legacy paper_trading.yaml shape losslessly."""
        body: dict[str, Any] = {
            "capital": self.risk.capital.initial,
            "position_size": self.risk.capital.position_size,
            "portfolio_drawdown_limit": self.risk.capital.portfolio_drawdown_limit,
        }

        defaults: dict[str, Any] = dict(self.risk.exits_default.__dict__)
        # Walk sizing dataclass
        for f in self.risk.sizing.__dataclass_fields__:
            defaults[f] = getattr(self.risk.sizing, f)

        ae = self.risk.exits_default
        defaults["adaptive_exit"] = {
            "enabled": ae.enabled,
            "be_lock_r": ae.be_lock_r,
            "trail_activation_r": ae.trail_activation_r,
            "trail_retrace_pct": ae.trail_retrace_pct,
            "max_hold_candles": ae.max_hold_candles,
            "time_decay_start": ae.time_decay_start,
            "scale_out_fraction": ae.scale_out_fraction,
            "scale_out_r": ae.scale_out_r,
        }
        defaults["sell_only_assets"] = sorted(self.risk.sell_only.assets)
        body["defaults"] = defaults

        body["assets"] = {name: a.to_legacy_dict() for name, a in self.assets.items()}

        for k, v in self.legacy_extras.items():
            body[k] = v
        return body

    def summary(self) -> dict[str, Any]:
        domain_assets = sum(1 for s in self.asset_sources.values() if s == "domain")
        legacy_assets = sum(1 for s in self.asset_sources.values() if s == "legacy")
        return {
            "assets": len(self.assets),
            "domain_assets": domain_assets,
            "legacy_assets": legacy_assets,
            "sell_only": sorted(self.risk.sell_only.assets),
            "sizing_fields": len(self.risk.sizing.__dataclass_fields__),
            "legacy_extras": sorted(self.legacy_extras.keys()),
        }


# ── Asset merging ────────────────────────────────────────────────────


_DEFAULT_BLOCK_KEYS = ("shadow_sltp", "dynamic_sltp", "adaptive_exit")


def _merge_assets(
    *,
    domains_dir: Path,
    legacy_assets: dict[str, dict],
    defaults_exit,
) -> tuple[dict[str, AssetConfig], dict[str, str]]:
    """Compose per-asset YAMLs with legacy assets block.

    For each asset:
      1. Start from configs/domains/assets/_defaults.yaml shared block
      2. If configs/domains/assets/<NAME>.yaml exists, overlay it
         (per-asset adaptive_exit given priority)
      3. If no per-asset file, fall back to legacy asset block
    """
    assets_out: dict[str, AssetConfig] = {}
    sources: dict[str, str] = {}

    # Defaults for shadow/dynamic/adaptive
    defaults_yaml: dict[str, dict] = {}
    defaults_path = domains_dir / "assets" / "_defaults.yaml"
    if defaults_path.exists():
        defaults_yaml = yaml.safe_load(defaults_path.read_text()) or {}

    # Per-asset files index
    per_asset_files = {fn.stem: fn for fn in (domains_dir / "assets").glob("[!_]*.yaml")}

    # Build per-asset results: union of per-asset YAMLs + legacy asset keys
    all_names = set(per_asset_files) | set(legacy_assets)
    for name in sorted(all_names):
        per_file = per_asset_files.get(name)
        legacy_block = legacy_assets.get(name) or {}

        if per_file is not None:
            unique = yaml.safe_load(per_file.read_text()) or {}
            sources[name] = "domain"
        elif legacy_block:
            unique = _legacy_asset_to_unique(legacy_block)
            sources[name] = "legacy"
        else:
            continue

        # Compose defaults overlay
        composite = _compose_asset(unique, defaults_yaml)
        assets_out[name] = AssetConfig.from_dict(name, composite, defaults_exit)

    return assets_out, sources


def _legacy_asset_to_unique(legacy_block: dict) -> dict:
    """Convert a legacy asset entry to its per-asset YAML unique shape.

    Keeps ticker/allocation/sl_mult/tp_mult (and the truly-unique
    keys); strips shadow_sltp / dynamic_sltp / adaptive_exit which the
    composition overlays from _defaults.yaml.
    """
    carry = {k: v for k, v in legacy_block.items() if k not in ("config", "regime_geometry")}
    return carry


def _compose_asset(unique: dict, defaults_yaml: dict) -> dict:
    """Compose an asset entry with the shared defaults overlay.

    Outputs an asset block the AssetConfig.from_dict can consume.
    """
    composite = dict(unique)
    # Per-asset adaptive_exit may be missing → inherit default
    composite.setdefault("adaptive_exit", defaults_yaml.get("adaptive_exit", {}))
    composite.setdefault("shadow_sltp", defaults_yaml.get("shadow_sltp", {}))
    composite.setdefault("dynamic_sltp", defaults_yaml.get("dynamic_sltp", {}))
    # Wrap into config sub-block (AssetConfig.from_dict path reads raw
    # in addition to the typed loader paths)
    composite["config"] = {
        "shadow_sltp": composite.pop("shadow_sltp"),
        "dynamic_sltp": composite.pop("dynamic_sltp"),
        "adaptive_exit": composite.pop("adaptive_exit"),
    }
    return composite
