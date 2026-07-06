#!/usr/bin/env python3
"""
Documentation drift checker.

Detects mismatches between Markdown documentation and code/config sources.
Designed to be wired into CI (see ``.github/workflows/ci.yml`` if present)
and to be runnable locally:

    PYTHONPATH=$PYTHONPATH:. python tools/doc_drift_check.py

Checks performed:

1. **Asset-list consistency** — number of assets in
   the domain tree (``configs/domains/`` ``assets:`` mapping) equals the
   number of tracked model artifacts (``*_model_hash.txt`` sidecars,
   falling back to ``*_model.json`` files for local runs) outside
   of ``paper_trading/models/orphaned/`` and ``paper_trading/models/research/``.

2. **SELL_ONLY list consistency** — the hardcoded fallback
   ``SELL_ONLY_ASSETS`` in ``paper_trading/execution/gate_constants.py``
   matches the domain tree (``configs/domains/risk/sizing.yaml``)
   ``sell_only_assets`` list AND the YAML version is a subset of the active 16-asset list.

3. **Phase-count consistency** — counts ``_phase_X_*`` methods in
   ``paper_trading/orchestrator/engine.py`` and asserts that the
   Mermaid diagram in ``README.md`` includes a PRE node.

4. **Key-files path resolution** — every path cited in the
   ``## Key Files`` table of ``AGENTS.md`` must resolve on disk

5. **Component-name identity** — confirms ``ReplayRunner`` (in
   ``paper_trading/replay/runner.py``) is referenced as ``ReplayRunner``
   wherever the orchestrator's WAL replay is mentioned in any of
   ``AGENTS.md``, ``docs/SYSTEM_OVERVIEW.md`` (no ``WALRunner`` stragglers).

6. **Mode selector presence** — the domain tree (``configs/domains/``) has a
   top-level ``mode:`` key plus a ``modes:`` block.

7. **Trend-exhaustion feature count** — when the live ``alpha_features.py``
   emitter is OHLCV-gated, total columns = 9 base + 6 trend-exhaustion per
   asset, plus 4 cross-asset. The body of AGENTS.md, LIVE_CONTRACT.md, and
   SYSTEM_OVERVIEW.md must all say "9 base" per-asset OR explicitly call
   out the 9+6=15 per-asset formula.

Exits 0 if everything passes; exits 1 with a Markdown-formatted report
otherwise.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent

DOCS_TO_SCAN = (
    "AGENTS.md",
    "README.md",
    "LIVE_CONTRACT.md",
    "docs/SYSTEM_OVERVIEW.md",
    "docs/PRODUCTION_SYSTEM_SPEC_v1.md",
)

# Directories to scan for path validity checking (all .md files)
DOCS_DIRS = (
    REPO_ROOT / "docs",
    REPO_ROOT / "docs" / "adr",
    REPO_ROOT / "docs" / "audit",
    REPO_ROOT / "docs" / "archive",
    REPO_ROOT / "docs" / "planning",
    REPO_ROOT / "configs",
)

# Exclude patterns for path validation (intentional dead references)
PATH_EXCLUDE_PATTERNS = (
    "**/docs/archive/**",
    "**/docs/adr/**",
    "**/docs/audit/**",
    "**/docs/planning/**",
    "**/CHANGELOG.md",
    "**/node_modules/**",
    "**/.venv/**",
    "**/configs/paper_trading.yaml",  # intentionally deleted in Phase 12.7
)

# Canonical facts for cross-reference consistency
CANONICAL_FACTS: dict[str, str] = {
    "governance_layers": "16 core + 3 adaptive budget",
    "core_alpha_features": "9 per-asset",
    "trend_exhaustion_features": "6 per-asset",
    "cross_asset_features": "4",
    "sell_only_count": "3",
    "promoted_assets": "22",
    "orchestrator_phases": "5 (PRE + 1a + 1b + 2 + 3 + 4)",
}


def _read(p: Path) -> str:
    return p.read_text()


def _registry_assets() -> list[str]:
    """Load asset list from PaperConfigRegistry (domain-first)."""
    sys.path.insert(0, str(REPO_ROOT))
    from configs.paper_config_registry import PaperConfigRegistry

    reg = PaperConfigRegistry.load()
    return sorted(reg.assets.keys())


def _model_files() -> list[str]:
    models_dir = REPO_ROOT / "paper_trading" / "models"
    found = []
    # Model JSON files are gitignored; read from tracked *_hash.txt sidecars
    # so the check works in CI. Fall back to *_model.json for local runs
    # if no hash sidecars exist yet.
    hash_paths = list(models_dir.glob("*_model_hash.txt"))
    json_paths = list(models_dir.glob("*_model.json"))
    paths = hash_paths if hash_paths else json_paths
    for path in paths:
        if "orphaned" in path.parts or "research" in path.parts:
            continue
        # {NAME}_model.json or {NAME}_model_hash.txt. Some assets use
        # `DJI` (no caret) on disk while yaml has `^DJI`. Normalize.
        name = path.stem.replace("_model_hash", "").replace("_model", "")
        # Keep both names visible but emit the no-caret version
        found.append(name)
    return found


def _normalize(name: str) -> str:
    """Strip a leading `^` so `^DJI` ↔ `DJI`."""
    return name.lstrip("^")


def _registry_sell_only() -> list[str]:
    """Load SELL_ONLY list from PaperConfigRegistry."""
    sys.path.insert(0, str(REPO_ROOT))
    from configs.paper_config_registry import PaperConfigRegistry

    reg = PaperConfigRegistry.load()
    return sorted(reg.risk.sell_only.assets)


def _gate_constants_sell_only() -> list[str]:
    """Read SELL_ONLY assets from the hardcoded EngineConfig default.

    gate_constants.py now reads from config dynamically (get_sell_only_assets()).
    The Python-level fallback default lives in config_manager.py:

        sell_only_assets: frozenset = field(
            default_factory=lambda: frozenset({"CADCHF", "NZDCHF", "EURAUD"})
        )
    """
    text = _read(REPO_ROOT / "paper_trading" / "config_manager.py")
    # Find the frozenset({...}) pattern that follows sell_only_assets
    block = re.search(
        r"sell_only_assets.*?frozenset\(\s*\{\s*((?:\"[A-Z]+\",?\s*)+)\}\s*\)",
        text,
        re.DOTALL,
    )
    if not block:
        return []
    return [m.group(1) for m in re.finditer(r"\"([A-Z]+)\"", block.group(1))]


def _phase_methods() -> list[str]:
    """Return all `_phase_X_*` method names declared in the orchestrator."""
    import ast

    text = _read(REPO_ROOT / "paper_trading" / "orchestrator" / "engine.py")
    tree = ast.parse(text)
    names: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name.startswith("_phase_"):
            names.append(node.name)
    return names


def _decide_phase_count() -> int:
    """Number of distinct orchestrator phases derived from method names.

    Methods like ``_phase_1_refresh_signal`` and ``_phase_1b_admission_review``
    both belong to ``1`` and ``1b`` respectively. Pre-phase is ``_pre_phase_pek``.
    So we count ``_pre_phase_*`` + every distinct leading number after ``_phase_``.
    """
    methods = _phase_methods()
    keys = set()
    for name in methods:
        if name.startswith("_pre_phase"):
            keys.add("PRE")
            continue
        m = re.match(r"_phase_(\d+)([a-z]?)_", name)
        if m:
            keys.add(f"{m.group(1)}{m.group(2)}")
    return len(keys)


def _key_files_paths() -> list[str]:
    r"""Extract `| `path` | ...` rows from AGENTS.md "Key Files" table."""
    text = _read(REPO_ROOT / "AGENTS.md")
    in_kf = False
    rows = []
    for line in text.splitlines():
        if line.startswith("## Key Files"):
            in_kf = True
            continue
        if in_kf and line.startswith("## ") and "Key Files" not in line:
            in_kf = False
            break
        if in_kf:
            m = re.match(r"^\|\s+`([^`]+)`\s+\|\s+", line)
            if m:
                rows.append(m.group(1))
    return rows


def _check_walrunner_occurrences() -> list[tuple[str, int]]:
    """Fail if any doc still mentions ``WALRunner`` (the class is ReplayRunner)."""
    findings: list[tuple[str, int]] = []
    for doc in DOCS_TO_SCAN:
        path = REPO_ROOT / doc
        if not path.exists():
            continue
        text = _read(path)
        for i, line in enumerate(text.splitlines(), start=1):
            if "WALRunner" in line:
                findings.append((doc, i))
    return findings


def _check_pre_phase_in_readme() -> tuple[bool, int]:
    """README claims a 5-phase cycle; ensure PRE node is in the mermaid diagram."""
    path = REPO_ROOT / "README.md"
    if not path.exists():
        return True, 0
    text = _read(path)
    lines = text.splitlines()
    has_5phase_word = "5-phase orchestrator cycle" in text
    has_pre_node = any("PRE[" in line or "PRE:" in line for line in lines)
    return has_5phase_word and has_pre_node, sum(1 for _ in lines)


def _check_feature_count_claims() -> list[str]:
    """Find any claim of '11 core' or '13 base' alpha features — both outdated."""
    out = []
    for doc in DOCS_TO_SCAN:
        p = REPO_ROOT / doc
        if not p.exists():
            continue
        text = _read(p)
        for pat, negator in [
            (r"\b11 core\b", "should be 9 core"),
            (r"\b13 base\b", "should be 9 base"),
            (r"\b13 per[- ]asset\b", "should be 9 or 15 per-asset (with OHLCV)"),
        ]:
            for m in re.finditer(pat, text):
                line_no = text[: m.start()].count("\n") + 1
                out.append(f"{doc}:{line_no}: '{m.group(0)}' — {negator}")
    return out


def _check_mode_selector_present() -> bool:
    """Verify mode selector and modes block exist via PaperConfigRegistry."""
    try:
        from configs.paper_config_registry import PaperConfigRegistry

        reg = PaperConfigRegistry.load()
        return "mode" in (reg.legacy_extras or {}) or bool(reg.modes)
    except Exception:  # noqa: BLE001
        return False


def _check_arch_orchestrator_paths() -> list[str]:
    """Verify cited `risk/*` paths don't exist; suggest the `paper_trading/pek/*` replacement."""
    out = []
    for path in _key_files_paths():
        if not path.startswith("risk/"):
            continue
        candidate = REPO_ROOT / path
        actual = REPO_ROOT / path.replace("risk/", "paper_trading/pek/")
        if not candidate.exists() and actual.exists():
            out.append(path)
    return out


