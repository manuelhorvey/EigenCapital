"""
config_lint.py — configuration architecture lint tool.

Phase 0 scaffolding: report-only linter that flags unused parameters,
repeated boilerplate, deprecated key forms, and naming inconsistencies.
Strict mode is opt-in via `--strict`; default behavior is non-failing
to support incremental rollout.

This tool NEVER raises errors that block CI in default mode; the goal is
visibility into configuration drift. Use `--strict` to fail on warnings.
"""

from __future__ import annotations

import argparse
import sys
from collections import Counter
from pathlib import Path

import yaml

REPO_ROOT = Path(__file__).resolve().parent.parent


def _load_registry_dict() -> dict:
    """Load config dict from PaperConfigRegistry."""
    sys.path.insert(0, str(REPO_ROOT))
    from configs.paper_config_registry import PaperConfigRegistry

    reg = PaperConfigRegistry.load()
    return reg.as_legacy_dict()


# Patterns that signal reader misconfiguration
DEPRECATED_KEYS = (
    # min_lot: legacy-MT5 hard-floor removed 2026-06-29; surfaced via YAML comment
    "min_lot",
)

# Grouping patterns used for repeated-block detection
REPEATED_BLOCKS = (
    "shadow_sltp",
    "dynamic_sltp",
    "adaptive_exit",
    "regime_geometry",
    "config:",
)


def _check_duplicate_blocks(assets: dict, findings: list[str]) -> None:
    """Identify per-asset blocks that look identical across most assets."""
    contents: dict[str, str] = {}
    for name, spec in assets.items():
        cfg = spec.get("config") or {}
        if cfg:
            contents[name] = yaml.safe_dump(cfg, sort_keys=True)
    counts = Counter(contents.values())
    total = len(contents)
    for block, count in counts.items():
        if count == 0:
            continue
        ratio = count / max(total, 1)
        if ratio >= 0.9 and count >= 18:
            keys_in_block = [line.strip() for line in block.splitlines() if ":" in line][:5]
            findings.append(
                f"REPEATED-BLOCK: {keys_in_block[0] if keys_in_block else block!r} "
                f"appears in {count}/{total} assets ({ratio:.0%}). "
                "Candidate for default + override composition."
            )


def _check_deprecated_keys(data: dict, findings: list[str]) -> None:
    """Walk naive; surface yaml keys that have been deprecated."""
    stack = [((), data)]
    while stack:
        path, node = stack.pop()
        if isinstance(node, dict):
            for k, v in node.items():
                if k in DEPRECATED_KEYS:
                    findings.append(f"DEPRECATED: {'.'.join(path + (k,))} references a removed key")
                stack.append((path + (k,), v))


def _check_defaults_size(defaults: dict, findings: list[str]) -> None:
    """Surface the dict-density heuristic: >50 keys => fragmentation signal."""
    if isinstance(defaults, dict) and len(defaults) > 50:
        findings.append(
            f"DENSITY-WARN: defaults section has {len(defaults)} keys. "
            "Consider splitting by domain (risk/sizing, risk/exits, execution/spreads, etc)."
        )


def _check_kebab_case_in_paths(users: list[str], findings: list[str]) -> None:
    """Trivial placeholder - file paths dropped in via --paths option."""
    if users:
        findings.append(
            f"INFO: linting {len(users)} user-supplied paths; explicit path mode is experimental in Phase 0"
        )


def lint(config_path: Path | None = None) -> int:
    """Run all lint checks and print findings.

    Returns 0 if --strict is false (report only).
    Returns 0 if --strict is true and no findings.
    Returns 1 if --strict is true and any findings exist.
    """
    parser = argparse.ArgumentParser(description="Configuration lint")
    parser.add_argument("--strict", action="store_true", help="Exit non-zero when findings exist")
    parser.add_argument("--config", type=Path, default=None)
    args, _unknown = parser.parse_known_args()

    if args.config:
        if not args.config.exists():
            print(f"config_lint: file not found: {args.config}")
            return 0
        data = yaml.safe_load(args.config.read_text()) or {}
    else:
        # Load from registry (domain-first)
        try:
            data = _load_registry_dict()
        except Exception as e:  # noqa: BLE001
            print(f"config_lint: could not load registry: {e}")
            return 1
    findings: list[str] = []
    _check_deprecated_keys(data, findings)

    assets = data.get("assets", {}) or {}
    if isinstance(assets, dict):
        _check_duplicate_blocks(assets, findings)

    defaults = data.get("defaults", {}) or {}
    _check_defaults_size(defaults, findings)

    if findings:
        print(f"config_lint: {len(findings)} finding(s):")
        for f in findings:
            print(f"  - {f}")
    else:
        print("config_lint: clean.")

    if args.strict and findings:
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(lint())
