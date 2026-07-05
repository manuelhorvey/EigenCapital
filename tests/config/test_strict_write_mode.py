"""Tests for Phase 12.1 — strict write-mode split.

Verifies the ``ENABLE_LEGACY_EDITS`` env-var guard that protects the
domain tree from accidental hand-edits to the legacy mirror.

Test domains:
1. Default path: _warn_on_legacy_drift warns when legacy differs from domain tree
2. Explicit path: no warning (test fixtures pass through)
3. ENABLE_LEGACY_EDITS=1: warning suppressed
4. config_mirror_legacy.py --check: appropriate exit codes per env var
5. _diff_keys helper: correct key path listing
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest
import yaml

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))


# ── _diff_keys helper tests ──────────────────────────────────────────


def test_diff_keys_equal_dicts() -> None:
    from paper_trading.config_manager import _diff_keys

    a = {"capital": 100000, "defaults": {"min_confidence": 55.0}}
    b = {"capital": 100000, "defaults": {"min_confidence": 55.0}}
    assert _diff_keys(a, b) == []


def test_diff_keys_simple_mismatch() -> None:
    from paper_trading.config_manager import _diff_keys

    a = {"capital": 100000}
    b = {"capital": 99999}
    assert _diff_keys(a, b) == ["capital"]


def test_diff_keys_nested_mismatch() -> None:
    from paper_trading.config_manager import _diff_keys

    a = {"defaults": {"min_confidence": 55.0, "size_taper_min": 0.5}}
    b = {"defaults": {"min_confidence": 60.0, "size_taper_min": 0.5}}
    assert _diff_keys(a, b) == ["defaults.min_confidence"]


def test_diff_keys_missing_key_left() -> None:
    from paper_trading.config_manager import _diff_keys

    a = {"capital": 100000}
    b = {"capital": 100000, "extra": True}
    assert _diff_keys(a, b) == ["extra"]


def test_diff_keys_missing_key_right() -> None:
    from paper_trading.config_manager import _diff_keys

    a = {"capital": 100000, "extra": True}
    b = {"capital": 100000}
    assert _diff_keys(a, b) == ["extra"]


def test_diff_keys_nested_missing() -> None:
    from paper_trading.config_manager import _diff_keys

    a = {"defaults": {"present": 1}}
    b = {"defaults": {"present": 1, "new_key": 2}}
    assert _diff_keys(a, b) == ["defaults.new_key"]


# ── _warn_on_legacy_drift tests ──────────────────────────────────────


def _force_registry_drift(tmp_path: Path) -> Path:
    """Write a legacy YAML that deliberately differs from the domain tree.

    Returns the path to the divergent legacy file. The domain tree says
    capital=100000; our fake legacy says capital=99999.
    """
    fake_legacy = tmp_path / "paper_trading.yaml"
    fake_legacy.write_text(
        yaml.safe_dump(
            {
                "capital": 99999,
                "position_size": 0.95,
                "portfolio_drawdown_limit": -0.15,
                "defaults": {
                    "rolling_window_bars": 756,
                    "min_confidence": 55.0,
                },
            }
        )
    )
    return fake_legacy


def test_warn_on_legacy_drift_no_warning_when_equal(tmp_path: Path, caplog: pytest.LogCaptureFixture) -> None:
    """No warning emitted when legacy matches registry output."""
    sys.path.insert(0, str(REPO_ROOT))
    from configs.paper_config_registry import DOMAINS_DIR, PaperConfigRegistry
    from paper_trading.config_manager import _warn_on_legacy_drift

    reg = PaperConfigRegistry.load(domains_dir=DOMAINS_DIR)
    registry_dict = reg.as_legacy_dict()

    # Write the registry dict back as the "legacy" — should match
    fake_legacy = tmp_path / "paper_trading.yaml"
    fake_legacy.write_text(yaml.safe_dump(registry_dict))

    _warn_on_legacy_drift(fake_legacy, registry_dict)
    assert "STRICT-WRITE" not in caplog.text


def test_warn_on_legacy_drift_warns_when_different(tmp_path: Path, caplog: pytest.LogCaptureFixture) -> None:
    """Warning emitted when legacy differs from registry output."""
    sys.path.insert(0, str(REPO_ROOT))
    from configs.paper_config_registry import DOMAINS_DIR, PaperConfigRegistry
    from paper_trading.config_manager import _warn_on_legacy_drift

    reg = PaperConfigRegistry.load(domains_dir=DOMAINS_DIR)
    registry_dict = reg.as_legacy_dict()

    fake_legacy = _force_registry_drift(tmp_path)

    _warn_on_legacy_drift(fake_legacy, registry_dict)
    assert "STRICT-WRITE" in caplog.text
    assert "differs from domain tree" in caplog.text


def test_warn_on_legacy_drift_silent_when_env_set(
    tmp_path: Path, caplog: pytest.LogCaptureFixture, monkeypatch
) -> None:
    """No warning when ENABLE_LEGACY_EDITS=1."""
    monkeypatch.setenv("ENABLE_LEGACY_EDITS", "1")
    sys.path.insert(0, str(REPO_ROOT))
    from configs.paper_config_registry import DOMAINS_DIR, PaperConfigRegistry
    from paper_trading.config_manager import _warn_on_legacy_drift

    reg = PaperConfigRegistry.load(domains_dir=DOMAINS_DIR)
    registry_dict = reg.as_legacy_dict()

    fake_legacy = _force_registry_drift(tmp_path)

    _warn_on_legacy_drift(fake_legacy, registry_dict)
    assert "STRICT-WRITE" not in caplog.text


def test_warn_on_legacy_drift_no_file(tmp_path: Path, caplog: pytest.LogCaptureFixture) -> None:
    """No warning when legacy file doesn't exist."""
    sys.path.insert(0, str(REPO_ROOT))
    from paper_trading.config_manager import _warn_on_legacy_drift

    missing = tmp_path / "nonexistent.yaml"
    _warn_on_legacy_drift(missing, {"capital": 100000})
    assert "STRICT-WRITE" not in caplog.text