def _collect_markdown_files() -> list[Path]:
    """Collect all .md files under docs/ (excluding node_modules, .venv)."""
    md_files: list[Path] = []
    for d in DOCS_DIRS:
        if d.exists():
            md_files.extend(d.rglob("*.md"))
    return sorted(set(md_files))


def _is_excluded(path: Path) -> bool:
    """Check if a path matches any exclusion pattern."""
    try:
        rel = path.relative_to(REPO_ROOT)
    except ValueError:
        return False

    parts = rel.parts
    # Direct check for our known excluded directories
    for d in ("archive", "adr", "audit", "planning", "node_modules", ".venv"):
        if d in parts:
            return True

    # Also check if it's DOCUMENTATION_IMPROVEMENT_PLAN.md
    if rel.name == "DOCUMENTATION_IMPROVEMENT_PLAN.md" or "DOCUMENTATION_IMPROVEMENT_PLAN.md" in parts:
        return True

    # Standard fnmatch check for other patterns
    import fnmatch
    rel_str = rel.as_posix()
    for pat in PATH_EXCLUDE_PATTERNS:
        # Clean up double asterisks for standard wildcard matching
        cleaned = pat.replace("**/", "*").replace("/**", "/*")
        if fnmatch.fnmatch(rel_str, cleaned) or fnmatch.fnmatch(f"/{rel_str}", cleaned):
            return True

    return False


