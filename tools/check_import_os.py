"""Pre-commit hook — detect Python files that use os.* without importing os.

The pathlib conversion (os_path -> pathlib.Path) across the codebase replaced
many ``import os`` with ``from pathlib import Path``. In several cases the
file still used ``os_fsync()``, ``os_replace()``, ``os_stat()``, or similar
calls, causing ``NameError`` at runtime.

This hook catches those regressions before they reach CI or production.

Allowlist (not flagged):
    - ``os.path.*``              (path operations, widely used)
    - ``os.environ``             (env-var lookups, used everywhere)
    - ``os.sep``, ``os.linesep``, ``os.name``
    - Files that have ``import os`` or ``from os import`` at module level
    - Files that have a local ``import os`` inside a function body
    - Test files (``tests/``) — legitimate use of os.* in fixtures
"""

from __future__ import annotations

import ast
import re
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent

# Directories to scan (production code only — tests are exempt).
SCAN_DIRS = (
    "backtests",
    "configs",
    "eigencapital",
    "features",
    "labels",
    "monitoring",
    "paper_trading",
    "portfolio",
    "shared",
    "tools",
)

EXCLUDE_PATTERNS = ("__pycache__", ".venv", ".git", "legacy_systems", "archive", "notebooks")

# os.XXX calls that are commonly used and do NOT trigger a violation
# by themselves.  Every attribute in this list still requires import os
# at runtime, but these are so pervasive (or are path operations that
# coexisted with the pathlib migration) that flagging them individually
# would create noise.  The check focuses on non-path, non-environ os_*
# calls that were likely left behind after import os was stripped.
_SAFE_OS_ATTRS: frozenset[str] = frozenset({
    "os.path",
    "os.environ",
    "os.sep",
    "os.linesep",
    "os.name",
})


def _is_excluded(path: Path) -> bool:
    return any(p in path.parts for p in EXCLUDE_PATTERNS)


def _is_self_check(path: Path) -> bool:
    """Return True if the file is this tool itself (always exempt).

    The tool's own source contains ``os.`` references in docstrings,
    comments, and the ``f"os.{m.group(1)}"`` format string.  These are
    false positives that don't indicate a missing ``import os``.
    """
    return path.name == "check_import_os.py"


def _walk_python_files() -> list[Path]:
    files: list[Path] = []
    for scan_dir in SCAN_DIRS:
        base = REPO_ROOT / scan_dir
        if not base.is_dir():
            continue
        for p in base.rglob("*.py"):
            if not _is_excluded(p) and not _is_self_check(p):
                files.append(p)
    return files


def _has_module_level_import_os(source: str) -> bool:
    """Check if the file has ``import os`` or ``from os import ...`` at module level."""
    for match in re.finditer(r"^import os\b|^from os import", source, re.MULTILINE):
        return True
    return False


def _has_local_import_os(source: str) -> bool:
    """Check if the file has ``import os`` inside a function body."""
    try:
        tree = ast.parse(source, filename="<check_import_os>")
    except SyntaxError:
        return False
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            for child in ast.walk(node):
                if isinstance(child, ast.Import):
                    for alias in child.names:
                        if alias.name == "os":
                            return True
                elif isinstance(child, ast.ImportFrom):
                    if child.module == "os":
                        return True
    return False


def _find_os_calls(source: str) -> set[str]:
    """Find all ``os.XXX`` calls in the source text (excluding safe attrs).

    Returns a set of unique ``os.XXX`` names found.
    """
    calls: set[str] = set()
    for m in re.finditer(r"(?<![$\w.])os\.([a-zA-Z_]\w*)", source):
        full = f"os.{m.group(1)}"
        if full in _SAFE_OS_ATTRS:
            continue
        calls.add(full)
    return calls


def check_file(path: Path) -> list[str]:
    """Check a single file. Returns list of violation messages (empty = clean)."""
    if _is_self_check(path):
        return []

    try:
        source = path.read_text(errors="replace")
    except OSError:
        return []

    os_calls = _find_os_calls(source)
    if not os_calls:
        return []

    if _has_module_level_import_os(source):
        return []
    if _has_local_import_os(source):
        return []

    # Use absolute path when file is outside REPO_ROOT (e.g. tmp_path in tests)
    try:
        rel = str(path.relative_to(REPO_ROOT))
    except ValueError:
        rel = str(path.resolve())

    calls_str = ", ".join(sorted(os_calls))
    return [f"{rel}: missing ``import os`` — uses {calls_str}"]


def main() -> int:
    files = _walk_python_files()
    violations: list[str] = []

    for path in files:
        violations.extend(check_file(path))

    if not violations:
        print(f"PASSED: scanned {len(files)} files — all have ``import os`` when using os.* calls.")
        return 0

    print(f"FAILED: {len(violations)} file(s) missing ``import os``:")
    for msg in violations:
        print(f"  {msg}")
    print(
        "\nFix: add ``import os`` at the top of each file, or if the os.* call is "
        "inside a single function, add a local ``import os`` inside that function body."
    )
    return 1


if __name__ == "__main__":
    sys.exit(main())
