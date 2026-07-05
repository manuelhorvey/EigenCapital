"""Check that all useSystemSnapshot calls pass a `select` parameter.

Key Contract #1 (ARCHITECTURE.md) requires components to subscribe via
a slice selector rather than the full bundle. Internal hooks that need
the full bundle for downstream consumption are exempt — the discipline
applies at the component layer.

Usage:
    python tools/check_snapshot_discipline.py
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
DASHBOARD_SRC = REPO_ROOT / "paper_trading" / "dashboard" / "src"
EXEMPT_DIRS = frozenset({"__tests__"})

# Hooks and internal modules that consume the full bundle to feed
# slice selectors to components — these are exempt from the discipline.
EXEMPT_FILES = frozenset({
    "useGovernanceRadar.ts",
    "useMonitorAlerts.ts",
    "useSystemSnapshot.ts",
    "hook.ts",           # trading-state/hook.ts
})

# Component files that are documented as exceptions.
EXEMPT_COMPONENTS = frozenset({
    "AppShell.tsx",
    "TradingWorkspace.tsx",
})

CALL_PATTERN = re.compile(r"useSystemSnapshot\s*\(")


def is_exempt(path: Path) -> bool:
    if any(p in path.parts for p in EXEMPT_DIRS):
        return True
    if path.name in EXEMPT_FILES:
        return True
    if path.name in EXEMPT_COMPONENTS:
        return True
    return False


def main() -> int:
    ts_files = sorted(DASHBOARD_SRC.rglob("*.tsx")) + sorted(DASHBOARD_SRC.rglob("*.ts"))
    violations: list[tuple[Path, int, str]] = []
    total_calls = 0
    exempt_calls = 0

    for path in ts_files:
        text = path.read_text()
        calls_in_file = CALL_PATTERN.findall(text)
        if not calls_in_file:
            continue

        if is_exempt(path):
            exempt_calls += len(calls_in_file)
            continue

        for i, line in enumerate(text.splitlines(), 1):
            stripped = line.strip()
            if "useSystemSnapshot" not in stripped:
                continue
            total_calls += 1
            if "useSystemSnapshot(" in stripped:
                idx = stripped.index("useSystemSnapshot(")
                rest = stripped[idx + len("useSystemSnapshot("):]
                if rest.startswith(")"):
                    violations.append((path, i, stripped[:80]))

    total = total_calls + exempt_calls
    if not violations:
        print(f"PASSED: scanned {len(ts_files)} files, {total} useSystemSnapshot calls ({exempt_calls} exempt, {total_calls} with select).")
        return 0

    print(f"FAILED: {len(violations)} useSystemSnapshot call(s) without select parameter:")
    for path, line_no, text in violations:
        rel = path.relative_to(REPO_ROOT)
        print(f"  {rel}:{line_no}: {text}")
    print("\nAdd a select parameter: useSystemSnapshot((b) => b.snapshot.portfolio)")
    return 1


if __name__ == "__main__":
    sys.exit(main())
