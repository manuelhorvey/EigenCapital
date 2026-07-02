"""Check that production code doesn't use bare assertion-style guards.

``assert`` statements are stripped when Python runs with ``-O``.  This
means production invariants guarded by ``assert`` would be silently
disabled in optimized mode.  Pre-merge hook catches these.

Allowlist:
    - tests/        (test fixtures may legitimately use asserts)
    - scripts/      (CLI tools and one-off scripts)
    - tools/        (CLI tooling)
    - docstrings and comments are not scanned — only executable asserts

The pattern matched is a top-level ``assert`` statement.
"""

from __future__ import annotations

import ast
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
PROD_DIRS = ("paper_trading", "eigencapital", "shared")
EXCLUDE_PATTERNS = ("__pycache__", ".venv", ".git", "legacy_systems")


def _is_excluded(path: Path) -> bool:
    return any(p in path.parts for p in EXCLUDE_PATTERNS)


def _walk_python_files() -> list[Path]:
    files: list[Path] = []
    for prod in PROD_DIRS:
        base = REPO_ROOT / prod
        if not base.is_dir():
            continue
        for p in base.rglob("*.py"):
            if not _is_excluded(p):
                files.append(p)
    return files


def _finds_top_level_assert(path: Path) -> list[tuple[int, str]]:
    """Return [(line, text), ...] of bare assert statements in this file."""
    matches: list[tuple[int, str]] = []
    try:
        tree = ast.parse(path.read_text(), filename=str(path))
    except SyntaxError:
        return matches
    # Skip `from __future__ import annotations` parsing errors etc.
    for node in ast.walk(tree):
        if isinstance(node, ast.Assert):
            line_no = node.lineno or 0
            line_text = path.read_text().splitlines()[line_no - 1].strip() if line_no else ""
            matches.append((line_no, line_text))
    return matches


def main() -> int:
    files = _walk_python_files()
    violations: list[tuple[Path, int, str]] = []
    for path in files:
        for line_no, text in _finds_top_level_assert(path):
            violations.append((path, line_no, text))

    if not violations:
        print(f"PASSED: scanned {len(files)} files in {PROD_DIRS}, no top-level asserts.")
        return 0

    print(f"FAILED: {len(violations)} bare assert(s) found in production code:")
    for path, line_no, text in violations[:20]:
        rel = path.relative_to(REPO_ROOT)
        print(f"  {rel}:{line_no}: {text[:80]}")
    if len(violations) > 20:
        print(f"  ... and {len(violations) - 20} more.")
    print(
        "\nReplace with explicit 'if cond: ...; return ...' or raise ValueError. "
        "Asserts are stripped under 'python -O'."
    )
    return 1


if __name__ == "__main__":
    sys.exit(main())
