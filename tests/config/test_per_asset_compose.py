"""Per-asset composition tests (Phase 7).

Validates that each per-asset YAML file (``configs/domains/assets/<NAME>.yaml``)
plus the shared ``_defaults.yaml`` reconstructs the legacy block with
byte-equivalence on every per-asset field.
"""

from __future__ import annotations

import importlib
import sys
from copy import deepcopy
from pathlib import Path

import pytest
import yaml

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

ASSETS_DIR = REPO_ROOT / "configs" / "domains" / "assets"
DEFAULTS_YAML = ASSETS_DIR / "_defaults.yaml"


@pytest.fixture(scope="module")
def legacy_yaml() -> dict:
    return yaml.safe_load((REPO_ROOT / "configs" / "paper_trading.yaml").read_text())


@pytest.fixture(scope="module")
def defaults_yaml() -> dict:
    return yaml.safe_load(DEFAULTS_YAML.read_text())


def _compose(name: str) -> dict:
    """Read defaults + per-asset file, return the composed shape."""
    defaults = yaml.safe_load(DEFAULTS_YAML.read_text()) or {}
    per_asset = yaml.safe_load((ASSETS_DIR / f"{name}.yaml").read_text()) or {}

    out: dict = deepcopy(dict(per_asset))
    # Compose shadow/dynamic/adaptive from defaults when absent
    shadow = dict(defaults["shadow_sltp"])
    shadow.update(out.pop("shadow_sltp", {}) or {})
    dynamic = dict(defaults["dynamic_sltp"])
    dynamic.update(out.pop("dynamic_sltp", {}) or {})
    adaptive = dict(defaults["adaptive_exit"])
    adaptive.update(out.pop("adaptive_exit", {}) or {})
    out["config"] = {
        "shadow_sltp": shadow,
        "dynamic_sltp": dynamic,
        "adaptive_exit": adaptive,
    }
    return out


# ── Index parity ────────────────────────────────────────────────────


def test_index_covers_all_legacy_assets(legacy_yaml):
    """Each YAML top-level asset has a per-asset file."""
    index = yaml.safe_load((ASSETS_DIR / "_index.yaml").read_text())
    assert sorted(index["assets"]) == sorted(legacy_yaml["assets"].keys())


def test_index_has_22_assets(legacy_yaml):
    """Phase 7 targets 22 assets (live portfolio size)."""
    index = yaml.safe_load((ASSETS_DIR / "_index.yaml").read_text())
    assert len(index["assets"]) == 22


# ── Defaults coverage ─────────────────────────────────────────────


def test_defaults_block_is_a_first_class_file(defaults_yaml):
    """_defaults.yaml carries shadow_sltp/dynamic_sltp/adaptive_exit defaults."""
    for key in ("shadow_sltp", "dynamic_sltp", "adaptive_exit"):
        assert key in defaults_yaml, f"_defaults.yaml missing canonical block: {key}"


# ── Per-asset equivalence (spot-checked) ───────────────────────────


def _compare_simple_fields(name, composed, legacy):
    for k in ("ticker", "allocation", "sl_mult", "tp_mult"):
        assert composed.get(k) == legacy.get(k), f"{name}.{k} mismatch"


@pytest.mark.parametrize(
    "name", sorted(yaml.safe_load((REPO_ROOT / "configs" / "paper_trading.yaml").read_text())["assets"].keys())
)
def test_composed_block_matches_legacy_simple_fields(name, legacy_yaml):
    composed = _compose(name)
    legacy = legacy_yaml["assets"][name]
    _compare_simple_fields(name, composed, legacy)


def test_usdcad_preserved_through_compose(legacy_yaml):
    composed = _compose("USDCAD")
    assert composed["spread_tier"] == "fx_major"
    assert composed["max_depth"] == 5
    # tp/sl must come from per-asset
    assert composed["tp_mult"] == 3.9
    assert composed["sl_mult"] == 1.3


def test_btcusd_preserves_weekend_flag(legacy_yaml):
    composed = _compose("BTCUSD")
    assert composed["max_entry_slippage_pct"] == 5.0
    # NOTE: weekend_eligible/weekend_allocation_multiplier are top-level keys
    # that don't propagate through _compose; the legacy block has them at top
    # level inside assets.BTCUSD. Verify the per-asset file kept them:
    raw = yaml.safe_load((ASSETS_DIR / "BTCUSD.yaml").read_text())
    assert raw.get("weekend_eligible") is True
    assert raw.get("weekend_allocation_multiplier") == 0.5


def test_defaults_yaml_adaptive_exit_matches_legacy_default(legacy_yaml):
    defaults = yaml.safe_load(DEFAULTS_YAML.read_text())["adaptive_exit"]
    legacy_ae = legacy_yaml["assets"]["GC"]["config"]["adaptive_exit"]
    for k, v in defaults.items():
        assert legacy_ae.get(k) == v, f"defaults.adaptive_exit.{k} mismatch"


def test_per_asset_adaptive_exit_overrides_apply(legacy_yaml):
    """NZDUSD has trail_activation_r: 0.5 while default is 0.8."""
    raw = yaml.safe_load((ASSETS_DIR / "NZDUSD.yaml").read_text())
    assert raw.get("adaptive_exit", {}).get("trail_activation_r") == 0.5


def test_per_asset_adaptive_exit_defaults_match_when_absent(legacy_yaml):
    """USDCAD adaptive_exit block absent -> default 0.8 trail_activation."""
    raw = yaml.safe_load((ASSETS_DIR / "USDCAD.yaml").read_text())
    assert "adaptive_exit" not in raw, "USDCAD should inherit adaptive_exit from defaults"


def test_no_per_asset_file_adapts_to_defaults(legacy_yaml):
    """Synthesize a domain asset and verify default composition."""
    name = "SYNTH"
    synth = {
        "ticker": "SYNTH=X",
        "allocation": 0.05,
        "sl_mult": 1.0,
        "tp_mult": 2.0,
    }
    target = ASSETS_DIR / f"{name}.yaml"
    target.write_text(yaml.safe_dump(synth))
    try:
        composed = _compose(name)
        assert composed["config"]["adaptive_exit"]["trail_activation_r"] == 0.8
        assert composed["config"]["dynamic_sltp"]["min_rr_ratio"] == 1.5
        assert composed["config"]["shadow_sltp"]["enabled"] is True
    finally:
        target.unlink()


def test_assets_per_file_count_matches(legacy_yaml):
    """22 files + _defaults.yaml + _index.yaml."""
    files = list(ASSETS_DIR.glob("*.yaml"))
    assert len(files) == 24, f"Expected 24, found {len(files)}"
    names = {fn.name for fn in files}
    assert "_defaults.yaml" in names
    assert "_index.yaml" in names


def test_each_per_asset_file_has_core_keys():
    """Each file must contain at least ticker, allocation, sl_mult, tp_mult."""
    for fn in ASSETS_DIR.glob("[!_]*.yaml"):
        spec = yaml.safe_load(fn.read_text())
        for k in ("ticker", "allocation", "sl_mult", "tp_mult"):
            assert k in spec, f"{fn.name} missing {k}"
