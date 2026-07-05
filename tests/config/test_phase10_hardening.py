"""Tests for the Phase 10 hardening: config_diff + schema_version."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest
import yaml

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))


# ── config_diff ─────────────────────────────────────────────────────


@pytest.fixture(scope="module")
def diff_tool():
    return REPO_ROOT / "tools" / "config_diff.py"


def test_diff_files_exist(diff_tool):
    assert diff_tool.exists()


def test_diff_paper_vs_research(diff_tool):
    """Two environments that intentionally differ."""
    result = subprocess.run(
        [
            sys.executable,
            str(diff_tool),
            str(REPO_ROOT / "configs" / "environments" / "paper.yaml"),
            str(REPO_ROOT / "configs" / "environments" / "research.yaml"),
        ],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stderr
    out = result.stdout
    assert "data_source" in out
    assert "'mt5'" in out
    assert "'yfinance'" in out


def test_diff_paper_vs_paper_no_changes(diff_tool):
    """Self-diff must report no differences."""
    result = subprocess.run(
        [
            sys.executable,
            str(diff_tool),
            str(REPO_ROOT / "configs" / "environments" / "paper.yaml"),
            str(REPO_ROOT / "configs" / "environments" / "paper.yaml"),
        ],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
    )
    assert "No differences." in result.stdout


def test_diff_json_output(diff_tool):
    """--json must produce parseable JSON with left/right keys."""
    result = subprocess.run(
        [
            sys.executable,
            str(diff_tool),
            str(REPO_ROOT / "configs" / "environments" / "paper.yaml"),
            str(REPO_ROOT / "configs" / "environments" / "research.yaml"),
            "--json",
        ],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0
    parsed = json.loads(result.stdout)
    assert isinstance(parsed, dict)
    assert "data_source" in parsed
    entry = parsed["data_source"]
    assert entry["left"] == "mt5"
    assert entry["right"] == "yfinance"


def test_diff_handles_nested_keys(diff_tool, tmp_path: Path):
    """Nested differences get dotted output."""
    left = tmp_path / "a.yaml"
    right = tmp_path / "b.yaml"
    left.write_text(yaml.safe_dump({"a": {"b": 1, "c": 2}, "d": 3}))
    right.write_text(yaml.safe_dump({"a": {"b": 1, "c": 5}, "d": 3}))
    result = subprocess.run(
        [sys.executable, str(diff_tool), str(left), str(right)],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
    )
    assert "a.c" in result.stdout
    assert "2" in result.stdout
    assert "5" in result.stdout


def test_diff_missing_file_returns_nonzero(diff_tool, tmp_path: Path):
    right = tmp_path / "b.yaml"
    right.write_text("{}\n")
    result = subprocess.run(
        [sys.executable, str(diff_tool), str(tmp_path / "nope.yaml"), str(right)],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
    )
    assert result.returncode != 0


# ── schema_version ─────────────────────────────────────────────────


@pytest.fixture(scope="module")
def schema_version() -> dict:
    path = REPO_ROOT / "configs" / "schema_version.json"
    return json.loads(path.read_text())


def test_schema_version_present(schema_version):
    assert "version" in schema_version


def test_schema_version_is_v2(schema_version):
    """Phase 10 final hardening milestone: schema_version 2.0.0."""
    assert schema_version["version"] == "2.0.0"


def test_schema_version_records_previous(schema_version):
    assert schema_version.get("previous_version") == "1.0.0"


def test_schema_version_has_compat_max(schema_version):
    assert schema_version.get("compat_max") == "<3"


# ── Phase 10 acceptance smoke ────────────────────────────────────────


def test_all_phase0_through_phase9_artifacts_present():
    """Spot-check the artifacts that should exist after the 10-phase plan."""
    expected = [
        # Phase 0
        "BASELINE.md",
        "configs/README.md",
        "configs/schema_version.json",
        "tools/config_lint.py",
        "tools/config_migrate.py",
        # Phase 1
        "tools/check_config_schema.py",
        "tests/tools/test_config_validator.py",
        # Phase 3
        "configs/domain_models/risk.py",
        "configs/domain_models/assets.py",
        # Phase 4
        "configs/domain_loader.py",
        # Phase 6
        "configs/domain_models/triple_barrier.py",
        "configs/domains/ml/triple_barrier.yaml",
        # Phase 7
        "configs/domains/assets/_defaults.yaml",
        "configs/domains/assets/USDCAD.yaml",
        "configs/domains/assets/BTCUSD.yaml",
        # Phase 8
        "configs/environments/paper.yaml",
        "configs/environments/live.yaml",
        "configs/environments/backtest.yaml",
        "configs/environments/research.yaml",
        "configs/environments/test.yaml",
        # Phase 9
        "tools/config_docs.py",
        "docs/CONFIGURATION.md",
        # Phase 10
        "tools/config_diff.py",
    ]
    missing = [p for p in expected if not (REPO_ROOT / p).exists()]
    assert not missing, f"missing artifacts: {missing}"


def test_settings_directory_size_under_budget():
    """Refactor target was reducing the legacy YAML maintenance surface.

    Per-asset files sum to ~16-19 lines per asset (~380 lines total)
    plus _defaults.yaml at 18 lines. The legacy YAML was deleted in
    Phase 12.7; verify per-asset files are reasonably small.
    """
    assets_dir = REPO_ROOT / "configs" / "domains" / "assets"
    asset_files = sorted(assets_dir.glob("[!_]*.yaml"))
    per_asset_total = 0
    for fn in asset_files:
        per_asset_total += sum(1 for _ in fn.read_text().splitlines())
    # 22 per-asset files should average < 30 lines each
    avg_lines = per_asset_total / max(len(asset_files), 1)
    assert avg_lines < 30, (
        f"per-asset average {avg_lines:.1f} lines exceeds 30-line budget"
    )
    # Total per-asset files should be well under 1000 lines
    assert per_asset_total < 800, (
        f"per-asset total {per_asset_total} lines exceeds 800-line budget"
    )


def test_documented_subtraction():
    """Confirm phase plan README references phases 0-12 and is current."""
    readme = (REPO_ROOT / "configs" / "README.md").read_text()
    # Each row in the migration tracking table begins with the phase number
    # (e.g., "| 0 |" or "| Phase 0 |"); verify a row exists.
    for phase in range(13):
        # Phase 11+ uses dotted notation (11.0, 12.5), so check without trailing space
        candidates = (f"| {phase} ", f"| Phase {phase} ", f"| {phase}.")
        assert any(c in readme for c in candidates), f"missing 'Phase {phase}' row in configs/README.md"
    # Confirm completion marker — README uses "✅" (not "✅ completed")
    assert "✅" in readme
    # Schema version 2.0.0 reference
    assert "2.0.0" in readme
    # Phase 12 entries exist (dotted notation)
    assert "12.0" in readme or "12.1" in readme


# ── Phase 10 acceptance: validator still passes the full strategy ──


def test_full_validator_passes_post_phase10():
    result = subprocess.run(
        [sys.executable, "tools/check_config_schema.py"],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert "PASSED" in result.stdout
    assert "22 assets" in result.stdout
    assert "3 sell-only" in result.stdout
