#!/usr/bin/env bash
set -euo pipefail

TIER="${1:-all}"
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"

start_browsing() {
    echo "Starting Tier 2 — Browsing Service on :8001..."
    cd "$SCRIPT_DIR/browsing-service"
    uv sync
    uv run uvicorn app.main:app --port 8001 --reload &
    BROWSING_PID=$!
    echo "Browsing service PID: $BROWSING_PID"
}

start_n1() {
    echo "Starting Tier 3 — n1 Deep Service on :8002..."
    cd "$SCRIPT_DIR/n1-service"
    uv sync
    uv run playwright install chromium 2>/dev/null || true
    uv run uvicorn app.main:app --port 8002 --reload &
    N1_PID=$!
    echo "n1 service PID: $N1_PID"
}

cleanup() {
    echo "Shutting down services..."
    [ -n "${BROWSING_PID:-}" ] && kill "$BROWSING_PID" 2>/dev/null || true
    [ -n "${N1_PID:-}" ] && kill "$N1_PID" 2>/dev/null || true
    exit 0
}

trap cleanup SIGINT SIGTERM

case "$TIER" in
    2)
        start_browsing
        ;;
    3)
        start_n1
        ;;
    all|*)
        start_browsing
        start_n1
        ;;
esac

echo ""
echo "Services running. Press Ctrl+C to stop."
wait
