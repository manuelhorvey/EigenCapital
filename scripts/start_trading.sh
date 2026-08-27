#!/usr/bin/env bash
# ── EigenCapital Trading System Startup ──────────────────────────
#
# Starts the full trading stack:
#   1. MT5 RPyC bridge (if not already running)
#   2. R4 rebalance loop
#   3. R4 monitor (optional)
#
# Handles:
#   - Automatic bridge restart on failure
#   - Port health checks before starting dependent services
#   - Graceful shutdown on SIGINT/SIGTERM
#   - Process isolation via setsid
#
# Usage:
#   ./scripts/start_trading.sh                    # rebalance loop only
#   ./scripts/start_trading.sh --with-monitor     # rebalance + monitor
#   ./scripts/start_trading.sh --dry-run          # rebalance in dry-run mode
#   ./scripts/start_trading.sh --bridge-only      # just start the bridge
#   ./scripts/start_trading.sh --status           # check what's running
#   ./scripts/start_trading.sh --stop             # stop everything
#
set -euo pipefail

# ── Configuration ─────────────────────────────────────────────────
WINEPREFIX="${HOME}/.wine_mt5"
WINE_PYTHON='C:\users\manuelhorveydaniel\AppData\Local\Programs\Python\Python312\python.exe'
BRIDGE_PORT=8001
BRIDGE_HOST="127.0.0.1"
DISPLAY_NUM=":1"
SERVER_DIR="/tmp/mt5linux"
BRIDGE_LOG="/tmp/mt5bridge.log"
LOOP_LOG="reports/r4_loop/loop_stdout.log"
MONITOR_LOG="reports/r4_loop/monitor_stdout.log"
REBALANCE_INTERVAL=3600  # 1 hour
MONITOR_INTERVAL=60

# ── Parse Arguments ───────────────────────────────────────────────
WITH_MONITOR=false
DRY_RUN=false
BRIDGE_ONLY=false
STATUS_ONLY=false
STOP_ALL=false
FORCE_REGIME=false

for arg in "$@"; do
    case "$arg" in
        --with-monitor)   WITH_MONITOR=true ;;
        --dry-run)        DRY_RUN=true ;;
        --bridge-only)    BRIDGE_ONLY=true ;;
        --status)         STATUS_ONLY=true ;;
        --stop)           STOP_ALL=true ;;
        --force-regime)   FORCE_REGIME=true ;;
        --interval)       ;; # handled below
        -h|--help)
            echo "Usage: $0 [--with-monitor] [--dry-run] [--bridge-only] [--status] [--stop]"
            exit 0
            ;;
    esac
done

# ── Helper Functions ──────────────────────────────────────────────

log() {
    echo "[$(date '+%H:%M:%S')] $*"
}

ensure_dirs() {
    mkdir -p reports/r4_loop reports/r4_qualification/evidence
    mkdir -p "$SERVER_DIR"
}

# Check if a port is listening
port_listening() {
    local port=$1
    ss -tlnp 2>/dev/null | grep -q ":${port} "
}

# Check if a process matching a pattern is running
process_running() {
    local pattern=$1
    pgrep -f "$pattern" >/dev/null 2>&1
}

# Check if the RPyC bridge is alive and accepting connections
bridge_alive() {
    if ! port_listening "$BRIDGE_PORT"; then
        return 1
    fi
    # Quick RPyC connection test
    timeout 10 python3 -c "
import rpyc
conn = rpyc.classic.connect('$BRIDGE_HOST', $BRIDGE_PORT)
conn.close()
" 2>/dev/null
}

# ── Status ────────────────────────────────────────────────────────
show_status() {
    echo "═══════════════════════════════════════════════════════════════"
    echo "  EigenCapital Trading System Status"
    echo "═══════════════════════════════════════════════════════════════"

    # Bridge
    if bridge_alive; then
        echo "  Bridge (port $BRIDGE_PORT):  ✅ ALIVE"
    elif port_listening "$BRIDGE_PORT"; then
        echo "  Bridge (port $BRIDGE_PORT):  ⚠️  PORT OPEN BUT UNRESPONSIVE"
    else
        echo "  Bridge (port $BRIDGE_PORT):  ❌ NOT RUNNING"
    fi

    # MT5 Terminal
    if process_running "terminal64.exe"; then
        echo "  MT5 Terminal:                ✅ RUNNING"
    else
        echo "  MT5 Terminal:                ❌ NOT RUNNING"
    fi

    # Rebalance Loop
    if process_running "r4_rebalance_loop"; then
        echo "  Rebalance Loop:              ✅ RUNNING"
    else
        echo "  Rebalance Loop:              ❌ NOT RUNNING"
    fi

    # Monitor
    if process_running "r4_monitor"; then
        echo "  R4 Monitor:                  ✅ RUNNING"
    else
        echo "  R4 Monitor:                  ❌ NOT RUNNING"
    fi

    # Supervisor
    if process_running "r4_supervisor"; then
        echo "  R4 Supervisor:               ✅ RUNNING"
    else
        echo "  R4 Supervisor:               ❌ NOT RUNNING"
    fi

    echo "═══════════════════════════════════════════════════════════════"
}