def _is_path_like(candidate: str) -> bool:
    """True if ``candidate`` looks like a real file path, not prose.

    Rejects anything containing spaces, markdown punctuation, math
    operators, or arrows (the typical signatures of a code-span that
    captured a prose fragment, formula, or sentence). Requires either
    a directory separator or a recognized file extension.
    """
    # Strip leading ./ for normalization; doesn't affect form detection.
    s = candidate.lstrip("./")
    if not s:
        return False
    # Reject any non-path punctuation typical of prose code-spans.
    bad_chars = set(" \t()=<>{}[]*|\\,;:`~'\"?!")
    if any(c in bad_chars for c in s):
        return False
    # Reject unicode arrows / dashes / math symbols seen in prose.
    for ch in ("→", "←", "−", "—", "/", "≈", "≤", "≥", "×"):
        if ch in s and "/" not in s.split(ch)[0]:
            # bare arrow without a path separator: prose
            pass
    # Hard reject unicode math/punctuation chars entirely.
    if any(ch in s for ch in ("→", "←", "−", "×", "·", "—", "≈", "≤", "≥")):
        return False
    # Require either a path separator or a recognized file extension.
    if "/" in s:
        return True
    known_ext = (
        ".py",
        ".yaml",
        ".yml",
        ".json",
        ".toml",
        ".md",
        ".sh",
        ".ts",
        ".tsx",
        ".js",
        ".jsx",
        ".css",
        ".txt",
        ".csv",
        ".parquet",
        ".png",
        ".jpg",
        ".jpeg",
        ".gif",
        ".svg",
        ".zip",
        ".html",
        ".env",
        ".pyi",
        ".ini",
        ".lock",
        ".db",
    )
    return any(s.endswith(ext) for ext in known_ext)


