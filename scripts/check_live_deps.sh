#!/usr/bin/env bash
# Dependency guard for live/ (paper_trading/) — CI-only, non-runtime.
# Fails if live module imports any disallowed research/orphaned package.
set -euo pipefail

LIVE_DIR="paper_trading"
DISALLOWED=(
    "execution\\."
    "portfolio\\."
    "risk\\."
    "signals\\."
    "models\\."
    "diagnostics\\."
    "equity\\."
    "backtests\\."
    "archive\\."
    "configs\\.driver_atlas"
)

HAD_ERROR=0
for pattern in "${DISALLOWED[@]}"; do
    results=$(grep -rn "^from ${pattern}\|^import ${pattern}" "$LIVE_DIR" 2>/dev/null || true)
    if [ -n "$results" ]; then
        echo "FORBIDDEN IMPORT: ${pattern}"
        echo "$results"
        HAD_ERROR=1
    fi
done

# Allow safe shared interface imports
for file in "$LIVE_DIR"/*.py; do
    [ -f "$file" ] || continue
    while IFS= read -r line; do
        if echo "$line" | grep -qE "^from shared\."; then
            module=$(echo "$line" | sed -n 's/^from shared\.\([^ ]*\).*/\1/p')
            case "$module" in
                model|signal|sizing|pnl|features|registry|meta_labeling) ;;
                *)
                    echo "FORBIDDEN SHARED IMPORT: $line (in $file)"
                    HAD_ERROR=1
                    ;;
            esac
        fi
    done < "$file"
done

if [ $HAD_ERROR -ne 0 ]; then
    echo ""
    echo "ERROR: paper_trading/ (live system) must not import research/orphaned modules."
    echo "Blocked patterns: ${DISALLOWED[*]}"
    exit 1
fi

echo "OK: paper_trading/ has no disallowed imports."
exit 0
