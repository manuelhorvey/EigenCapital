"""ConfigRegistry — typed configuration loader and composition surface.

Phase 4 of the configuration architecture refactor. Reads the new
domain tree under ``configs/domains/<area>/*.yaml``; writes are
re-emitted to the legacy ``configs/paper_trading.yaml`` via the
``as_legacy_dict()`` helper (used by ``tools/config_migrate.py``).

Composition order: new domain files take precedence over the legacy
``paper_trading.yaml`` for keys that exist in the new tree. Keys not
yet promoted to a domain file (e.g. ``rebalance``, ``data_source``)
continue to be sourced from the legacy file. The legacy file remains
the authoritative source for the ``assets:`` block until Phase 7.

Behavior is preserved from operator-visible perspective:
``get_config()`` (paper_trading.config_manager) returns an
``EngineConfig`` populated exactly as before, because the registry
feeds back into an embedded legacy dict.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

from configs.domain_models.assets import AssetConfig, assets_from_legacy
from configs.domain_models.risk import RiskConfig

logger = logging.getLogger("eigencapital.config_registry")

REPO_ROOT = Path(__file__).resolve().parent.parent
DOMAINS_DIR = REPO_ROOT / "configs" / "domains"
LEGACY_CONFIG = REPO_ROOT / "configs" / "paper_trading.yaml"


@dataclass
class ConfigRegistry:
    """Typed layer over the configuration tree."""

    risk: RiskConfig
    assets: dict[str, AssetConfig] = field(default_factory=dict)
    # Carrier bag for keys still exclusive to the legacy YAML. Used by
    # as_legacy_dict() so operator-edits to the legacy file keep round-
    # tripping through the registry until they land in a domain file.
    legacy_extras: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def load(
        cls,
        legacy_path: Path | None = None,
        domains_dir: Path | None = None,
    ) -> ConfigRegistry:
        """Build the registry.

        Parameters
        ----------
        legacy_path
            Path to the legacy ``configs/paper_trading.yaml`` mirror.
            Defaults to the project-generated file.
        domains_dir
            Path to the new domain tree. Defaults to
            ``configs/domains``.
        """
        legacy_path = legacy_path or LEGACY_CONFIG
        domains_dir = domains_dir or DOMAINS_DIR

        legacy_raw: dict[str, Any] = {}
        if legacy_path.exists():
            legacy_raw = yaml.safe_load(legacy_path.read_text()) or {}

        # Phase 4 only loads the risk domain from the new tree when it
        # contains overrides; otherwise the legacy block is the source
        # of truth.
        risk_legacy_block = _merge_with_domain_overrides_legacy(
            legacy_raw,
            domains_dir / "risk" / "capital.yaml",
            keys=("capital", "position_size", "portfolio_drawdown_limit"),
        )
        risk_legacy_block = _merge_with_defaults_block_legacy(
            risk_legacy_block,
            domains_dir / "risk" / "sizing.yaml",
            legacy_raw.get("defaults") or {},
        )
        # Exits override
        ae_path = domains_dir / "risk" / "exits.yaml"
        if ae_path.exists():
            ae_yaml = yaml.safe_load(ae_path.read_text()) or {}
            ae_default = ae_yaml.get("default") or {}
            if ae_default:
                legacy_raw.setdefault("defaults", {}).setdefault("adaptive_exit", {}).update(ae_default)

        risk = RiskConfig.from_legacy(risk_legacy_block)

        # Per-asset still keyed off legacy block until Phase 7 lands
        assets = assets_from_legacy(legacy_raw.get("assets") or {}, risk.exits_default)

        legacy_extras = {
            k: v
            for k, v in legacy_raw.items()
            if k
            not in (
                "capital",
                "position_size",
                "portfolio_drawdown_limit",
                "halt",
                "defaults",
                "assets",
            )
        }

        return cls(risk=risk, assets=assets, legacy_extras=legacy_extras)

    def as_legacy_dict(self) -> dict[str, Any]:
        """Re-emit the legacy ``paper_trading.yaml`` shape.

        Used by tests/test_domain_loader_equivalence.py to verify that
        the registry can re-produce the legacy file byte-equal on
        well-formed inputs. Round-trip equality with the legacy file is
        the Phase 4 acceptance gate.
        """
        body: dict[str, Any] = {
            "capital": self.risk.capital.initial,
            "position_size": self.risk.capital.position_size,
            "portfolio_drawdown_limit": self.risk.capital.portfolio_drawdown_limit,
        }

        defaults: dict[str, Any] = {}
        sizing = self.risk.sizing
        for f in sizing.__dataclass_fields__:
            defaults[f] = getattr(sizing, f)

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
        return {
            "assets": len(self.assets),
            "sell_only": sorted(self.risk.sell_only.assets),
            "sizing_fields": len(self.risk.sizing.__dataclass_fields__),
            "legacy_extras": sorted(self.legacy_extras.keys()),
        }


# ── Helpers ───────────────────────────────────────────────────────────

_TKeyset = tuple[str, ...]


def _merge_with_domain_overrides_legacy(legacy: dict, domain_path: Path, keys: _TKeyset) -> dict:
    """Apply selected keys from a domain file as overrides of legacy.

    The legacy dict is treated as authoritative for non-listed keys;
    listed keys come from the domain file when it exists, otherwise
    legacy wins.
    """
    out = dict(legacy)
    if not domain_path.exists():
        return out
    domain = yaml.safe_load(domain_path.read_text()) or {}
    for k in keys:
        if k in domain:
            out[k] = domain[k]
    return out


def _merge_with_defaults_block_legacy(combined: dict, sizing_path: Path, legacy_defaults: dict) -> dict:
    """Merge per-key overrides from a sizing domain file into
    ``combined['defaults']``.

    Behavior: the legacy ``defaults.*`` block forms the base; for each
    key present in the domain file, the domain value overrides the
    legacy value.
    """
    out = dict(combined)
    base_defaults = dict(legacy_defaults)

    if sizing_path.exists():
        sizing_domain = yaml.safe_load(sizing_path.read_text()) or {}
        for k, v in sizing_domain.items():
            base_defaults[k] = v

    out["defaults"] = base_defaults
    return out