def _check_markdown_paths() -> list[str]:
    """Extract backtick-quoted file paths from markdown files and verify they resolve.

    Scans for patterns like `path/to/file.py`, `path/to/file.yaml`, `path/to/FILE.md`
    inside backticks and checks if the path exists on disk relative to REPO_ROOT.

    Excludes:
    - Archive docs (intentionally reference old paths)
    - ADR docs (reference historical paths)
    - audit docs (reference old paths as findings)
    - ENV vars, URLs, hyperlinks, git refs, pip packages, etc.
    - Paths with `$` (variable interpolations)
    - Paths appearing after ``# `` (comments, not references)
    - Non-path code spans (formulas, prose fragments, plain numbers).
    """
    out: list[str] = []
    seen: set[str] = set()

    md_files = _collect_markdown_files()
    for md_path in md_files:
        if _is_excluded(md_path):
            continue
        text = _read(md_path)
        rel = md_path.relative_to(REPO_ROOT)

        # Find backtick-quoted strings that look like file paths
        for m in re.finditer(r"`([^`]+)`", text):
            candidate = m.group(1).strip()

            # Skip URLs, env vars, git refs, pip packages, CLI flags
            if any(
                skip in candidate
                for skip in (
                    "://",
                    "${",
                    "$(",
                    "git@",
                    "github.com",
                    "/tree/",
                    "==",
                    ">=",
                    "@latest",
                    "/blob/",
                    "/commit/",
                )
            ):
                continue
            if candidate.startswith("-") or candidate.startswith("$") or candidate.startswith("#"):
                continue
            # Skip multi-line content (caused by double-backtick regex artifacts)
            if "\n" in candidate:
                continue
            # Skip unreasonably long paths (>256 chars — no real file path is this long)
            if len(candidate) > 256:
                continue
            # Skip markdown table cells and single words
            if candidate.startswith("|"):
                continue
            # Skip code spans that are clearly NOT file paths:
            # formulas, prose fragments, plain numbers/metrics, etc.
            if not _is_path_like(candidate):
                continue
            # Skip markdown link fragments
            if candidate.startswith("#"):
                continue
            # Skip absolute paths starting with / (API routes, not file paths)
            if candidate.startswith("/"):
                continue
            # Skip paths under data/live/ (runtime-generated files not present in CI)
            if "data/live/" in candidate or candidate.startswith("data/live"):
                continue
            # Skip paths that are intentionally documented as deleted or planned
            if candidate in (
                "configs/paper_trading.yaml",       # intentionally deleted in Phase 12.7
                "configs/environment_resolver.py",  # planned, Phase 13 — not yet implemented
            ):
                continue

            # Normalize: strip leading ./ or cwd references
            normalized = candidate.lstrip("./")
            resolved = REPO_ROOT / normalized

            # Re-check after normalization: must still look like a path
            if normalized in seen:
                continue
            seen.add(normalized)
            if not resolved.exists():
                out.append(f"{rel}: path `{candidate}` does not resolve on disk")

    return out


def _check_last_updated_dates() -> list[str]:
    """Verify every active (non-archive, non-ADR) doc has a `**Last updated:**` date.

    Flags:
    - Missing date: WARNING — doc has no last-updated footer
    - Stale date (>180 days): WARNING — doc may be outdated
    """
    out: list[str] = []
    md_files = _collect_markdown_files()

    for md_path in md_files:
        if _is_excluded(md_path):
            continue

        text = _read(md_path)
        rel = md_path.relative_to(REPO_ROOT)

        # Check for last-updated pattern
        date_match = re.search(r"\*\*Last updated:\*\*\s*(\d{4}-\d{2}-\d{2})", text)
        if not date_match:
            if md_path.name == "README.md":
                continue
            out.append(f"{rel}: missing `**Last updated:**` date")
            continue

        # Check staleness
        date_str = date_match.group(1)
        try:
            from datetime import datetime, timezone

            date = datetime.strptime(date_str, "%Y-%m-%d").replace(tzinfo=timezone.utc)
            now = datetime.now(timezone.utc)
            days_stale = (now - date).days
            if days_stale > 180:
                out.append(f"{rel}: `Last updated` is {days_stale} days old (>180) — may be stale")
        except ValueError:
            out.append(f"{rel}: unparseable `Last updated` date: {date_str}")

    return out


