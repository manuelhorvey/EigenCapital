"""Tests for eigencapital.platform.paths.

Tests PathResolver, resolve_project_root, and the module-level
resolve_*_dir helper functions.
"""

from __future__ import annotations

import os
import tempfile
from pathlib import Path

import pytest

# Import the module directly to control _PROJECT_ROOT and _set_root
from eigencapital.platform import paths
from eigencapital.platform.paths import (
    PathResolver,
    resolve_backup_dir,
    resolve_cache_dir,
    resolve_config_dir,
    resolve_data_dir,
    resolve_log_dir,
    resolve_model_dir,
    resolve_project_root,
    resolve_project_root_str,
)


# ── Fixtures ──────────────────────────────────────────────────────────────────


@pytest.fixture(autouse=True)
def _reset_globals():
    """Reset the module-level _PROJECT_ROOT and _set_root after each test.

    Also create a temporary directory structure that mimics the project
    layout for deterministic path resolution tests.
    """
    old_root = paths._PROJECT_ROOT
    paths._PROJECT_ROOT = None
    yield
    paths._PROJECT_ROOT = old_root


@pytest.fixture
def temp_project(tmp_path: Path) -> Path:
    """Create a minimal project skeleton for testing PathResolver.

    Structure::

        <tmp>/
            data/
                live/
                    wal/
                    cache/
                backups/
                    sqlite/
            configs/
            paper_trading/
                models/
    """
    root = tmp_path / "my_project"
    root.mkdir()
    (root / "data" / "live" / "wal").mkdir(parents=True)
    (root / "data" / "live" / "cache").mkdir(parents=True)
    (root / "data" / "backups" / "sqlite").mkdir(parents=True)
    (root / "configs").mkdir()
    (root / "paper_trading" / "models").mkdir(parents=True)
    return root


# ── resolve_project_root ────────────────────────────────────────────────────


class TestResolveProjectRoot:
    def test_returns_path(self):
        root = resolve_project_root()
        assert isinstance(root, Path)
        assert root.is_dir()

    def test_returns_project_root(self):
        """The root should contain both paper_trading and configs."""
        root = resolve_project_root()
        assert (root / "paper_trading").is_dir(), f"{root / 'paper_trading'} should exist"
        assert (root / "configs").is_dir(), f"{root / 'configs'} should exist"

    def test_cached_after_first_call(self):
        """Calling twice should return the same cached Path object."""
        a = resolve_project_root()
        b = resolve_project_root()
        assert a is b

    def test_returns_absolute_path(self):
        root = resolve_project_root()
        assert root.is_absolute()

    def test_string_convenience(self):
        root_str = resolve_project_root_str()
        assert isinstance(root_str, str)
        assert Path(root_str).is_dir()

    def test_resolve_project_root_str_equals_path(self):
        root_path = resolve_project_root()
        root_str = resolve_project_root_str()
        assert root_str == str(root_path)

    def test_heuristic_finds_project_from_file_location(self, monkeypatch, tmp_path):
        """The ``__file__`` heuristic should find the project root even when
        CWD is a random directory without ``paper_trading`` or ``configs``.

        ``resolve_project_root`` walks up from ``__file__`` (not CWD), so
        changing the working directory should not affect the result.
        """
        fake_root = tmp_path / "nowhere"
        fake_root.mkdir()
        monkeypatch.setattr(paths, "_PROJECT_ROOT", None)
        monkeypatch.chdir(fake_root)
        root = resolve_project_root()
        assert root.is_dir()
        assert (root / "paper_trading").is_dir(), f"{root / 'paper_trading'} should exist"


# ── PathResolver ─────────────────────────────────────────────────────────────


