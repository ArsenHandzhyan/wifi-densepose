#!/bin/sh

set -eu

PORT="${PORT:-8000}"
BACKEND_URL="${BACKEND_URL:-http://127.0.0.1:${PORT}}"
FP2_POLL_INTERVAL="${FP2_POLL_INTERVAL:-1}"
FP2_MONITOR_LOG_LEVEL="${FP2_MONITOR_LOG_LEVEL:-INFO}"

BACKEND_PID=""
MONITOR_PID=""

cleanup() {
  if [ -n "${MONITOR_PID:-}" ]; then
    kill "${MONITOR_PID}" >/dev/null 2>&1 || true
  fi
  if [ -n "${BACKEND_PID:-}" ]; then
    kill "${BACKEND_PID}" >/dev/null 2>&1 || true
  fi
}

trap cleanup INT TERM EXIT

echo "Starting Render FP2 backend on port ${PORT}"
uvicorn src.app:app --host 0.0.0.0 --port "${PORT}" &
BACKEND_PID=$!

for _ in $(seq 1 30); do
  if curl -sf "${BACKEND_URL}/health/live" >/dev/null 2>&1; then
    break
  fi
  sleep 1
done

if ! curl -sf "${BACKEND_URL}/health/live" >/dev/null 2>&1; then
  echo "Backend did not become healthy on ${BACKEND_URL}" >&2
  exit 1
fi

echo "Starting Aqara Cloud monitor against ${BACKEND_URL}"
python3 /app/scripts/fp2_aqara_cloud_monitor.py \
  --backend "${BACKEND_URL}" \
  --interval "${FP2_POLL_INTERVAL}" \
  --log-level "${FP2_MONITOR_LOG_LEVEL}" &
MONITOR_PID=$!

wait "${BACKEND_PID}"