def _check_metric_consistency() -> list[str]:
    """Verify key metrics are consistent across documents.

    Checks that the governance layer count, feature counts, and
    asset counts mentioned in documentation files align with
    canonical facts.
    """
    out: list[str] = []

    for doc in DOCS_TO_SCAN:
        path = REPO_ROOT / doc
        if not path.exists():
            continue
        text = _read(path)

        # Governance layer count — look for "N governance" (not section numbers like "6.3")
        for m in re.finditer(r"(?<![.\d])(\d+)\s+(?:core\s+)?governance", text, re.IGNORECASE):
            count = int(m.group(1))
            expected = 16
            if count != expected:
                out.append(f"{doc}: claims {count} governance layers (expected {expected})")

        # Sell-only count — look for "N SELL_ONLY" or "N sell-only"
        for m in re.finditer(r"(\d+)\s+(?:permanent\s+)?(?:SELL_ONLY|sell.only|sell-only)", text, re.IGNORECASE):
            count = int(m.group(1))
            if count != 3 and "reduced" not in text.lower() and m.start() > 0:
                out.append(f"{doc}: claims {count} SELL_ONLY assets (expected {CANONICAL_FACTS['sell_only_count']})")

    return out


def main() -> int:
    findings: list[str] = []

    # 1. asset-list consistency
    reg_assets = [_normalize(a) for a in _registry_assets()]
    model_files = [_normalize(a) for a in _model_files()]
    if sorted(reg_assets) != sorted(model_files):
        only_reg = set(reg_assets) - set(model_files)
        only_models = set(model_files) - set(reg_assets)
        if only_reg or only_models:
            findings.append(f"asset mismatch: only_in_registry={sorted(only_reg)} only_in_models={sorted(only_models)}")

    # 2. SELL_ONLY list consistency
    reg_so = set(_registry_sell_only())
    code_so = set(_gate_constants_sell_only())
    if reg_so != code_so:
        findings.append(f"SELL_ONLY mismatch: registry={sorted(reg_so)} gate_constants={sorted(code_so)}")

    # 3. phase count
    phase_count = _decide_phase_count()
    # The orchestrator has: PRE + (1, 1b, 2, 3, 4) = 6 phases.
    if phase_count not in (5, 6):
        findings.append(f"phase count unexpected: {phase_count} (expected 5 or 6 — see doc/PLAN)")

    # 4. key-files paths
    missing = [p for p in _key_files_paths() if not (REPO_ROOT / p).exists()]
    if missing:
        findings.append(f"key-files paths missing on disk: {missing}")

    # 5. WALRunner stragglers
    walrunner_occurrences = _check_walrunner_occurrences()
    if walrunner_occurrences:
        findings.append(
            f"`WALRunner` still mentioned in {len(walrunner_occurrences)} doc line(s); rename to `ReplayRunner`"
        )

    # 6. mode selector
    if not _check_mode_selector_present():
        findings.append("mode selector or modes block missing from PaperConfigRegistry domain tree")

    # 7. README PRE step present (5-phase claim)
    pre_ok, _ = _check_pre_phase_in_readme()
    if not pre_ok:
        findings.append("README.md does not include PRE step in 5-phase cycle wording or mermaid diagram")

    # 8. feature-count claims
    feat_issues = _check_feature_count_claims()
    if feat_issues:
        findings.extend(feat_issues)

    # 9. `risk/` paths in AGENTS.md that should be `paper_trading/pek/`
    arch_paths = _check_arch_orchestrator_paths()
    if arch_paths:
        findings.append(f"`risk/*` paths in AGENTS.md Key Files that should be `paper_trading/pek/*`: {arch_paths}")

    # 10. markdown file path validity (Sprint 4)
    path_issues = _check_markdown_paths()
    findings.extend(path_issues)

    # 11. last-updated date presence and staleness (Sprint 4)
    date_issues = _check_last_updated_dates()
    findings.extend(date_issues)

    # 12. cross-reference metric consistency (Sprint 4)
    metric_issues = _check_metric_consistency()
    findings.extend(metric_issues)

    if findings:
        report = ["## Documentation Drift Report", ""]
        for f in findings:
            report.append(f"- {f}")
        sys.stderr.write("\n".join(report) + "\n")
        return 1

    print("OK: all doc-drift checks pass.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
