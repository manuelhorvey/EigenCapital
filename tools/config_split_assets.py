"""
config_split_assets.py — per-asset YAML splitter.

Reads the assets block from PaperConfigRegistry (domain-first) and
writes one YAML file per asset to configs/domains/assets/<NAME>.yaml.
Also writes configs/domains/assets/_defaults.yaml with shared values.

The legacy ``configs/paper_trading.yaml`` was deleted in Phase 12.7;
this tool reads from the registry instead.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import yaml

REPO_ROOT = Path(__file__).resolve().parent.parent
ASSETS_DIR = REPO_ROOT / "configs" / "domains" / "assets"


def _load_assets_from_registry() -> dict:
    """Load the assets block from PaperConfigRegistry.as_legacy_dict()."""
    sys.path.insert(0, str(REPO_ROOT))
    from configs.paper_config_registry import PaperConfigRegistry

    reg = PaperConfigRegistry.load()
    return reg.as_legacy_dict().get("assets") or {}


def split(legacy_path: Path | None = None, assets_dir: Path = ASSETS_DIR) -> int:
    if legacy_path and legacy_path.exists():
        data = yaml.safe_load(legacy_path.read_text()) or {}
        assets = data.get("assets") or {}
    else:
        assets = _load_assets_from_registry()
    if not assets:
        print(f"splitsplit: no assets block in {legacy_path}")
        return 1

    assets_dir.mkdir(parents=True, exist_ok=True)

    # Compute the shape that IS shared across all assets and was mass-
    # duplicated in the legacy block. This becomes _defaults.yaml.
    if assets:
        default_spec = {
            "shadow_sltp": {
                "enabled": True,
                "method": "trailing",
                "trailing_activation_mult": 1.0,
                "trailing_distance_mult": 1.0,
            },
            "dynamic_sltp": {
                "enabled": True,
                "method": "trailing",
                "trailing_activation_mult": 1.0,
                "trailing_distance_mult": 1.0,
                "min_rr_ratio": 1.5,
            },
            "adaptive_exit": {
                "enabled": True,
                "be_lock_r": 0.5,
                "trail_activation_r": 0.8,
                "trail_retrace_pct": 0.33,
                "max_hold_candles": 40,
                "time_decay_start": 20,
            },
        }
        (assets_dir / "_defaults.yaml").write_text(yaml.safe_dump(default_spec, sort_keys=False))

    # Write per-asset files containing only unique config
    for name, raw in assets.items():
        target = assets_dir / f"{name}.yaml"
        # Extract only the truly-unique keys (the asset_name key itself is
        # implicit, and the config sub-block keeps only what's diverse).
        unique_spec: dict = {
            "ticker": raw["ticker"],
            "allocation": raw["allocation"],
            "sl_mult": raw["sl_mult"],
            "tp_mult": raw["tp_mult"],
        }
        for k in (
            "spread_tier",
            "max_depth",
            "min_confidence",
            "max_entry_slippage_pct",
            "max_positions_per_asset",
            "weekend_eligible",
            "weekend_allocation_multiplier",
        ):
            if k in raw:
                unique_spec[k] = raw[k]

        # Regime geometry is unique per asset when the values deviate
        # from the identity (1.0, 1.0) for any band. We emit the full
        # block since some assets partial-deviate.
        if raw.get("regime_geometry"):
            unique_spec["regime_geometry"] = raw["regime_geometry"]

        # Per-asset adaptive_exit: emit only when deviating from default
        ae = (raw.get("config") or {}).get("adaptive_exit") or {}
        if ae and any(ae.get(k) != v for k, v in default_spec["adaptive_exit"].items()):
            unique_spec["adaptive_exit"] = ae

        target.write_text(yaml.safe_dump(unique_spec, sort_keys=False))

    print(f"splitsplit: wrote {len(assets)} per-asset files + _defaults.yaml to {assets_dir}")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--legacy", type=Path, default=None,
                        help="Optional legacy YAML path (default: registry)")
    parser.add_argument("--output", type=Path, default=ASSETS_DIR)
    args = parser.parse_args()

    return split(args.legacy, args.output)


if __name__ == "__main__":
    sys.exit(main())
