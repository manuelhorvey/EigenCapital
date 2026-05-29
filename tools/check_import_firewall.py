import ast
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent

FORBIDDEN_MODULES = frozenset({
    "features.builder",
    "features.lead_lag_features",
    "features.pair_specific",
    "features.publication_lags",
    "features.cot_features",
    "features.base_features",
    "features.trend_features",
    "features.volatility_features",
    "features.mean_reversion_features",
    "features.structural_features",
    "features.interaction_features",
    "features.cross_asset_features",
    "labels.triple_barrier",
    "labels.generator",
    "shared.features",
    "shared.meta_labeling",
    "signals.signal_generator",
    "signals.paper_signal_adapter",
    "signals.signal_filters",
    "signals.thresholding",
    "signals.simple_threshold",
    "signals.alpha_weighting",
    "models.hybrid_ensemble",
    "models.macro_expert_head",
    "models.macro_only",
    "models.mean_reversion.mr_model",
    "portfolio.correlation_clusters",
    "portfolio.hrp_allocator",
    "portfolio.risk_parity",
    "risk.drawdown_controls",
    "risk.exposure_limits",
    "risk.position_sizing",
    "risk.stop_engine",
})

SCAN_DIRECTORIES = [
    "paper_trading",
    "shared",
    "features",
    "labels",
    "monitoring",
    "scripts",
]

EXCLUDE_PATTERNS = [
    "legacy_systems",
    ".venv",
    "__pycache__",
    ".pytest_cache",
    ".git",
]


def _is_excluded(path: Path) -> bool:
    return any(p in path.parts for p in EXCLUDE_PATTERNS)


def _module_forbidden(mod_name: str) -> str | None:
    mod_name = mod_name.split(".")[0]
    for f in FORBIDDEN_MODULES:
        if mod_name == f or mod_name.startswith(f + "."):
            return f
    return None


def _check_file(filepath: Path) -> list[tuple[int, str]]:
    try:
        tree = ast.parse(filepath.read_text(), filename=str(filepath))
    except SyntaxError:
        return []

    violations: list[tuple[int, str]] = []

    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                blocked = _module_forbidden(alias.name)
                if blocked:
                    violations.append((node.lineno or 0, f"import {alias.name}"))
        elif isinstance(node, ast.ImportFrom):
            if node.module:
                blocked = _module_forbidden(node.module)
                if blocked:
                    names = ", ".join(a.name for a in node.names)
                    violations.append((node.lineno or 0, f"from {node.module} import {names}"))

    return violations


def main() -> int:
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
                for lineno, imp in violations:
                    print(f"{rel}:{lineno}: FORBIDDEN IMPORT — {imp}")
                total_violations += len(violations)

    print(f"\nScanned {files_scanned} files across {len(SCAN_DIRECTORIES)} directories.")
    if total_violations:
        print(f"FAILED: {total_violations} forbidden import(s) found.")
        return 1
    print("PASSED: No forbidden imports detected.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
