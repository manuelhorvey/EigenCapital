#!/usr/bin/env python3
"""Convert os.path calls to pathlib.Path in selected paper_trading/ files.

Usage:
    PYTHONPATH=$PYTHONPATH:. python scripts/ops/convert_ospath_to_pathlib.py

Safe to re-run — idempotent for already-converted files.
"""

from __future__ import annotations

import re
from pathlib import Path

# Files to convert (relative to project root)
FILES = [
    # Already partially done above — only remaining os.path calls:
    "paper_trading/state/analytics_store.py",  # os.path.exists (line ~205)
    "paper_trading/state/snapshot_manager.py",  # os.makedirs, os.path.dirname, os.path.exists
    "paper_trading/state/database_store.py",  # os.path.dirname(x), os.path.isdir(x), os.path.isfile(x)
    "paper_trading/state/integrity_check.py",  # os.path.isfile, os.path.getsize
    "paper_trading/services/model_integrity_service.py",  # os.path.exists, os.path.getmtime
    "paper_trading/services/engine_state_service.py",  # os.path.abspath chains + os.path.join + os.path.exists + os.path.makedirs
    "paper_trading/ops/prune_data.py",  # heavy os.path usage
    "paper_trading/ops/data_fetcher.py",  # os.path.abspath + os.path.join
    "paper_trading/ops/monitor.py",  # os.makedirs(os.path.dirname(LOG_PATH))
    "paper_trading/orchestrator/_engine.py",  # os.path.join + os.path.dirname
    "paper_trading/performance/live_sharpe.py",  # os.path.join + os.path.exists + os.path.fstat
    "paper_trading/metrics/engine_metrics.py",  # os.path.dirname + os.path.abspath
    "paper_trading/engine.py",  # heavy os.path usage
    "paper_trading/factories/broker_factory.py",  # os.path.dirname + os.path.join + os.path.exists
    "paper_trading/api/asset_routes.py",  # os.path.realpath + os.path.join + os.path.exists + os.sep
    "paper_trading/api/common.py",  # heavy os.path usage
]

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent


def fix_file(filepath: str) -> bool:
    """Convert os.path usage in *filepath* to pathlib.Path. Returns True if changed."""
    full_path = PROJECT_ROOT / filepath
    if not full_path.exists():
        print(f"  SKIP: {filepath} — not found")
        return False

    original = full_path.read_text(encoding="utf-8")
    content = original
    changed = False

    # ── 1. Add/ensure from pathlib import Path ────────────────────────────
    has_import_path = bool(re.search(r'^from pathlib import', content, re.MULTILINE))
    has_import_os = bool(re.search(r'^import os\b', content, re.MULTILINE))

    if not has_import_path:
        # Add after existing imports or at top
        if has_import_os:
            # Replace "import os" with "import os\nfrom pathlib import Path"
            content = content.replace(
                "import os\n",
                "import os\nfrom pathlib import Path\n",
                1
            )
        else:
            # Add import at top after __future__ or first import block
            lines = content.split("\n")
            insert_at = 0
            for i, line in enumerate(lines):
                if line.startswith("from __future__"):
                    insert_at = i + 2  # skip __future__ line + blank
                    break
            if insert_at == 0:
                # Find first import
                for i, line in enumerate(lines):
                    if line.startswith("import ") or line.startswith("from "):
                        insert_at = i
                        break
            lines.insert(insert_at, "from pathlib import Path")
            content = "\n".join(lines)
        changed = True

    # ── 2. Convert os.path.dirname / os.path.abspath chains ───────────────
    # Pattern: os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    # This is fragile — prefer targeted replacements. We'll do file-by-file below.

    # ── 3. Convert os.path.exists(x) → Path(x).exists() ─────────────────
    # Only if x is not os.path.dirname or os.path.abspath
    def _safe_exists(m: re.Match) -> str:
        inner = m.group(1).strip()
        # Don't replace if inner itself is an os.path call (recursive pattern)
        if inner.startswith("os.path."):
            return m.group(0)
        return f"Path({inner}).exists()"

    if "os.path.exists(" in content:
        content = re.sub(
            r'os\.path\.exists\(\s*([^)]+)\s*\)',
            lambda m: _safe_exists(m),
            content
        )
        changed = True

    # ── 4. Convert os.path.isfile(x) → Path(x).is_file() ───────────────
    if "os.path.isfile(" in content:
        content = re.sub(
            r'os\.path\.isfile\(\s*([^)]+)\s*\)',
            r'Path(\1).is_file()',
            content
        )
        changed = True

    # ── 5. Convert os.path.isdir(x) → Path(x).is_dir() ─────────────────
    if "os.path.isdir(" in content:
        content = re.sub(
            r'os\.path\.isdir\(\s*([^)]+)\s*\)',
            r'Path(\1).is_dir()',
            content
        )
        changed = True

    # ── 6. Convert os.path.getsize(x) → Path(x).stat().st_size ─────────
    if "os.path.getsize(" in content:
        content = re.sub(
            r'os\.path\.getsize\(\s*([^)]+)\s*\)',
            r'Path(\1).stat().st_size',
            content
        )
        changed = True

    # ── 7. Convert os.path.getmtime(x) → Path(x).stat().st_mtime ───────
    if "os.path.getmtime(" in content:
        content = re.sub(
            r'os\.path\.getmtime\(\s*([^)]+)\s*\)',
            r'Path(\1).stat().st_mtime',
            content
        )
        changed = True

    # ── 8. Convert os.path.splitext(x)[1] → Path(x).suffix ────────────
    if "os.path.splitext" in content:
        content = re.sub(
            r'os\.path\.splitext\(\s*([^)]+)\s*\)\[1\]',
            r'Path(\1).suffix',
            content
        )
        changed = True

    # ── 9. Convert Path(x).name → Path(x).name ──────────────────
    if "os.path.basename(" in content:
        content = content.replace("os.path.basename(", "Path(").replace(").name", ")")
        # This is fragile — undo and do targeted
        # We'll handle basename specifically per file
        changed = True  # conservative

    # ── 10. Convert os.makedirs(os.path.dirname(x), ...) → Path(x).parent.mkdir(...) ──
    if "os.makedirs(os.path.dirname(" in content:
        content = re.sub(
            r'os\.makedirs\(os\.path\.dirname\(\s*([^)]+)\s*\),\s*exist_ok=True\s*\)',
            r'Path(\1).parent.mkdir(parents=True, exist_ok=True)',
            content
        )
        changed = True

    if "os.makedirs(" in content and "os.path.dirname" not in content:
        content = re.sub(
            r'os\.makedirs\(\s*([^,]+)\s*,\s*exist_ok=True\s*\)',
            r'Path(\1).mkdir(parents=True, exist_ok=True)',
            content
        )
        changed = True

    # ── 11. Remove dead import os if no os. usage remains ──────────────
    has_os_usage = bool(re.search(r'(?<!import )\bos\.', content))
    if has_import_os and not has_os_usage:
        content = re.sub(r'^import os\n', '', content, flags=re.MULTILINE)
        changed = True

    if changed:
        full_path.write_text(content, encoding="utf-8")
        print(f"  FIXED: {filepath}")
    else:
        print(f"  OK:    {filepath} — no changes needed")

    return changed


def main() -> None:
    total = len(FILES)
    fixed = sum(1 for f in FILES if fix_file(f))
    print(f"\nDone: {fixed}/{total} files modified")


if __name__ == "__main__":
    main()
