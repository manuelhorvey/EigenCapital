"""tests for tools/config_mirror_legacy.py — Phase 11.3."""

from __future__ import annotations

import shutil
import sys
from pathlib import Path

import pytest
import yaml

REPO_ROOT = Path(__file__).resolve().parents[2]
LEGACY_PATH = REPO_ROOT / "configs" / "paper_trading.yaml"


@pytest.fixture
def restored_legacy():
    """Restore the legacy YAML from a snapshot taken at test start."""
    snapshot = LEGACY_PATH.read_text()
    yield
    LEGACY_PATH.write_text(snapshot)


def test_render_legacy_yaml_returns_string(restored_legacy):
    sys.path.insert(0, str(REPO_ROOT))
    from tools.config_mirror_legacy import render_legacy_yaml

    out = render_legacy_yaml(LEGACY_PATH)
    assert isinstance(out, str)
    parsed = yaml.safe_load(out)
    assert isinstance(parsed, dict)
    assert "capital" in parsed
    assert "defaults" in parsed
    assert "assets" in parsed


def test_render_legacy_yaml_yields_registered_assets(restored_legacy):
    sys.path.insert(0, str(REPO_ROOT))
    from tools.config_mirror_legacy import render_legacy_yaml

    out = render_legacy_yaml(LEGACY_PATH)
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

    reg = PaperConfigRegistry.load(legacy_path=LEGACY_PATH, domains_dir=DOMAINS_DIR)
    yaml_text = render_legacy_yaml(LEGACY_PATH)
    parsed = yaml.safe_load(yaml_text)
    assert parsed == reg.as_legacy_dict()


def test_check_passes_when_registry_matches_disk(restored_legacy, monkeypatch, capsys):
    sys.path.insert(0, str(REPO_ROOT))
    monkeypatch.setattr("sys.argv", ["config_mirror_legacy.py", "--check", "--path", str(LEGACY_PATH)])
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
    backup = LEGACY_PATH.read_text()
    try:
        raw = yaml.safe_load(backup)
        # Mutate `capital` in a way not reflected in the domain layer:
        # the registry's as_legacy_dict() always emits the domain value,
        # while the disk holds our override. This must drift.
        raw["capital"] = 7777
        LEGACY_PATH.write_text(yaml.safe_dump(raw))

        sys.path.insert(0, str(REPO_ROOT))
        monkeypatch.setattr("sys.argv", ["config_mirror_legacy.py", "--check", "--path", str(LEGACY_PATH)])
        from tools import config_mirror_legacy

        rc = config_mirror_legacy.main()
        captured = capsys.readouterr()
        assert rc == 1
        assert "drifted" in captured.err.lower()
    finally:
        LEGACY_PATH.write_text(backup)


def test_write_replaces_disk_with_registry_output(restored_legacy):
    """--write fully replaces the legacy YAML with the registry output."""
    sys.path.insert(0, str(REPO_ROOT))
    from tools import config_mirror_legacy
    from tools.config_mirror_legacy import render_legacy_yaml

    pre = LEGACY_PATH.read_text()

    # Snapshot disk → dispose so the post-write content cannot equal pre
    drift_yaml = yaml.safe_load(pre)
    drift_yaml["capital"] = 9999
    LEGACY_PATH.write_text(yaml.safe_dump(drift_yaml))

    # Run --write
    import sys as _sys

    _sys.path.insert(0, str(REPO_ROOT))
    _sys.argv = ["config_mirror_legacy.py", "--write", "--path", str(LEGACY_PATH)]
    rc = config_mirror_legacy.main()
    assert rc == 0

    post = LEGACY_PATH.read_text()
    expected = render_legacy_yaml(LEGACY_PATH)
    assert post == expected
    parsed_post = yaml.safe_load(post)
    assert parsed_post["capital"] != 9999


def test_render_preserves_session_gate(restored_legacy):
    """Phase 11.3 fix: session_gate must round-trip from legacy_extras."""
    from tools.config_mirror_legacy import render_legacy_yaml

    out = render_legacy_yaml(LEGACY_PATH)
    parsed = yaml.safe_load(out)
    assert "session_gate" in parsed["defaults"]
    sg = parsed["defaults"]["session_gate"]
    assert sg["enabled"] is True
    assert "tiers" in sg
    assert "fx_major" in sg["tiers"]
