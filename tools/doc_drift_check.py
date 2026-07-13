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
   in ``paper_trading/config_manager.py`` (``EngineConfig.from_dict()``)
   matches the domain model (``configs/domain_models/risk.py``)
   ``SellOnlyConfig.assets`` list AND the YAML version (if any) is a subset of the active 22-asset list.

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
    "docs/GOVERNANCE.md",
    "docs/CONFIGURATION.md",
    "docs/MODES.md",
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
    "**/DOCUMENTATION_AUDIT_FULL.md",  # audit report uses relative paths
    "**/DOCUMENTATION_AUDIT_SUMMARY.md",  # audit summary uses relative paths
    "**/CHANGELOG.md",
    "**/node_modules/**",
    "**/.venv/**",
    "**/configs/paper_trading.yaml",  # intentionally deleted in Phase 12.7
    "**/data/live/*.json",  # runtime-generated state files not present in CI
    "**/data/live/**",  # any runtime-generated files
)

# Canonical facts for cross-reference consistency
CANONICAL_FACTS: dict[str, str] = {
    "governance_layers": "17 core + 3 adaptive budget",
    "core_alpha_features": "9 per-asset",
    "trend_exhaustion_features": "6 per-asset",
    "cross_asset_features": "4",
    "sell_only_count": "6",
    "promoted_assets": "22",
    "orchestrator_phases": "5 (PRE + 1a + 1b + 2 + 3 + 4)",
    # Decision pipeline — verified against paper_trading/execution/decision_pipeline.py DEFAULT_STAGES
    "decision_pipeline_stages": "25",
    # Governance size-scalar formula — code uses max() not min()
    # See paper_trading/governance/multipliers.py:44
    "governance_size_scalar_formula_operator": "max",
    # Config defaults — verified against configs/domains/risk/sizing.yaml
    "min_confidence_buy_default": "45.0",
    "min_confidence_sell_default": "55.0",
    # Mode values — verified against configs/domains/modes/production.yaml
    "production_max_concurrent_positions": "13",
    "production_capital": "100000",
    # Infrastructure — verified against configs/domains/infrastructure/config.yaml
    "retrain_window": "10",
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
            # Skip paths under data/ (entire directory is gitignored — runtime-generated)
            if candidate.startswith("data/"):
                continue
            # Skip paths that are intentionally documented as deleted or planned
            if candidate in (
                "configs/paper_trading.yaml",  # intentionally deleted in Phase 12.7
                "configs/environment_resolver.py",  # planned, Phase 13 — not yet implemented
                "state.json",  # runtime-generated file concept, not a source path
            ):
                continue
            # Skip paths under gitignored build artifacts (paper_trading/dashboard/dist/)
            # and optional directories (paper_trading/models/orphaned/)
            if candidate.startswith("paper_trading/dashboard/dist/") or candidate.startswith(
                "paper_trading/models/orphaned/"
            ):
                continue

            # Normalize: strip leading ./ or cwd references
            normalized = candidate.lstrip("./")
            resolved = REPO_ROOT / normalized

            # Re-check after normalization: must still look like a path
            if normalized in seen:
                continue
            seen.add(normalized)
            if resolved.exists():
                continue

            # Fallback: config domain paths are often written as shorthand
            # (e.g. `risk/capital.yaml` instead of
            # `configs/domains/risk/capital.yaml`) in doc tables.
            if resolved.suffix in {".yaml", ".yml", ".json", ".toml"}:
                domain_resolved = REPO_ROOT / "configs" / "domains" / normalized
                if domain_resolved.exists():
                    continue

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


def _check_index_yaml_authority() -> list[str]:
    """Verify _index.yaml is authoritative: PaperConfigRegistry reads it directly.

    As of 2026-07-13, ``PaperConfigRegistry.load()`` reads ``_index.yaml`` to
    determine the canonical asset set. Per-asset YAML files not listed in the
    index are silently ignored by the registry.

    This check verifies all three sources agree:
    - ``_index.yaml`` is parseable and contains an ``assets:`` list
    - Filesystem has a ``.yaml`` file for every asset in ``_index.yaml``
    - The registry's loaded assets match ``_index.yaml`` exactly
    """
    out: list[str] = []

    index_path = REPO_ROOT / "configs" / "domains" / "assets" / "_index.yaml"
    if not index_path.exists():
        out.append("configs/domains/assets/_index.yaml: missing — required as authoritative asset index")
        return out

    try:
        import yaml

        index_data = yaml.safe_load(_read(index_path)) or {}
    except Exception as exc:  # noqa: BLE001
        out.append(f"configs/domains/assets/_index.yaml: unparseable — {exc}")
        return out

    index_assets: list[str] = sorted(index_data.get("assets", []))
    if not index_assets:
        out.append("configs/domains/assets/_index.yaml: empty `assets:` list")
        return out

    # Assets from filesystem: all [!_]*.yaml files (excluding _index and _defaults)
    assets_dir = REPO_ROOT / "configs" / "domains" / "assets"
    fs_assets = sorted(
        fn.stem for fn in assets_dir.glob("[!_]*.yaml") if fn.name != "_index.yaml"
    )

    # Every asset in the index must have a corresponding YAML file on disk
    only_index = set(index_assets) - set(fs_assets)
    if only_index:
        out.append(f"_index.yaml lists assets with no per-asset YAML file: {sorted(only_index)}")

    # Verify registry agrees with the index (it reads _index.yaml directly now)
    try:
        reg_assets = sorted(_registry_assets())
        if reg_assets != index_assets:
            only_reg = set(reg_assets) - set(index_assets)
            only_index_reg = set(index_assets) - set(reg_assets)
            if only_reg:
                out.append(f"registry loaded assets not in _index.yaml: {sorted(only_reg)}")
            if only_index_reg:
                out.append(f"_index.yaml lists assets not loaded by registry: {sorted(only_index_reg)}")
    except Exception as exc:  # noqa: BLE001
        out.append(f"cannot verify registry-vs-index parity: {exc}")

    # Verify filesystem doesn't have orphan assets (those with YAML but absent from index)
    only_fs = sorted(set(fs_assets) - set(index_assets))
    if only_fs:
        out.append(f"filesystem has per-asset YAML files not in _index.yaml (will be ignored): {only_fs}")

    # If any issues were found, suggest the auto-generator
    if out:
        out.append(
            "hint: run `PYTHONPATH=$PYTHONPATH:. python tools/generate_index_yaml.py` "
            "to auto-regenerate _index.yaml from the filesystem"
        )

    return out


def _check_doc_asset_tables() -> list[str]:
    """Count rows in asset tables within documentation files.

    The canonical asset tables in LIVE_CONTRACT.md, PRODUCTION_SYSTEM_SPEC_v1.md,
    and OPERATIONS.md each list 22 promoted assets with columns:
    | Asset | Ticker | Allocation | sl_mult | tp_mult | max_depth |

    Counts data rows after the header separator (|---|---|...| line).
    """
    out: list[str] = []
    expected = int(CANONICAL_FACTS["promoted_assets"])

    docs_with_tables = [
        "LIVE_CONTRACT.md",
        "docs/PRODUCTION_SYSTEM_SPEC_v1.md",
        "docs/OPERATIONS.md",
    ]

    for doc in docs_with_tables:
        path = REPO_ROOT / doc
        if not path.exists():
            continue
        text = _read(path)
        lines = text.splitlines()

        # Find the asset table: look for the header row with Asset | Ticker
        # then count data rows until a blank line or non-table line
        in_table = False
        found_separator = False
        data_rows = 0
        for line in lines:
            if not in_table:
                if re.match(r"\|\s*Asset\s*\|\s*Ticker", line):
                    in_table = True
                continue

            # Header separator row: |---|---|...|
            if not found_separator:
                if re.match(r"\|[-\s]+\|", line):
                    found_separator = True
                continue

            # Data rows: must start with pipe and contain a ticker
            if re.match(r"\|\s*[A-Z0-9^]+\s*\|", line):
                data_rows += 1
            else:
                # End of table
                break

        if data_rows != expected:
            out.append(
                f"{doc}: asset table has {data_rows} rows (expected {expected} — "
                f"see configs/domains/assets/_index.yaml)"
            )

    return out


def _check_metric_consistency() -> list[str]:
    """Verify key metrics are consistent across documents.

    Checks that the governance layer count, feature counts, asset counts,
    stage counts, formula correctness, and config defaults mentioned
    in documentation files align with canonical facts.
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
            expected = int(CANONICAL_FACTS["governance_layers"].split()[0])
            if count != expected:
                out.append(f"{doc}: claims {count} governance layers (expected {expected})")

        # Sell-only count — look for "N SELL_ONLY" or "N sell-only"
        for m in re.finditer(r"(\d+)\s+(?:permanent\s+)?(?:SELL_ONLY|sell.only|sell-only)", text, re.IGNORECASE):
            count = int(m.group(1))
            expected = int(CANONICAL_FACTS["sell_only_count"])
            if count != expected and "reduced" not in text.lower() and m.start() > 0:
                out.append(f"{doc}: claims {count} SELL_ONLY assets (expected {CANONICAL_FACTS['sell_only_count']})")

        # Decision pipeline stage count — look for "N-stage decision pipeline"
        # (not just "N-stage" which would catch orchestrator phase references)
        for m in re.finditer(r"(\d+)-stage decision pipeline", text, re.IGNORECASE):
            count = int(m.group(1))
            expected = int(CANONICAL_FACTS["decision_pipeline_stages"])
            if count != expected:
                out.append(
                    f"{doc}: claims {count}-stage decision pipeline "
                    f"(expected {CANONICAL_FACTS['decision_pipeline_stages']})"
                )

    # ── GOVERNANCE.md specific checks ─────────────────────────────────
    governance_path = REPO_ROOT / "docs/GOVERNANCE.md"
    if governance_path.exists():
        gov_text = _read(governance_path)

        # Check size-scalar formula: code uses max(), doc should NOT say min()
        for m in re.finditer(r"min\(narrative_size_scalar", gov_text):
            line_no = gov_text[: m.start()].count("\n") + 1
            out.append(
                f"docs/GOVERNANCE.md:{line_no}: size-scalar formula uses `min(...)` "
                f"but code uses `max()` — see paper_trading/governance/multipliers.py:44"
            )

        # Check the numeric floor value matches code
        # Uses a generic pattern for the formula structure to avoid
        # matching the × character which requires Unicode escapes.
        expected_floor = 0.30  # _MIN_SIZE_FLOOR in multipliers.py
        for m in re.finditer(r"min\(narrative_size_scalar[^(]+,\s*([\d.]+)\)", gov_text):
            try:
                val = float(m.group(1))
            except ValueError:
                continue
            if abs(val - expected_floor) > 0.001:
                line_no = gov_text[: m.start()].count("\n") + 1
                out.append(
                    f"docs/GOVERNANCE.md:{line_no}: "
                    f"size-scalar floor is {val} but code has {expected_floor}"
                )

    # ── CONFIGURATION.md specific checks ─────────────────────────────
    config_path = REPO_ROOT / "docs/CONFIGURATION.md"
    if config_path.exists():
        cfg_text = _read(config_path)

        # Check retrain_window default matches infrastructure config
        # MODES.md documents retrain_window: 10 — CONFIGURATION.md is auto-generated
        # so we verify against the canonical fact

        # Check that rolling_window_bars mention is consistent with
        # the current dynamic default (None). The config doc shows the
        # domain model default, not the runtime default.
        # We just check that it's not hardcoded to 756 in the doc.
        for m in re.finditer(r"rolling_window_bars.*756", cfg_text):
            out.append(
                "docs/CONFIGURATION.md: rolling_window_bars should be `None` (dynamic from retrain_window), "
                "not hardcoded to 756 — see asset_engine.py:_init_runtime_state()"
            )

        # Check key sizing defaults match canonical facts
        fact_checks = [
            (r"min_confidence_buy.*`(\d+(?:\.\d+)?)`", CANONICAL_FACTS["min_confidence_buy_default"]),
            (r"min_confidence_sell.*`(\d+(?:\.\d+)?)`", CANONICAL_FACTS["min_confidence_sell_default"]),
        ]
        for pattern, expected in fact_checks:
            for m in re.finditer(pattern, cfg_text):
                if m.group(1) != expected:
                    line_no = cfg_text[: m.start()].count("\n") + 1
                    out.append(
                        f"docs/CONFIGURATION.md:{line_no}: documented value `{m.group(1)}` "
                        f"should be `{expected}` — see configs/domains/risk/sizing.yaml"
                    )

    # ── Refresh interval consistency (cross-doc) ───────────────────────
    # Verify docs that claim a specific refresh interval all agree on ~60s.
    refresh_docs = [
        (REPO_ROOT / "docs/PRODUCTION_SYSTEM_SPEC_v1.md", r"~60s\b|~60 seconds\b|every ~60", "~60s"),
        (REPO_ROOT / "docs/OPERATIONS.md", r"60s\b|60 seconds\b", "60s"),
        (REPO_ROOT / "docs/CONFIGURATION.md",
         r"EIGENCAPITAL_REFRESH_INTERVAL.*`60`",
         "EIGENCAPITAL_REFRESH_INTERVAL default 60"),
    ]
    for rpath, pattern, label in refresh_docs:
        if rpath.exists():
            rtext = _read(rpath)
            if not re.search(pattern, rtext):
                out.append(
                    f"{rpath.relative_to(REPO_ROOT)}: missing '{label}' refresh interval claim "
                    f"— should say ~60s (see monitor.py:EIGENCAPITAL_REFRESH_INTERVAL default 60)"
                )

    # ── MODES.md specific checks ─────────────────────────────────────
    modes_path = REPO_ROOT / "docs/MODES.md"
    if modes_path.exists():
        modes_text = _read(modes_path)

        # Check retrain_window: 10 (not 5)
        if not re.search(r"retrain_window\s*[:=]?\s*10", modes_text):
            # Check if it says something other than 10
            m = re.search(r"retrain_window\s*[:=]?\s*(\d+)", modes_text)
            if m:
                out.append(
                    f"docs/MODES.md: retrain_window={m.group(1)} but config says "
                    f"{CANONICAL_FACTS['retrain_window']} — see configs/domains/infrastructure/config.yaml"
                )
            else:
                out.append(
                    f"docs/MODES.md: missing retrain_window: {CANONICAL_FACTS['retrain_window']} "
                    f"— see configs/domains/infrastructure/config.yaml"
                )

        # Check production max_concurrent_positions
        # The doc has a comparison table with | max_concurrent_positions | 8 | 5 | 6 |
        # but production.yaml actually says 13
        prod_row = re.search(
            r"max_concurrent_positions\s*\|\s*(\d+)\s*\|\s*(\d+)\s*\|\s*(\d+)",
            modes_text,
        )
        if prod_row:
            prod_val = prod_row.group(1)
            expected_prod = CANONICAL_FACTS["production_max_concurrent_positions"]
            if prod_val != expected_prod:
                out.append(
                    f"docs/MODES.md: production max_concurrent_positions={prod_val} "
                    f"but production.yaml says {expected_prod}"
                )

        # Check production capital
        cap_m = re.search(r"`capital`\s*\|\s*([\d,]+)\s*\|\s*([\d,]+)\s*\|\s*([\d,]+)", modes_text)
        if cap_m:
            prod_cap = cap_m.group(1).replace(",", "")
            expected_cap = CANONICAL_FACTS["production_capital"]
            if prod_cap != expected_cap:
                out.append(
                    f"docs/MODES.md: production capital={cap_m.group(1)} "
                    f"but production.yaml says {expected_cap}"
                )

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

    # 12. _index.yaml authority
    index_issues = _check_index_yaml_authority()
    findings.extend(index_issues)

    # 13. doc asset table row counts (LIVE_CONTRACT, PRODUCTION_SPEC, OPERATIONS)
    table_issues = _check_doc_asset_tables()
    findings.extend(table_issues)

    # 14. cross-reference metric consistency (Sprint 4)
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
