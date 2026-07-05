"""tests for tools/config_mirror_legacy.py — Phase 11.3."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest
import yaml

REPO_ROOT = Path(__file__).resolve().parents[2]
LEGACY_PATH = REPO_ROOT / "configs" / "paper_trading.yaml"


def _make_legacy_file(path: Path) -> dict:
    """Generate a synthetic legacy YAML file from PaperConfigRegistry."""
    sys.path.insert(0, str(REPO_ROOT))
    from configs.paper_config_registry import PaperConfigRegistry

    reg = PaperConfigRegistry.load()
    data = reg.as_legacy_dict()
    path.write_text(yaml.safe_dump(data, sort_keys=False))
    return data


@pytest.fixture
def restored_legacy(tmp_path):
    """Create a synthetic legacy YAML file from the registry."""
    path = tmp_path / "paper_trading.yaml"
    _make_legacy_file(path)
    return path


def test_render_legacy_yaml_returns_string(restored_legacy):
    sys.path.insert(0, str(REPO_ROOT))
    from tools.config_mirror_legacy import render_legacy_yaml

    out = render_legacy_yaml(restored_legacy)
    assert isinstance(out, str)
    parsed = yaml.safe_load(out)
    assert isinstance(parsed, dict)
    assert "capital" in parsed
    assert "defaults" in parsed
    assert "assets" in parsed


def test_render_legacy_yaml_yields_registered_assets(restored_legacy):
    sys.path.insert(0, str(REPO_ROOT))
    from tools.config_mirror_legacy import render_legacy_yaml

    out = render_legacy_yaml(restored_legacy)
    parsed = yaml.safe_load(out)
    assets = parsed["assets"]
    assert isinstance(assets, dict)
    assert len(assets) >= 16  # 22 - already removed

    cdchf = assets.get("CADCHF")
    assert cdchf is not None
    assert "ticker" in cdchf
    assert "config" in cdchf


def test_render_round_trips_through_registry(restored_legacy):
    sys.path.insert(0, str(REPO_ROOT))
    from configs.paper_config_registry import (
        DOMAINS_DIR,
        PaperConfigRegistry,
    )
    from tools.config_mirror_legacy import render_legacy_yaml

    reg = PaperConfigRegistry.load(legacy_path=restored_legacy, domains_dir=DOMAINS_DIR)
    yaml_text = render_legacy_yaml(restored_legacy)
    parsed = yaml.safe_load(yaml_text)
    assert parsed == reg.as_legacy_dict()


def test_check_passes_when_registry_matches_disk(restored_legacy, monkeypatch, capsys):
    sys.path.insert(0, str(REPO_ROOT))
    monkeypatch.setattr("sys.argv", ["config_mirror_legacy.py", "--check", "--path", str(restored_legacy)])
    from tools import config_mirror_legacy

    rc = config_mirror_legacy.main()
    captured = capsys.readouterr()
    assert rc == 0
    assert "drifted" not in captured.err.lower()
    assert "no drift" in captured.out.lower() or "matches" in captured.out.lower()


def test_check_fails_on_modified_legacy(restored_legacy, capsys, monkeypatch):
    """Inject drift by setting an override that the registry won't
    reproduce. The mirror produces capital=100000 (from domain).
    Setting capital on disk to anything different creates structural
    drift if the registry does not overlay the legacy path — but the
    as_legacy_dict() regenerates from domain, so disk's arbitrary
    capital value will NOT match the renderer's output.
    """
    raw = yaml.safe_load(restored_legacy.read_text())
    # Mutate `capital` in a way not reflected in the domain layer:
    raw["capital"] = 7777
    restored_legacy.write_text(yaml.safe_dump(raw))

    sys.path.insert(0, str(REPO_ROOT))
    monkeypatch.setattr("sys.argv", ["config_mirror_legacy.py", "--check", "--path", str(restored_legacy)])
    from tools import config_mirror_legacy

    rc = config_mirror_legacy.main()
    captured = capsys.readouterr()
    assert rc == 1
    assert "drifted" in captured.err.lower()


def test_write_replaces_disk_with_registry_output(restored_legacy):
    """--write fully replaces the legacy YAML with the registry output."""
    sys.path.insert(0, str(REPO_ROOT))
    from tools import config_mirror_legacy
    from tools.config_mirror_legacy import render_legacy_yaml

    pre = restored_legacy.read_text()

    # Mutate capital so post-write content differs
    drift_yaml = yaml.safe_load(pre)
    drift_yaml["capital"] = 9999
    restored_legacy.write_text(yaml.safe_dump(drift_yaml))

    # Run --write
    import sys as _sys

    _sys.path.insert(0, str(REPO_ROOT))
    _sys.argv = ["config_mirror_legacy.py", "--write", "--path", str(restored_legacy)]
    rc = config_mirror_legacy.main()
    assert rc == 0

    post = restored_legacy.read_text()
    expected = render_legacy_yaml(restored_legacy)
    assert post == expected
    parsed_post = yaml.safe_load(post)
    assert parsed_post["capital"] != 9999


def test_render_preserves_session_gate(restored_legacy):
    """Phase 11.3 fix: session_gate must round-trip from legacy_extras."""
    from tools.config_mirror_legacy import render_legacy_yaml

    out = render_legacy_yaml(restored_legacy)
    parsed = yaml.safe_load(out)
    assert "session_gate" in parsed["defaults"]
    sg = parsed["defaults"]["session_gate"]
    assert sg["enabled"] is True
    assert "tiers" in sg
    assert "fx_major" in sg["tiers"]


# ── Phase 12.4 — CI mode ────────────────────────────────────────────────


def _run_ci(path: Path) -> subprocess.CompletedProcess:
    """Run config_mirror_legacy.py --ci and return the CompletedProcess."""
    import sys as _sys

    return subprocess.run(
        [_sys.executable, "tools/config_mirror_legacy.py", "--ci", "--path", str(path)],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        env={"PYTHONPATH": str(REPO_ROOT)},
    )


def test_ci_no_drift_when_clean(restored_legacy):
    """--ci exits 0 with drift=false when no drift exists."""
    result = _run_ci(restored_legacy)
    assert result.returncode == 0, f"stdout={result.stdout}, stderr={result.stderr}"
    parsed = json.loads(result.stdout)
    assert parsed["drift"] is False
    assert parsed["summary"]["total"] == 0


def test_ci_detects_promoted_drift(restored_legacy):
    """--ci reports promoted-key drift when the mirror has stale values."""
    raw = yaml.safe_load(restored_legacy.read_text())
    raw["capital"] = 7777  # promoted key (domain-owned)
    restored_legacy.write_text(yaml.safe_dump(raw))

    result = _run_ci(restored_legacy)
    assert result.returncode == 1, f"stdout={result.stdout}, stderr={result.stderr}"
    parsed = json.loads(result.stdout)
    assert parsed["drift"] is True
    assert parsed["summary"]["promoted"] >= 1
    promoted_changes = [c for c in parsed["changes"] if c["category"] == "promoted"]
    assert len(promoted_changes) >= 1
    capital_change = next((c for c in promoted_changes if c["path"] == "capital"), None)
    assert capital_change is not None
    assert capital_change["disk"] == 7777
    assert capital_change["registry"] == 100000


def test_categorize_path_logic():
    """Unit test for _categorize_path classification logic.

    Verifies that promoted keys, legacy_extras keys, and unknown keys
    are correctly classified without needing mounted disk fixtures.
    """
    sys.path.insert(0, str(REPO_ROOT))
    from tools.config_mirror_legacy import _categorize_path

    promoted = frozenset({"capital", "halt", "defaults", "assets"})
    legacy = frozenset({"mode", "modes", "mt5", "data_source"})

    # Promoted keys
    assert _categorize_path("capital", promoted, legacy) == "promoted"
    assert _categorize_path("halt.drawdown", promoted, legacy) == "promoted"
    assert _categorize_path("defaults.min_confidence", promoted, legacy) == "promoted"

    # Legacy extras keys
    assert _categorize_path("mode", promoted, legacy) == "legacy_extras"
    assert _categorize_path("mt5.bridge_port", promoted, legacy) == "legacy_extras"
    assert _categorize_path("data_source", promoted, legacy) == "legacy_extras"

    # Unknown keys
    assert _categorize_path("unknown_key", promoted, legacy) == "other"
    assert _categorize_path("random.nested.value", promoted, legacy) == "other"
