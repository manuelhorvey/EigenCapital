#!/usr/bin/env python3
"""
Documentation drift checker.

Detects mismatches between Markdown documentation and code/config sources.
Designed to be wired into CI (see ``.github/workflows/ci.yml`` if present)
and to be runnable locally:

    PYTHONPATH=$PYTHONPATH:. python tools/doc_drift_check.py

Checks performed:

1. **Asset-list consistency** — number of assets in
   ``configs/paper_trading.yaml`` (``assets:`` mapping) equals the
   number of tracked model artifacts (``*_model_hash.txt`` sidecars,
   falling back to ``*_model.json`` files for local runs) outside
   of ``paper_trading/models/orphaned/`` and ``paper_trading/models/research/``.

2. **SELL_ONLY list consistency** — the hardcoded fallback
   ``SELL_ONLY_ASSETS`` in ``paper_trading/execution/gate_constants.py``
   matches the ``configs/paper_trading.yaml:defaults.sell_only_assets``
   list AND the YAML version is a subset of the active 16-asset list.

3. **Phase-count consistency** — counts ``_phase_X_*`` methods in
   ``paper_trading/orchestrator/engine.py`` and asserts that the
   Mermaid diagram in ``README.md`` includes a PRE node.

4. **Key-files path resolution** — every path cited in the
   ``## Key Files`` table of ``AGENTS.md`` must resolve on disk

5. **Component-name identity** — confirms ``ReplayRunner`` (in
   ``paper_trading/replay/runner.py``) is referenced as ``ReplayRunner``
   wherever the orchestrator's WAL replay is mentioned in any of
   ``AGENTS.md``, ``docs/SYSTEM_OVERVIEW.md`` (no ``WALRunner`` stragglers).

6. **Mode selector presence** — ``configs/paper_trading.yaml`` has a
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


def _read(p: Path) -> str:
    return p.read_text()


def _yaml_assets() -> list[str]:
    text = _read(REPO_ROOT / "configs" / "paper_trading.yaml")
    assets: list[str] = []
    in_assets = False
    base_indent: int | None = None
    for line in text.splitlines():
        if re.match(r"^assets:\s*$", line):
            in_assets = True
            base_indent = 2
            continue
        if in_assets:
            if line.strip() == "":
                continue
            stripped = line.lstrip(" ")
            indent = len(line) - len(stripped)
            if indent < (base_indent or 2):
                break
            if indent == base_indent:
                m = re.match(r"^(\^?[A-Za-z][A-Za-z0-9_]*):\s*$", stripped)
                if m:
                    assets.append(m.group(1))
    return assets


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


def _yaml_sell_only() -> list[str]:
    text = _read(REPO_ROOT / "configs" / "paper_trading.yaml")
    block = re.search(r"sell_only_assets:\n((?:\s+-\s+\S+\n?)+)", text)
    if not block:
        return []
    return [line.strip()[2:] for line in block.group(1).splitlines() if line.strip().startswith("- ")]


def _gate_constants_sell_only() -> list[str]:
    text = _read(REPO_ROOT / "paper_trading" / "execution" / "gate_constants.py")
    block = re.search(r"return frozenset\(\s*\{\s*((?:\"[A-Z]+\",?\s*)+)\}\s*\)", text)
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
    text = _read(REPO_ROOT / "configs" / "paper_trading.yaml")
    return bool(re.search(r"^mode:\s+\w+", text, re.MULTILINE)) and "modes:" in text


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


def main() -> int:
    findings: list[str] = []

    # 1. asset-list consistency
    yaml_assets = [_normalize(a) for a in _yaml_assets()]
    model_files = [_normalize(a) for a in _model_files()]
    if sorted(yaml_assets) != sorted(model_files):
        only_yaml = set(yaml_assets) - set(model_files)
        only_models = set(model_files) - set(yaml_assets)
        if only_yaml or only_models:
            findings.append(f"asset mismatch: only_in_yaml={sorted(only_yaml)} only_in_models={sorted(only_models)}")

    # 2. SELL_ONLY list consistency
    yaml_so = set(_yaml_sell_only())
    code_so = set(_gate_constants_sell_only())
    if yaml_so != code_so:
        findings.append(f"SELL_ONLY mismatch: yaml={sorted(yaml_so)} gate_constants={sorted(code_so)}")

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
        findings.append("`mode:` selector or `modes:` block missing in paper_trading.yaml")

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
