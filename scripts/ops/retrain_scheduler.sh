#!/usr/bin/env bash
# EigenCapital Retrain Scheduler (LEGACY — use Python equivalent for cross-platform)
#
# CROSS-PLATFORM REPLACEMENT:
#   python -m scripts.eigencapital.retrain [--dry-run]
#
# The Python equivalent works identically on Linux, Windows, and Windows VPS.
#
# Wrapper that runs the model retrain pipeline and alerts on failure.
# Designed for cron/systemd timer usage — logs to a dedicated file,
# exits non-zero on gate failures, and sends Slack alerts when
# SLACK_WEBHOOK_URL is configured.
#
# Usage:
#   # Default: full pipeline with rollback on failure
#   ./scripts/ops/retrain_scheduler.sh
#
#   # Dry run (no actual retrain)
#   ./scripts/ops/retrain_scheduler.sh --dry-run
#
#   # Override log directory
#   RETRAIN_LOG_DIR=/var/log/eigencapital ./scripts/ops/retrain_scheduler.sh
#
# Exit codes:
#   0  — Pipeline succeeded (all gates passed or retrain completed OK)
#   1  — Pipeline failed (validation gates exceeded thresholds)
#   2  — Script error (missing environment, config issue, or concurrent run)

set -euo pipefail

# ── Config ──────────────────────────────────────────────────────────────────
cd "$(dirname "$0")/../.."
PROJECT_ROOT="$(pwd)"
TIMESTAMP="$(date +%Y%m%d_%H%M%S)"
RETRAIN_LOG_DIR="${RETRAIN_LOG_DIR:-${PROJECT_ROOT}/data/logs/retrain}"
RETRAIN_LOG="${RETRAIN_LOG_DIR}/retrain_${TIMESTAMP}.log"
PIPELINE_SCRIPT="scripts/training/pipeline.py"
LOCKFILE="${RETRAIN_LOG_DIR}/retrain.lock"

# ── Concurrency guard ───────────────────────────────────────────────────────
mkdir -p "$RETRAIN_LOG_DIR"
exec 200>"$LOCKFILE"
if ! flock -n 200; then
    echo "[$(date)] Previous retrain still running — exiting (lock: ${LOCKFILE})" >&2
    exit 0
fi
# Only register cleanup if we actually hold the lock (trap is runtime-evaluated)
trap 'rm -f "$LOCKFILE"' EXIT

# ── Parse args ──────────────────────────────────────────────────────────────
DRY_RUN=""
while [[ $# -gt 0 ]]; do
    case "$1" in
        --dry-run) DRY_RUN="--dry-run"; shift ;;
        *) echo "Unknown option: $1" >&2; exit 2 ;;
    esac
done

# ── Log rotation (keep last 90 days) ────────────────────────────────────────
find "$RETRAIN_LOG_DIR" -name 'retrain_*.log' -mtime +90 -delete 2>/dev/null || true

# ── Setup ────────────────────────────────────────────────────────────────────
export PYTHONPATH="${PYTHONPATH:-}:${PROJECT_ROOT}"

{
    echo "=========================================================="
    echo "  EigenCapital Retrain Scheduler — ${TIMESTAMP}"
    echo "  Project root: ${PROJECT_ROOT}"
    echo "  Dry run:      ${DRY_RUN:-no}"
    echo "=========================================================="
    echo ""
} | tee -a "$RETRAIN_LOG"

# ── Activate virtual environment (if present) ──────────────────────────────
if [[ -f ".venv/bin/activate" ]]; then
    # shellcheck disable=SC1091
    source .venv/bin/activate
    echo "  Virtual environment: .venv" | tee -a "$RETRAIN_LOG"
elif [[ -f "venv/bin/activate" ]]; then
    # shellcheck disable=SC1091
    source venv/bin/activate
    echo "  Virtual environment: venv" | tee -a "$RETRAIN_LOG"
fi

# ── Source .env for SLACK_WEBHOOK_URL et al. ───────────────────────────────
if [[ -f ".env" ]]; then
    set -a
    # shellcheck disable=SC1091
    source .env
    set +a
