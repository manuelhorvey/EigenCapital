"""
config_diff.py — compare two configuration snapshots.

Phase 10 helper for safe review of configuration changes. Given two
configuration sources (legacy YAMLs or ConfigRegistry snapshots), this
tool emits a side-by-side diff showing every key where the values
diverge.

Usage:
    # Compare live vs production-mode legacy YAML
    python tools/config_diff.py configs/paper_trading.yaml configs/domains/modes/live.yaml

    # Compare two environment overlay files
    python tools/config_diff.py configs/environments/paper.yaml configs/environments/research.yaml

    # Pipe-friendly, JSON output
    python tools/config_diff.py a.yaml b.yaml --json
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

import yaml

REPO_ROOT = Path(__file__).resolve().parent.parent


def _load_yaml(path: Path) -> dict:
    if not path.exists():
        return {}
    return yaml.safe_load(path.read_text()) or {}


def _flatten(d: dict, prefix: str = "") -> dict[str, Any]:
    out: dict[str, Any] = {}
    for k, v in d.items():
        key = f"{prefix}.{k}" if prefix else str(k)
        if isinstance(v, dict):
            out.update(_flatten(v, key))
        else:
            out[key] = v
    return out


def diff(left: dict, right: dict) -> dict[str, tuple[Any, Any]]:
    """Return a dict of changed-keys → (left_value, right_value)."""
    flat_l = _flatten(left)
    flat_r = _flatten(right)
    keys = set(flat_l) | set(flat_r)
    return {k: (flat_l.get(k), flat_r.get(k)) for k in sorted(keys) if flat_l.get(k) != flat_r.get(k)}


def format_text(diffs: dict[str, tuple[Any, Any]]) -> str:
    if not diffs:
        return "No differences.\n"
    out_lines = ["Configuration differences:"]
    for key, (a, b) in diffs.items():
        out_lines.append(f"  {key}:")
        out_lines.append(f"    - {a!r}")
        out_lines.append(f"    + {b!r}")
    return "\n".join(out_lines) + "\n"


def format_json(diffs: dict[str, tuple[Any, Any]]) -> str:
    return json.dumps(
        {k: {"left": a, "right": b} for k, (a, b) in diffs.items()},
        indent=2,
        sort_keys=True,
    )


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("left", type=Path, help="Left configuration YAML")
    parser.add_argument("right", type=Path, help="Right configuration YAML")
    parser.add_argument("--json", action="store_true", help="Emit JSON instead of text")
    args = parser.parse_args()

    if not args.left.exists():
        print(f"config_diff: file not found: {args.left}", file=sys.stderr)
        return 1
    if not args.right.exists():
        print(f"config_diff: file not found: {args.right}", file=sys.stderr)
        return 1

    left = _load_yaml(args.left)
    right = _load_yaml(args.right)
    diffs = diff(left, right)

    if args.json:
        print(format_json(diffs))
    else:
        print(format_text(diffs))

    return 0


if __name__ == "__main__":
    sys.exit(main())
