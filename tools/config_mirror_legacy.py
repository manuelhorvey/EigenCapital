"""
config_mirror_legacy.py — regenerate configs/paper_trading.yaml to match
PaperConfigRegistry.

Phase 11.3 of the configuration architecture refactor. The legacy
paper_trading.yaml is no longer the operator-write surface; it becomes
a derived shadow maintained by this tool. Two modes:

- Default: emit the regenerated file to stdout (drift-check dry run).
- --write: replace configs/paper_trading.yaml in place.
- --check: exit 1 if the on-disk file diverges from the regenerated
  content (used by CI).

The regeneration composes:
1. PaperConfigRegistry.as_legacy_dict() (typed result of the domain tree)
2. existing configs/domains/assets/_defaults.yaml overlay plus per-asset
   files (preserves the typed composition path).
3. existing legacy_extras carrier (unpromoted keys pass through).
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import yaml

REPO_ROOT = Path(__file__).resolve().parent.parent
LEGACY_PATH = REPO_ROOT / "configs" / "paper_trading.yaml"


def _load(path: Path) -> dict:
    return yaml.safe_load(path.read_text()) or {}


def render_legacy_yaml(legacy_path: Path = LEGACY_PATH) -> str:
    """Render the legacy YAML content as a string from PaperConfigRegistry.

    Uses a YAML serializer that preserves order and reads the original
    legacy file's structure when domains don't override it.
    """
    sys.path.insert(0, str(REPO_ROOT))
    from configs.paper_config_registry import (
        DOMAINS_DIR,
        PaperConfigRegistry,
    )

    reg = PaperConfigRegistry.load(legacy_path=legacy_path, domains_dir=DOMAINS_DIR)
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


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--write", action="store_true", help="Replace on-disk legacy file")
    parser.add_argument("--check", action="store_true", help="Exit 1 if drift detected")
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
    if on_disk_raw == rendered_raw:
        print(f"config_mirror: {args.path} matches registry output (no drift)")
        return 0

    if args.check:
        # Structural diff via json for stability of key order
        print(
            _diff_text(
                json.dumps(on_disk_raw, indent=2, sort_keys=True),
                json.dumps(rendered_raw, indent=2, sort_keys=True),
            ),
            file=sys.stderr,
        )
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
