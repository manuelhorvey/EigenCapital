#!/usr/bin/env bash
#
# EigenCapital Dashboard — Start both backend and frontend
#
# Usage:
#   ./scripts/start_dashboard.sh              # Start both (dev mode)
#   ./scripts/start_dashboard.sh --prod       # Start backend + serve production build
#   ./scripts/start_dashboard.sh --backend    # Start backend only
#   ./scripts/start_dashboard.sh --frontend   # Start frontend only
#

set -euo pipefail

PROJECT_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
BACKEND_PORT=8080
FRONTEND_PORT=5173

# Colors
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
CYAN='\033[0;36m'
NC='\033[0m' # No Color

# PIDs to cleanup
BACKEND_PID=""
FRONTEND_PID=""

cleanup() {
    echo ""
    echo -e "${YELLOW}Shutting down...${NC}"
    [ -n "$BACKEND_PID" ] && kill "$BACKEND_PID" 2>/dev/null && echo -e "${RED}  Backend stopped${NC}"
    [ -n "$FRONTEND_PID" ] && kill "$FRONTEND_PID" 2>/dev/null && echo -e "${RED}  Frontend stopped${NC}"
    exit 0
}

trap cleanup SIGINT SIGTERM

print_banner() {
    echo -e "${CYAN}"
    echo "╔══════════════════════════════════════════════════════════════╗"
    echo "║           EigenCapital Operations Dashboard                 ║"
    echo "║           Read-Only Observability Layer                     ║"
    echo "╚══════════════════════════════════════════════════════════════╝"
    echo -e "${NC}"
}

start_backend() {
    echo -e "${BLUE}[1/2]${NC} Starting FastAPI backend on port ${BACKEND_PORT}..."
    cd "$PROJECT_ROOT"
    python scripts/dashboard_server.py --port "$BACKEND_PORT" --reload &
    BACKEND_PID=$!
    sleep 2

    if kill -0 "$BACKEND_PID" 2>/dev/null; then
        echo -e "${GREEN}  ✓ Backend running${NC} → http://localhost:${BACKEND_PORT}"
        echo -e "${GREEN}  ✓ API docs${NC}      → http://localhost:${BACKEND_PORT}/api/docs"
    else
        echo -e "${RED}  ✗ Backend failed to start${NC}"
        exit 1
    fi
}

start_frontend_dev() {
    echo -e "${BLUE}[2/2]${NC} Starting Vite dev server on port ${FRONTEND_PORT}..."
    cd "$PROJECT_ROOT/dashboard"
    npm run dev -- --port "$FRONTEND_PORT" &
    FRONTEND_PID=$!
    sleep 3

    if kill -0 "$FRONTEND_PID" 2>/dev/null; then
        echo -e "${GREEN}  ✓ Frontend running${NC} → http://localhost:${FRONTEND_PORT}"
    else
        echo -e "${RED}  ✗ Frontend failed to start${NC}"
        exit 1
    fi
}

start_frontend_prod() {
    echo -e "${BLUE}[2/2]${NC} Building and serving production frontend..."
    cd "$PROJECT_ROOT/dashboard"

    echo -e "  Building..."
    npm run build --silent 2>/dev/null

    echo -e "  Serving production build on port ${FRONTEND_PORT}..."
    npx serve dist -l "$FRONTEND_PORT" -s &
    FRONTEND_PID=$!
    sleep 2

    if kill -0 "$FRONTEND_PID" 2>/dev/null; then
        echo -e "${GREEN}  ✓ Frontend running${NC} → http://localhost:${FRONTEND_PORT}"
    else
        echo -e "${RED}  ✗ Frontend failed to start${NC}"
        exit 1
    fi
}

print_status() {
    echo ""
    echo -e "${CYAN}══════════════════════════════════════════════════════════════${NC}"
    echo -e "${GREEN}  Dashboard is ready!${NC}"
    echo ""
    echo -e "  ${BLUE}Frontend:${NC}  http://localhost:${FRONTEND_PORT}"
    echo -e "  ${BLUE}Backend:${NC}   http://localhost:${BACKEND_PORT}"
    echo -e "  ${BLUE}API docs:${NC}  http://localhost:${BACKEND_PORT}/api/docs"
    echo ""
    echo -e "  ${YELLOW}Press Ctrl+C to stop all services${NC}"
    echo -e "${CYAN}══════════════════════════════════════════════════════════════${NC}"
    echo ""
}

# Parse arguments
MODE="dev"
BACKEND_ONLY=false
FRONTEND_ONLY=false

for arg in "$@"; do
    case $arg in
        --prod|--production) MODE="prod" ;;
        --backend) BACKEND_ONLY=true ;;
        --frontend) FRONTEND_ONLY=true ;;
        --help|-h)
            echo "Usage: $0 [--prod|--backend|--frontend]"
            echo ""
            echo "Options:"
            echo "  (no args)    Start both backend + frontend (dev mode)"
            echo "  --prod       Start backend + serve production build"
            echo "  --backend    Start backend only"
            echo "  --frontend   Start frontend only"
            exit 0
            ;;
    esac
done

print_banner

if [ "$FRONTEND_ONLY" = true ]; then
    start_frontend_dev
    print_status
    wait
elif [ "$BACKEND_ONLY" = true ]; then
    start_backend
    echo ""
    echo -e "${YELLOW}Press Ctrl+C to stop${NC}"
    wait
else
    start_backend
    if [ "$MODE" = "prod" ]; then
        start_frontend_prod
    else
        start_frontend_dev
    fi
    print_status
    wait
fi
