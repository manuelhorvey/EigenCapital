"""Per-asset composition tests (Phase 7).

Validates that each per-asset YAML file (``configs/domains/assets/<NAME>.yaml``)
plus the shared ``_defaults.yaml`` composes correctly.
The legacy ``configs/paper_trading.yaml`` was deleted in Phase 12.7.
"""

from __future__ import annotations

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


def test_index_covers_22_assets():
    """_index.yaml lists all 22 live assets."""
    index = yaml.safe_load((ASSETS_DIR / "_index.yaml").read_text())
    domain_files = sorted(fn.stem for fn in ASSETS_DIR.glob("[!_]*.yaml"))
    assert sorted(index["assets"]) == domain_files
    assert len(index["assets"]) == 22


# ── Defaults coverage ─────────────────────────────────────────────


def test_defaults_block_is_a_first_class_file(defaults_yaml):
    """_defaults.yaml carries shadow_sltp/dynamic_sltp/adaptive_exit defaults."""
    for key in ("shadow_sltp", "dynamic_sltp", "adaptive_exit"):
        assert key in defaults_yaml, f"_defaults.yaml missing canonical block: {key}"


# ── Per-asset composition ───────────────────────────────────────────


@pytest.fixture(scope="module")
def _all_asset_names() -> list[str]:
    return sorted(fn.stem for fn in ASSETS_DIR.glob("[!_]*.yaml"))


@pytest.mark.parametrize(
    "name",
    sorted(fn.stem for fn in Path(__file__).resolve().parent.parent.parent.glob("configs/domains/assets/[!_]*.yaml")),
)
def test_composed_block_has_core_fields(name):
    """Each composed asset has ticker, allocation, sl_mult, tp_mult."""
    composed = _compose(name)
    for k in ("ticker", "allocation", "sl_mult", "tp_mult"):
        assert k in composed, f"{name} composed missing {k}"
    assert "config" in composed, f"{name} composed missing config block"


def test_usdcad_preserved_through_compose():
    composed = _compose("USDCAD")
    assert composed["spread_tier"] == "fx_major"
    assert composed["max_depth"] == 3
    assert composed["tp_mult"] == 3.9
    assert composed["sl_mult"] == 1.3


def test_btcusd_preserves_weekend_flag():
    composed = _compose("BTCUSD")
    assert composed["max_entry_slippage_pct"] == 5.0
    raw = yaml.safe_load((ASSETS_DIR / "BTCUSD.yaml").read_text())
    assert raw.get("weekend_eligible") is True
    assert raw.get("weekend_allocation_multiplier") == 0.5


def test_defaults_yaml_adaptive_exit_matches_known_default():
    defaults = yaml.safe_load(DEFAULTS_YAML.read_text())["adaptive_exit"]
    assert defaults["trail_activation_r"] == 0.8
    assert defaults["trail_retrace_pct"] == 0.33
    assert defaults["enabled"] is True
    assert defaults.get("mfe_ratio_tighten", {}).get("enabled") is True


def test_mfe_ratio_tighten_flows_from_defaults_to_per_asset():
    """Per-asset files without mfe_ratio_tighten inherit from defaults."""
    composed = _compose("EURNZD")
    mfe = composed["config"]["adaptive_exit"]["mfe_ratio_tighten"]
    assert mfe["enabled"] is True
    assert mfe["ratio_thresholds"] == [[1.5, 0.85], [2.0, 0.7], [3.0, 0.5]]


def test_mfe_ratio_tighten_2x_default():
    """At MFE/SL ratio 2.0 (1.56R peak / 1.0R SL dist), retrace tightens."""
    from paper_trading.position.adaptive_exit import AdaptiveExitEngine

    engine = AdaptiveExitEngine()
    engine._breakeven_activated = True
    # peak_r = 2.0  (mfe_sl_ratio = 2.0 / 1.0 = 2.0)
    engine._best_price = 104.0
    cfg = {
        "trail_activation_r": 0.5,
        "trail_retrace_pct": 0.33,
        "mfe_ratio_tighten": {"enabled": True, "ratio_thresholds": [[2.0, 0.7]]},
    }
    result = engine.compute(
        side="long",
        entry_price=100,
        current_price=101,
        current_sl=100,
        vol_at_entry=0.02,
        bars_since_entry=5,
        config=cfg,
    )
    # effective_retrace = 0.33 * 0.70 = 0.231
    # retrace_level = 104 - 0.231 * 4 = 103.076
    assert result.action == "trail"
    assert result.new_sl == pytest.approx(103.076, abs=0.01)
    assert "mfe_ratio_tighten=0.7" in result.description


def test_per_asset_adaptive_exit_overrides_apply():
    """NZDUSD has trail_activation_r: 0.5 while default is 0.8."""
    raw = yaml.safe_load((ASSETS_DIR / "NZDUSD.yaml").read_text())
    assert raw.get("adaptive_exit", {}).get("trail_activation_r") == 0.5


def test_per_asset_adaptive_exit_defaults_match_when_absent():
    """USDCAD has adaptive_exit set to false — override applied."""
    raw = yaml.safe_load((ASSETS_DIR / "USDCAD.yaml").read_text())
    ae = raw.get("adaptive_exit", {})
    assert ae.get("enabled") is False, "USDCAD adaptive_exit should be disabled"


def test_no_per_asset_file_adapts_to_defaults():
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


def test_assets_per_file_count_matches():
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