# ── Stop All ──────────────────────────────────────────────────────
stop_all() {
    log "Stopping all trading processes..."
    pkill -f "r4_rebalance_loop" 2>/dev/null && log "  Stopped rebalance loop" || true
    pkill -f "r4_monitor" 2>/dev/null && log "  Stopped monitor" || true
    pkill -f "r4_supervisor_dryrun" 2>/dev/null && log "  Stopped supervisor" || true
    # Don't kill the bridge or terminal by default — they're shared
    log "Done. (Bridge and MT5 terminal left running)"
}

# ── Start Bridge ──────────────────────────────────────────────────
start_bridge() {
    if bridge_alive; then
        log "Bridge already alive on port $BRIDGE_PORT"
        return 0
    fi

    # Kill any stale bridge processes
    pkill -f "server.py.*$BRIDGE_PORT" 2>/dev/null || true
    sleep 1

    log "Starting MT5 RPyC bridge on port $BRIDGE_PORT..."

    # Ensure Xvfb is running for headless display
    if ! pgrep -f "Xvfb $DISPLAY_NUM" >/dev/null 2>&1; then
        log "  Starting Xvfb on $DISPLAY_NUM..."
        Xvfb "$DISPLAY_NUM" -screen 0 1024x768x24 &>/dev/null &
        sleep 1
    fi

    # Start the bridge server
    export DISPLAY="$DISPLAY_NUM"
    export WINEPREFIX
    cd "$SERVER_DIR"

    setsid wine "$WINE_PYTHON" server.py --host "$BRIDGE_HOST" -p "$BRIDGE_PORT" \
        </dev/null >"$BRIDGE_LOG" 2>&1 &

    # Wait for port to come up (max 30s)
    log "  Waiting for bridge to bind..."
    for i in $(seq 1 15); do
        sleep 2
        if port_listening "$BRIDGE_PORT"; then
            log "  ✅ Bridge bound to port $BRIDGE_PORT"
            # Extra wait for RPyC to be ready for connections
            sleep 3
            if bridge_alive; then
                log "  ✅ Bridge confirmed alive and accepting connections"
                return 0
            else
                log "  ⚠️  Port open but RPyC not ready, waiting more..."
                sleep 5
                if bridge_alive; then
                    log "  ✅ Bridge confirmed alive"
                    return 0
                fi
                log "  ❌ Bridge not responding after port bind"
                return 1
            fi
        fi
        log "  Still waiting... ($((i*2))s)"
    done

    log "  ❌ Bridge failed to start within 30s"
    return 1
}

# ── Stop ──────────────────────────────────────────────────────────
if $STOP_ALL; then
    stop_all
    exit 0
fi

# ── Status ────────────────────────────────────────────────────────
if $STATUS_ONLY; then
    show_status
    exit 0
fi

# ── Main Startup ──────────────────────────────────────────────────
ensure_dirs

log "═══════════════════════════════════════════════════════════════"
log "  EigenCapital Trading System — Starting Up"
log "═══════════════════════════════════════════════════════════════"

# 1. Ensure bridge is running
start_bridge || {
    log "❌ Cannot start without bridge. Exiting."
    exit 1
}

if $BRIDGE_ONLY; then
    log "Bridge-only mode — done."
    exit 0
fi

# 2. Start rebalance loop
if process_running "r4_rebalance_loop"; then
    log "Rebalance loop already running"
else
    log "Starting rebalance loop (interval: ${REBALANCE_INTERVAL}s)..."
    REBALANCE_ARGS="--loop --interval $REBALANCE_INTERVAL"
    $DRY_RUN && REBALANCE_ARGS="$REBALANCE_ARGS --dry-run"
    $FORCE_REGIME && REBALANCE_ARGS="$REBALANCE_ARGS --force-regime"

    nohup python3 scripts/r4_rebalance_loop.py $REBALANCE_ARGS \
        >"$LOOP_LOG" 2>&1 &
    log "  PID: $! → $LOOP_LOG"
    sleep 2

    if process_running "r4_rebalance_loop"; then
        log "  ✅ Rebalance loop started"
    else
        log "  ❌ Rebalance loop failed to start — check $LOOP_LOG"
        tail -20 "$LOOP_LOG" 2>/dev/null
    fi
fi

# 3. Start monitor (optional)
if $WITH_MONITOR; then
    if process_running "r4_monitor"; then
        log "Monitor already running"
    else
        log "Starting monitor (interval: ${MONITOR_INTERVAL}s)..."
        nohup python3 scripts/r4_monitor.py --loop --interval "$MONITOR_INTERVAL" \
            >"$MONITOR_LOG" 2>&1 &
        log "  PID: $! → $MONITOR_LOG"
        sleep 2

        if process_running "r4_monitor"; then
            log "  ✅ Monitor started"
        else
            log "  ⚠️  Monitor failed to start — check $MONITOR_LOG"
        fi
    fi
fi

log ""
log "═══════════════════════════════════════════════════════════════"
log "  System running. Use '$0 --status' to check health."
log "  Use '$0 --stop' to shut down gracefully."
log "═══════════════════════════════════════════════════════════════"
show_status
