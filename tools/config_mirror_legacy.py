"""
config_mirror_legacy.py — regenerate configs/paper_trading.yaml from
PaperConfigRegistry.

Phase 11.3 of the configuration architecture refactor. The legacy
paper_trading.yaml was the operator-write surface; in Phase 12.7 it
was deleted from the repo. This tool can still regenerate it as a
derived shadow for debugging or migration purposes.

Modes:
- Default: emit the regenerated file to stdout (drift-check dry run).
- --write: create/replace configs/paper_trading.yaml from registry.
- --check: exit 1 if the on-disk file diverges from the regenerated
  content (used by CI).
- --ci: like --check but emits structured JSON to stdout with
  categorised changes for CI consumption.

The regeneration composes:
1. PaperConfigRegistry.as_legacy_dict() (typed result of the domain tree)
2. existing legacy_extras carrier (promoted keys pass through).
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

import yaml

REPO_ROOT = Path(__file__).resolve().parent.parent
LEGACY_PATH = REPO_ROOT / "configs" / "paper_trading.yaml"
ENABLE_LEGACY_EDITS = "ENABLE_LEGACY_EDITS"


def _load(path: Path) -> dict:
    return yaml.safe_load(path.read_text()) or {}


def _load_registry(legacy_path: Path = LEGACY_PATH) -> object:
    """Load PaperConfigRegistry once, shared by render and CI helpers."""
    sys.path.insert(0, str(REPO_ROOT))
    from configs.paper_config_registry import (
        DOMAINS_DIR,
        PaperConfigRegistry,
    )
    return PaperConfigRegistry.load(legacy_path=legacy_path, domains_dir=DOMAINS_DIR)


def render_legacy_yaml(legacy_path: Path = LEGACY_PATH) -> str:
    """Render the legacy YAML content as a string from PaperConfigRegistry.

    Uses a YAML serializer that preserves order and reads the original
    legacy file's structure when domains don't override it.
    """
    reg = _load_registry(legacy_path)
    return yaml.safe_dump(
        reg.as_legacy_dict(),
        sort_keys=False,
        default_flow_style=False,
        allow_unicode=True,
    )


def _diff_text(a: str, b: str) -> str:
    from difflib import unified_diff

    return "".join(
        unified_diff(a.splitlines(keepends=True), b.splitlines(keepends=True), fromfile="disk", tofile="regen")
    )


# ── Structured CI diff helpers (Phase 12.4) ────────────────────────────

_MISSING = object()


def _flatten(d: dict, prefix: str = "") -> dict[str, object]:
    """Recursively flatten a nested dict into dot-separated key paths."""
    out: dict[str, object] = {}
    for k, v in d.items():
        key = f"{prefix}.{k}" if prefix else str(k)
        if isinstance(v, dict):
            out.update(_flatten(v, key))
        else:
            out[key] = v
    return out


def _categorize_path(path: str, promoted_top: frozenset, legacy_extras_keys: frozenset) -> str:
    """Classify a config key path as promoted, legacy_extras, or other.

    - ``promoted``: the root key is owned by a domain file. Drift here is a
      sign that an operator edited the mirror instead of the domain file.
    - ``legacy_extras``: the root key lives only in the legacy YAML. Drift
      here is expected (the domain tree doesn't own these keys).
    - ``other``: unknown root key (possible future promotion candidate).
    """
    root = path.split(".")[0]
    if root in promoted_top:
        return "promoted"
    if root in legacy_extras_keys:
        return "legacy_extras"
    return "other"


def _compute_ci_diff(
    disk: dict,
    regen: dict,
    promoted_top: frozenset,
    legacy_extras_keys: frozenset,
) -> dict:
    """Compute structured diff between on-disk legacy and registry output.

    Returns a dict with the Phase 12.4 CI contract:

    .. code:: json

        {
          "drift": true,
          "summary": {"total": 3, "promoted": 1, "legacy_extras": 2, "other": 0},
          "changes": [
            {"path": "capital", "category": "promoted",
             "disk": 99999, "registry": 100000}
          ]
        }
    """
    flat_disk = _flatten(disk)
    flat_regen = _flatten(regen)
    all_keys = set(flat_disk) | set(flat_regen)

    changes: list[dict] = []
    for path in sorted(all_keys):
        lv = flat_disk.get(path, _MISSING)
        rv = flat_regen.get(path, _MISSING)
        if lv is rv or lv == rv:
            continue
        category = _categorize_path(path, promoted_top, legacy_extras_keys)
        change: dict = {"path": path, "category": category}
        if lv is not _MISSING:
            change["disk"] = _json_safe(lv)
        if rv is not _MISSING:
            change["registry"] = _json_safe(rv)
        changes.append(change)

    n_promoted = sum(1 for c in changes if c["category"] == "promoted")
    n_legacy = sum(1 for c in changes if c["category"] == "legacy_extras")
    n_other = sum(1 for c in changes if c["category"] == "other")

    return {
        "drift": len(changes) > 0,
        "summary": {
            "total": len(changes),
            "promoted": n_promoted,
            "legacy_extras": n_legacy,
            "other": n_other,
        },
        "changes": changes,
    }


def _json_safe(value: object) -> object:
    """Convert non-JSON-safe types (e.g. numpy, frozenset) to JSON-safe."""
    if isinstance(value, frozenset):
        return sorted(value)
    if isinstance(value, set):
        return sorted(value)
    return value


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--write", action="store_true", help="Replace on-disk legacy file")
    parser.add_argument("--check", action="store_true", help="Exit 1 if drift detected")
    parser.add_argument("--ci", action="store_true", help="Structured JSON diff for CI (implies --check)")
    parser.add_argument("--path", type=Path, default=LEGACY_PATH)
    args = parser.parse_args()

    rendered = render_legacy_yaml(args.path)

    if args.write:
        args.path.write_text(rendered)
        print(f"config_mirror: wrote {args.path} ({rendered.count(chr(10))} lines)")
        return 0

    if not args.path.exists():
        print(json.dumps({"generated": rendered, "drift": False}))
        return 0

    on_disk_raw = yaml.safe_load(args.path.read_text()) or {}
    rendered_raw = yaml.safe_load(rendered) or {}

    # ── --ci: structured JSON output ────────────────────────────────
    if args.ci:
        reg = _load_registry(args.path)

        # Promoted top-level keys: domain-owned (capital, halt, defaults, assets, ...)
        # plus all sizing field names (promoted to sizing.yaml).
        sizing_fields = frozenset(reg.risk.sizing.__dataclass_fields__.keys())
        promoted_top = frozenset({
            "capital", "position_size", "portfolio_drawdown_limit",
            "halt", "defaults", "assets",
        }) | sizing_fields | frozenset({"adaptive_exit", "sell_only_assets"})

        legacy_extras_keys = frozenset(reg.legacy_extras.keys())

        result = _compute_ci_diff(
            disk=on_disk_raw,
            regen=rendered_raw,
            promoted_top=promoted_top,
            legacy_extras_keys=legacy_extras_keys,
        )

        n_promoted = result["summary"]["promoted"]

        print(json.dumps(result, indent=2, default=str))

        # Promoted-key drift is a hard error; legacy_extras drift is soft
        if n_promoted > 0:
            print(
                f"config_mirror: {n_promoted} promoted key(s) drifted — run --write after domain edits",
                file=sys.stderr,
            )
            return 1
        return 0

    if on_disk_raw == rendered_raw:
        print(f"config_mirror: {args.path} matches registry output (no drift)")
        return 0

    # ── --check: human-readable diff ─────────────────────────────────
    if args.check:
        print(
            _diff_text(
                json.dumps(on_disk_raw, indent=2, sort_keys=True),
                json.dumps(rendered_raw, indent=2, sort_keys=True),
            ),
            file=sys.stderr,
        )

        is_strict = not os.environ.get(ENABLE_LEGACY_EDITS)
        if is_strict:
            print(
                f"config_mirror: STRICT-WRITE: {args.path} drifted from registry output.\n"
                "Operator edits should go to configs/domains/ — the legacy file is a derived mirror.\n"
                "Run `python tools/config_mirror_legacy.py --write` after domain edits, or set\n"
                f"{ENABLE_LEGACY_EDITS}=1 to bypass (emergency use only).",
                file=sys.stderr,
            )
        else:
            print(
                f"config_mirror: {args.path} drifted from registry output\n"
                "Run `python tools/config_mirror_legacy.py --write` and commit.",
                file=sys.stderr,
            )
        return 1

    print(rendered)
    return 0


if __name__ == "__main__":
    sys.exit(main())
