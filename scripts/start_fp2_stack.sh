#!/bin/bash

set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT_DIR"

BACKEND_LOG="/tmp/wifi-densepose-backend.log"
MONITOR_LOG="/tmp/wifi-densepose-cloud-monitor.log"
BACKEND_PID=""
MONITOR_PID=""

cleanup() {
  if [ -n "${MONITOR_PID}" ] && kill -0 "${MONITOR_PID}" >/dev/null 2>&1; then
    kill "${MONITOR_PID}" >/dev/null 2>&1 || true
  fi
  if [ -n "${BACKEND_PID}" ] && kill -0 "${BACKEND_PID}" >/dev/null 2>&1; then
    kill "${BACKEND_PID}" >/dev/null 2>&1 || true
  fi
}

trap cleanup EXIT INT TERM

if [ ! -d "$ROOT_DIR/venv" ]; then
  echo "Missing virtualenv at $ROOT_DIR/venv"
  echo "Create it first: python3 -m venv venv && source venv/bin/activate && pip install -r requirements.render.txt"
  exit 1
fi

source "$ROOT_DIR/venv/bin/activate"

export PYTHONPATH="$ROOT_DIR/v1"
export FP2_ENABLED="${FP2_ENABLED:-true}"
export ENABLE_REAL_TIME_PROCESSING="${ENABLE_REAL_TIME_PROCESSING:-false}"

echo "Starting backend..."
nohup uvicorn src.app:app --host 127.0.0.1 --port 8000 >"$BACKEND_LOG" 2>&1 &
BACKEND_PID=$!

for _ in $(seq 1 20); do
  if curl -sf http://127.0.0.1:8000/health/live >/dev/null 2>&1; then
    break
  fi
  sleep 1
done

if ! curl -sf http://127.0.0.1:8000/health/live >/dev/null 2>&1; then
  echo "Backend did not become healthy. Log: $BACKEND_LOG"
  exit 1
fi

echo "Starting Aqara Cloud monitor..."
nohup python3 "$ROOT_DIR/scripts/fp2_aqara_cloud_monitor.py" \
  --backend http://127.0.0.1:8000 \
  --interval "${FP2_POLL_INTERVAL:-1}" \
  --log-level INFO >"$MONITOR_LOG" 2>&1 &
MONITOR_PID=$!

echo
echo "FP2 stack started"
echo "  Backend: http://127.0.0.1:8000"
echo "  UI:      http://127.0.0.1:3000"
echo "  Backend log: $BACKEND_LOG"
echo "  Monitor log: $MONITOR_LOG"
echo
echo "Press Ctrl+C to stop both processes."

wait "$BACKEND_PID"
