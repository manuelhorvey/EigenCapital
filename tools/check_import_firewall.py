"""Static import firewall — AST-scans the source tree for forbidden imports.

EigenCapital uses a runtime import firewall (``tools/import_guard.py``) which
checks whether forbidden modules are *currently imported*.  This module
provides a *static* check that fails CI even if the offender is only
referenced in a script or vendored into a function body.

Forbidden modules represent deprecated refactors that should not be
referenced from production code (see ARCHITECTURE_REVIEW.md and
docs/adr/ADR-026).

Usage:
    PYTHONPATH= python tools/check_import_firewall.py
"""

from __future__ import annotations

import ast
import logging
import sys
from pathlib import Path

logger = logging.getLogger("eigencapital.tools.check_import_firewall")

REPO_ROOT = Path(__file__).resolve().parent.parent

FORBIDDEN_MODULES = frozenset(
    {
        "features.builder",
        "features.lead_lag_features",
        "features.pair_specific",
        "features.publication_lags",
        # "features.cot_features" removed 2026-07-09 (deprecated)
        "features.base_features",
        "features.structural_features",
        "features.interaction_features",
        "shared.features",
        "shared.meta_labeling",
        "signals.signal_generator",
        "signals.paper_signal_adapter",
        "signals.signal_filters",
        "signals.thresholding",
        "signals.alpha_weighting",
        "models.macro_only",
        "portfolio.correlation_clusters",
        "portfolio.hrp_allocator",
        "portfolio.risk_parity",
        "risk.exposure_limits",
        "risk.stop_engine",
    }
)

SCAN_DIRECTORIES = [
    "paper_trading",
    "shared",
    "features",
    "labels",
    "monitoring",
    "scripts",
    "eigencapital",
]

EXCLUDE_PATTERNS = {
    "legacy_systems",
    ".venv",
    "__pycache__",
    ".pytest_cache",
    ".git",
}


def _is_excluded(path: Path) -> bool:
    return any(p in path.parts for p in EXCLUDE_PATTERNS)


def _module_forbidden(mod_name: str) -> str | None:
    for forbidden in FORBIDDEN_MODULES:
        if mod_name == forbidden or mod_name.startswith(forbidden + "."):
            return forbidden
    return None


def _check_file(filepath: Path) -> list[tuple[int, str, str]]:
    try:
        tree = ast.parse(filepath.read_text(), filename=str(filepath))
    except SyntaxError:
        return []

    violations: list[tuple[int, str, str]] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                blocked = _module_forbidden(alias.name)
                if blocked:
                    violations.append((node.lineno or 0, f"import {alias.name}", blocked))
        elif isinstance(node, ast.ImportFrom) and node.module:
            blocked = _module_forbidden(node.module)
            if blocked:
                names = ", ".join(a.name for a in node.names)
                violations.append((node.lineno or 0, f"from {node.module} import {names}", blocked))

    return violations


def main() -> int:
    logging.basicConfig(level=logging.INFO, format="%(message)s", stream=sys.stdout, force=True)
    total_violations = 0
    files_scanned = 0

    for rel_dir in SCAN_DIRECTORIES:
        scan_path = REPO_ROOT / rel_dir
        if not scan_path.is_dir():
            continue
        for pyfile in sorted(scan_path.rglob("*.py")):
            if _is_excluded(pyfile):
                continue
            files_scanned += 1
            violations = _check_file(pyfile)
            if violations:
                rel = pyfile.relative_to(REPO_ROOT)
                for lineno, imp, mod in violations:
                    logger.warning("%s:%d: FORBIDDEN %s — %s", rel, lineno, mod, imp)
                total_violations += len(violations)

    logger.info("\nScanned %d files across %d directories.", files_scanned, len(SCAN_DIRECTORIES))
    if total_violations:
        logger.error("FAILED: %d forbidden import(s) found.", total_violations)
        return 1
    logger.info("PASSED: No forbidden imports detected.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