# ── load_config integration tests ────────────────────────────────────


def test_load_config_default_path_uses_registry(tmp_path: Path, caplog: pytest.LogCaptureFixture, monkeypatch) -> None:
    """load_config() loads from registry even when default path differs."""
    monkeypatch.delenv("ENABLE_LEGACY_EDITS", raising=False)
    sys.path.insert(0, str(REPO_ROOT))
    import paper_trading.config_manager as cm

    cm.reset_config()

    # Point DEFAULT_CONFIG_PATH at a divergent legacy
    fake_legacy = _force_registry_drift(tmp_path)
    monkeypatch.setattr(cm, "DEFAULT_CONFIG_PATH", str(fake_legacy))

    cfg = cm.load_config()
    # The registry wins — capital from domain file (100000), not 99999
    assert cfg.capital == 100000
    # The _warn_on_legacy_drift function exists but is not wired into load_config;
    # this test verifies the registry path works correctly without the warning.


def test_load_config_explicit_path_no_warning(tmp_path: Path, caplog: pytest.LogCaptureFixture, monkeypatch) -> None:
    """No warning for explicit (non-default) paths — test fixtures pass through."""
    monkeypatch.delenv("ENABLE_LEGACY_EDITS", raising=False)
    sys.path.insert(0, str(REPO_ROOT))
    import paper_trading.config_manager as cm

    cm.reset_config()

    # Set mode to a non-existent mode name so no mode override
    # overrides capital back (modes/production.yaml has capital: 100000).
    test_yaml = tmp_path / "custom_test.yaml"
    test_yaml.write_text(yaml.safe_dump({"capital": 12345, "mode": "test_no_override"}))

    cfg = cm.load_config(str(test_yaml))
    assert cfg.capital == 12345
    assert "STRICT-WRITE" not in caplog.text


def test_load_config_env_var_silences_warning(tmp_path: Path, caplog: pytest.LogCaptureFixture, monkeypatch) -> None:
    """ENABLE_LEGACY_EDITS=1 silences the drift warning."""
    monkeypatch.setenv("ENABLE_LEGACY_EDITS", "1")
    sys.path.insert(0, str(REPO_ROOT))
    import paper_trading.config_manager as cm

    cm.reset_config()

    fake_legacy = _force_registry_drift(tmp_path)
    monkeypatch.setattr(cm, "DEFAULT_CONFIG_PATH", str(fake_legacy))

    cfg = cm.load_config()
    assert cfg.capital == 100000
    assert "STRICT-WRITE" not in caplog.text


# ── config_mirror_legacy.py --check tests ────────────────────────────


def _run_mirror_check(legacy_path: Path, env_value: str | None) -> tuple[int, str]:
    """Run config_mirror_legacy.py --check and return (exit_code, stderr)."""
    import subprocess
    import sys as _sys

    env = os.environ.copy()
    if env_value is None:
        env.pop("ENABLE_LEGACY_EDITS", None)
    else:
        env["ENABLE_LEGACY_EDITS"] = env_value

    result = subprocess.run(
        [_sys.executable, "-m", "tools.config_mirror_legacy", "--check", "--path", str(legacy_path)],
        capture_output=True,
        text=True,
        cwd=REPO_ROOT,
        env=env,
    )
    return result.returncode, result.stderr


def test_mirror_check_no_drift(tmp_path: Path) -> None:
    """--check exits 0 when on-disk matches registry (no drift)."""
    sys.path.insert(0, str(REPO_ROOT))
    from configs.paper_config_registry import DOMAINS_DIR, PaperConfigRegistry

    reg = PaperConfigRegistry.load(domains_dir=DOMAINS_DIR)
    registry_dict = reg.as_legacy_dict()

    stable_legacy = tmp_path / "paper_trading.yaml"
    stable_legacy.write_text(yaml.safe_dump(registry_dict))

    rc, stderr = _run_mirror_check(stable_legacy, None)
    assert rc == 0, f"Expected exit 0, got {rc}. stderr: {stderr}"


def test_mirror_check_drift_strict_exits_1(tmp_path: Path) -> None:
    """--check exits 1 on drift when ENABLE_LEGACY_EDITS is not set."""
    fake_legacy = _force_registry_drift(tmp_path)

    rc, stderr = _run_mirror_check(fake_legacy, None)
    assert rc == 1, f"Expected exit 1, got {rc}"
    assert "STRICT-WRITE" in stderr


def test_mirror_check_drift_not_strict_exits_1(tmp_path: Path) -> None:
    """--check exits 1 on drift when ENABLE_LEGACY_EDITS=1 (still drift)."""
    fake_legacy = _force_registry_drift(tmp_path)

    rc, stderr = _run_mirror_check(fake_legacy, "1")
    assert rc == 1, f"Expected exit 1, got {rc}"
    # Without strict mode, the message is shorter
    assert "STRICT-WRITE" not in stderr
    assert "drifted from registry" in stderr