class TestPathResolver:
    def test_default_constructor_uses_project_root(self):
        resolver = PathResolver()
        assert resolver.base == resolve_project_root()

    def test_explicit_base(self, temp_project):
        resolver = PathResolver(temp_project)
        assert resolver.base == temp_project.resolve()

    def test_data_dir(self, temp_project):
        resolver = PathResolver(temp_project)
        assert resolver.data_dir == temp_project / "data"

    def test_live_dir(self, temp_project):
        resolver = PathResolver(temp_project)
        assert resolver.live_dir == temp_project / "data" / "live"

    def test_log_dir_is_live_dir(self, temp_project):
        resolver = PathResolver(temp_project)
        assert resolver.log_dir == resolver.live_dir

    def test_config_dir(self, temp_project):
        resolver = PathResolver(temp_project)
        assert resolver.config_dir == temp_project / "configs"

    def test_model_dir(self, temp_project):
        resolver = PathResolver(temp_project)
        assert resolver.model_dir == temp_project / "paper_trading" / "models"

    def test_state_path(self, temp_project):
        resolver = PathResolver(temp_project)
        assert resolver.state_path == temp_project / "data" / "live" / "state.json"

    def test_db_path(self, temp_project):
        resolver = PathResolver(temp_project)
        assert resolver.db_path == temp_project / "data" / "live" / "state.db"

    def test_cache_dir(self, temp_project):
        resolver = PathResolver(temp_project)
        assert resolver.cache_dir == temp_project / "data" / "live" / "cache"

    def test_backup_dir(self, temp_project):
        resolver = PathResolver(temp_project)
        assert resolver.backup_dir == temp_project / "data" / "backups" / "sqlite"

    def test_wal_dir(self, temp_project):
        resolver = PathResolver(temp_project)
        assert resolver.wal_dir == temp_project / "data" / "live" / "wal"

    def test_log_path(self, temp_project):
        resolver = PathResolver(temp_project)
        assert resolver.log_path == temp_project / "data" / "live" / "engine.log"

    def test_ensure_dirs_creates_directories(self, tmp_path):
        """ensure_dirs should create all missing directories."""
        root = tmp_path / "fresh_project"
        root.mkdir()
        resolver = PathResolver(root)
        resolver.ensure_dirs()
        assert resolver.live_dir.exists()
        assert resolver.cache_dir.exists()
        assert resolver.backup_dir.exists()
        assert resolver.wal_dir.exists()
        assert resolver.model_dir.exists()

    def test_ensure_dirs_idempotent(self, temp_project):
        """Calling ensure_dirs twice should not raise."""
        resolver = PathResolver(temp_project)
        resolver.ensure_dirs()
        resolver.ensure_dirs()  # second call should be a no-op

    def test_string_constructor(self, temp_project):
        """PathResolver should accept a string as base."""
        resolver = PathResolver(str(temp_project))
        assert resolver.base == temp_project.resolve()


# ── Module-level helper functions ────────────────────────────────────────────


class TestResolveHelpers:
    def test_resolve_data_dir(self):
        path = resolve_data_dir()
        assert isinstance(path, Path)
        assert path.name == "data"

    def test_resolve_data_dir_with_base(self, temp_project):
        path = resolve_data_dir(temp_project)
        assert path == temp_project / "data"

    def test_resolve_log_dir(self, temp_project):
        path = resolve_log_dir(temp_project)
        assert path == temp_project / "data" / "live"

    def test_resolve_config_dir(self, temp_project):
        path = resolve_config_dir(temp_project)
        assert path == temp_project / "configs"

    def test_resolve_model_dir(self, temp_project):
        path = resolve_model_dir(temp_project)
        assert path == temp_project / "paper_trading" / "models"

    def test_resolve_backup_dir(self, temp_project):
        path = resolve_backup_dir(temp_project)
        assert path == temp_project / "data" / "backups" / "sqlite"

    def test_resolve_cache_dir(self, temp_project):
        path = resolve_cache_dir(temp_project)
        assert path == temp_project / "data" / "live" / "cache"

    def test_data_dir_is_absolute(self):
        path = resolve_data_dir()
        assert path.is_absolute()

    def test_resolve_log_dir_default_inherits_data(self):
        """resolve_log_dir() without base should use the project root."""
        data = resolve_data_dir()
        log = resolve_log_dir()
        assert log == data / "live"

    def test_resolve_backup_dir_default_inherits_data(self):
        data = resolve_data_dir()
        backup = resolve_backup_dir()
        assert backup == data / "backups" / "sqlite"

    def test_resolve_cache_dir_default_inherits_data(self):
        data = resolve_data_dir()
        cache = resolve_cache_dir()
        assert cache == data / "live" / "cache"


# ── PathResolver with relative paths ─────────────────────────────────────────


class TestPathResolverRelative:
    def test_relative_base_is_resolved(self, tmp_path):
        """A relative base string should be resolved to an absolute path."""
        orig_cwd = Path.cwd()
        try:
            os.chdir(tmp_path)
            resolver = PathResolver(".")
            assert resolver.base.is_absolute()
        finally:
            os.chdir(orig_cwd)

    def test_none_base_falls_back(self):
        """Passing None should fall back to the project root."""
        resolver = PathResolver(None)  # type: ignore[arg-type]
        assert resolver.base == resolve_project_root()
