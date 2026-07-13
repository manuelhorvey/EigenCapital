#!/usr/bin/env python3
"""generate_index_yaml.py — auto-generate _index.yaml from per-asset YAML files.

Scans ``configs/domains/assets/`` for ``[!_]*.yaml`` files (excluding
``_index.yaml`` and ``_defaults.yaml``) and writes their sorted stem names
to ``_index.yaml``, making it the authoritative asset list.

Usage:

    PYTHONPATH=$PYTHONPATH:. python tools/generate_index_yaml.py
    PYTHONPATH=$PYTHONPATH:. python tools/generate_index_yaml.py --check  # dry-run, exit 1 if stale
"""

from __future__ import annotations

import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
ASSETS_DIR = REPO_ROOT / "configs" / "domains" / "assets"
INDEX_PATH = ASSETS_DIR / "_index.yaml"


def _read(path: Path) -> str:
    return path.read_text()


def _discover_filesystem_assets() -> list[str]:
    """Return sorted asset names from per-asset YAML files on disk.

    Scans ``configs/domains/assets/`` for ``[!_]*.yaml`` files, excluding
    ``_index.yaml`` and ``_defaults.yaml``.
    """
    assets = sorted(
        fn.stem for fn in ASSETS_DIR.glob("[!_]*.yaml") if fn.name not in ("_index.yaml", "_defaults.yaml")
    )
    return assets


def _read_current_index() -> list[str]:
    """Return asset names currently listed in ``_index.yaml``, or empty list.

    Returns ``[]`` if the file is missing, unparseable, or lacks an ``assets:`` key.
    """
    if not INDEX_PATH.exists():
        return []
    try:
        import yaml

        data = yaml.safe_load(_read(INDEX_PATH)) or {}
        return data.get("assets", [])
    except Exception:  # noqa: BLE001
        return []


def generate() -> str:
    """Generate the content for ``_index.yaml`` from filesystem.

    Returns the YAML content as a string.
    """
    assets = _discover_filesystem_assets()
    lines = ["assets:"]
    for name in assets:
        lines.append(f"- {name}")
    lines.append("")
    return "\n".join(lines)


def write() -> bool:
    """Write the generated index to ``_index.yaml``.

    Returns ``True`` if the file was written (i.e. content changed), ``False``
    if it was already up to date.
    """
    content = generate()
    if INDEX_PATH.exists() and _read(INDEX_PATH) == content:
        return False
    INDEX_PATH.write_text(content)
    return True


def check() -> bool:
    """Check whether ``_index.yaml`` matches the filesystem.

    Returns ``True`` if it matches, ``False`` if stale.
    """
    current = _read_current_index()
    expected = _discover_filesystem_assets()
    return current == expected


def main() -> int:
    import argparse

    parser = argparse.ArgumentParser(
        description="Auto-generate _index.yaml from per-asset YAML files on disk.",
    )
    parser.add_argument(
        "--check",
        action="store_true",
        help="Dry-run: exit 0 if _index.yaml is current, 1 if stale (no file writes)",
    )
    args = parser.parse_args()

    if args.check:
        if check():
            print("_index.yaml is up to date.")
            return 0
        print(
            "_index.yaml is stale — run `PYTHONPATH=$PYTHONPATH:. python tools/generate_index_yaml.py` "
            "to regenerate",
            file=sys.stderr,
        )
        return 1

    assets = _discover_filesystem_assets()
    n = len(assets)
    wrote = write()
    if wrote:
        print(f"Regenerated configs/domains/assets/_index.yaml with {n} asset(s).")
    else:
        print(f"_index.yaml is already up to date ({n} asset(s)).")
    return 0


if __name__ == "__main__":
    sys.exit(main())