fi

# ── Run pipeline ────────────────────────────────────────────────────────────
PIPELINE_ARGS=("--rollback")
if [[ -n "$DRY_RUN" ]]; then
    PIPELINE_ARGS+=("$DRY_RUN")
fi

echo "  Starting pipeline: python ${PIPELINE_SCRIPT} ${PIPELINE_ARGS[*]}" | tee -a "$RETRAIN_LOG"
echo "" | tee -a "$RETRAIN_LOG"

PIPELINE_START="$(date +%s)"
set +e  # allow pipeline failure
python "${PIPELINE_SCRIPT}" "${PIPELINE_ARGS[@]}" 2>&1 | tee -a "$RETRAIN_LOG"
PIPELINE_EXIT="${PIPESTATUS[0]}"
set -e
PIPELINE_END="$(date +%s)"
PIPELINE_DURATION=$((PIPELINE_END - PIPELINE_START))

echo "" | tee -a "$RETRAIN_LOG"
echo "  Pipeline finished: exit=${PIPELINE_EXIT}  duration=${PIPELINE_DURATION}s" | tee -a "$RETRAIN_LOG"
echo "" | tee -a "$RETRAIN_LOG"

# ── Alert on failure ────────────────────────────────────────────────────────
if [[ "$PIPELINE_EXIT" -ne 0 && -z "$DRY_RUN" ]]; then
    echo "  ALERT: Pipeline failed (exit code ${PIPELINE_EXIT})" | tee -a "$RETRAIN_LOG"

    # Send Slack alert via webhook if configured
    if [[ -n "${SLACK_WEBHOOK_URL:-}" ]]; then
        echo "  Sending Slack alert..." | tee -a "$RETRAIN_LOG"
        python3 -c "
import urllib.request, json
msg = '[EigenCapital] Retrain pipeline FAILED at ${TIMESTAMP}\\nExit code: ${PIPELINE_EXIT}\\nDuration: ${PIPELINE_DURATION}s\\nLog: ${RETRAIN_LOG}'
payload = json.dumps({'text': msg, 'channel': '#ops-alerts', 'username': 'EigenCapital Retrain', 'icon_emoji': ':warning:'}).encode('utf-8')
try:
    urllib.request.urlopen('${SLACK_WEBHOOK_URL}', data=payload, timeout=15)
    print('  Slack alert sent')
except Exception as e:
    print(f'  Slack alert failed: {e}')
" 2>&1 | tee -a "$RETRAIN_LOG" || true
    else
        echo "  SLACK_WEBHOOK_URL not set — skipping Slack alert" | tee -a "$RETRAIN_LOG"
    fi

    # Log a summary line that monitoring tools can grep for
    echo "RETRAIN_FAILURE: ${TIMESTAMP} exit=${PIPELINE_EXIT} duration=${PIPELINE_DURATION}s" | tee -a "$RETRAIN_LOG"
fi

# ── Report recent pipeline reports (last 3) ─────────────────────────────────
echo "" | tee -a "$RETRAIN_LOG"
echo "  Latest pipeline reports:" | tee -a "$RETRAIN_LOG"
for REPORT in $(ls -t scripts/data/processed/pipeline_report_*.json 2>/dev/null | head -3); do
    STATUS=$(python3 -c "import json; d=json.load(open('${REPORT}')); print(d['pipeline']['success'])" 2>/dev/null || echo "?")
    SUMMARY=$(python3 -c "
import json
d = json.load(open('${REPORT}'))
s = d['summary']
print(f'{s[\"pass\"]}P/{s[\"warn\"]}W/{s[\"fail\"]}F  total_R={s[\"total_R_sum_retrained\"]:.1f}')
" 2>/dev/null || echo "?")
    echo "    $(basename "${REPORT}"): ${STATUS}  ${SUMMARY}" | tee -a "$RETRAIN_LOG"
done

echo "" | tee -a "$RETRAIN_LOG"
echo "  Done." | tee -a "$RETRAIN_LOG"

exit "$PIPELINE_EXIT"
