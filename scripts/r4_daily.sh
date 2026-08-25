#!/bin/sh
set -u

PROJECT="$HOME/Projects/EigenCapital"
RUN_DIR="$PROJECT/reports/r4_loop/runs"
FLAG="$PROJECT/configs/r4_execute.enabled"

mkdir -p "$RUN_DIR"

exec 9>"$PROJECT/reports/r4_loop/.lock"
if ! flock -n 9; then
    echo "$(date -Is) previous run still active, skipping" >&2
    exit 0
fi

MODE="--dry-run"
LABEL="DRY-RUN"
if [ -f "$FLAG" ]; then
    MODE=""
    LABEL="LIVE-EXECUTE"
fi

cd "$PROJECT"

LOG="$RUN_DIR/$(date +%F).log"
{
    echo "============================================================"
    echo "=== R4 daily run $(date -Is) mode=$LABEL"
    echo "============================================================"
} >> "$LOG"

/usr/bin/python3 scripts/r4_rebalance_loop.py $MODE >> "$LOG" 2>&1
rc=$?

echo "=== exit $rc ===" >> "$LOG"
exit $rc
