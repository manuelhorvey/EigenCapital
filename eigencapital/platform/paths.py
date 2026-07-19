"""Platform-independent path resolution.

Centralises all directory layout logic so no module in the codebase
needs to hardcode path separators or directory layouts.

All paths are resolved relative to the project root, which is
auto-detected from ``__file__`` parent traversals (same pattern as
the current codebase).

Usage::

    from eigencapital.platform import resolve_data_dir, resolve_log_dir

    live_dir = resolve_data_dir() / "live"
    state_path = live_dir / "state.json"
"""

from __future__ import annotations

from pathlib import Path
from typing import Union

_PathLike = Union[str, Path]


def resolve_project_root() -> Path:
    """Resolve the project root directory.

    Uses the same heuristic as the existing codebase: walk up from
    this file's location until we find a directory containing both
    ``paper_trading`` and ``configs``.

    Cached after the first call.
    """
    if _PROJECT_ROOT is not None:
        return _PROJECT_ROOT

    # Start from this file's location: eigencapital/platform/paths.py
    current = Path(__file__).resolve().parent.parent.parent
    # Walk up until we find the project root marker
    for _ in range(10):
        if (current / "paper_trading").is_dir() and (current / "configs").is_dir():
            _set_root(current)
            return _PROJECT_ROOT  # type: ignore[return-value]
        parent = current.parent
        if parent == current:
            break
        current = parent

    # Fallback: assume CWD is the project root
    root = Path.cwd().resolve()
    _set_root(root)
    return root


_PROJECT_ROOT: Path | None = None


def _set_root(root: Path) -> None:
    global _PROJECT_ROOT
    _PROJECT_ROOT = root


def resolve_data_dir(base: _PathLike | None = None) -> Path:
    """Return the top-level data directory."""
    root = Path(base) if base else resolve_project_root()
    return root / "data"


def resolve_log_dir(base: _PathLike | None = None) -> Path:
    """Return the log directory (data/live by default)."""
    return resolve_data_dir(base) / "live"


def resolve_config_dir(base: _PathLike | None = None) -> Path:
    """Return the config directory."""
    root = Path(base) if base else resolve_project_root()
    return root / "configs"


def resolve_model_dir(base: _PathLike | None = None) -> Path:
    """Return the model directory (paper_trading/models by default)."""
    root = Path(base) if base else resolve_project_root()
    return root / "paper_trading" / "models"


def resolve_backup_dir(base: _PathLike | None = None) -> Path:
    """Return the backup directory."""
    return resolve_data_dir(base) / "backups" / "sqlite"


def resolve_cache_dir(base: _PathLike | None = None) -> Path:
    """Return the cache directory."""
    return resolve_data_dir(base) / "live" / "cache"


def resolve_project_root_str() -> str:
    """Return the project root as a string (convenience for legacy code)."""
    return str(resolve_project_root())


class PathResolver:
    """Stateful path resolver with an explicit base directory.

    Unlike the module-level functions above (which auto-detect the
    project root), this class lets you supply an explicit base path.
    Useful for tests and multi-instance scenarios.
    """

    def __init__(self, base: _PathLike | None = None) -> None:
        self._base = Path(base).resolve() if base else resolve_project_root()

    @property
    def base(self) -> Path:
        return self._base

    @property
    def data_dir(self) -> Path:
        return self._base / "data"

    @property
    def live_dir(self) -> Path:
        return self.data_dir / "live"

    @property
    def log_dir(self) -> Path:
        return self.live_dir

    @property
    def config_dir(self) -> Path:
        return self._base / "configs"

    @property
    def model_dir(self) -> Path:
        return self._base / "paper_trading" / "models"

    @property
    def state_path(self) -> Path:
        return self.live_dir / "state.json"

    @property
    def db_path(self) -> Path:
        return self.live_dir / "state.db"

    @property
    def cache_dir(self) -> Path:
        return self.live_dir / "cache"

    @property
    def backup_dir(self) -> Path:
        return self.data_dir / "backups" / "sqlite"

    @property
    def wal_dir(self) -> Path:
        return self.live_dir / "wal"

    @property
    def log_path(self) -> Path:
        return self.live_dir / "engine.log"

    def ensure_dirs(self) -> None:
        """Create all required directories if they don't exist."""
        dirs = [
            self.live_dir,
            self.cache_dir,
            self.backup_dir,
            self.wal_dir,
            self.model_dir,
        ]
        for d in dirs:
            d.mkdir(parents=True, exist_ok=True)
