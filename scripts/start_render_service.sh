#!/bin/sh

set -eu

PORT="${PORT:-8000}"
BACKEND_URL="${BACKEND_URL:-http://127.0.0.1:${PORT}}"
FP2_POLL_INTERVAL="${FP2_POLL_INTERVAL:-1}"
FP2_MONITOR_LOG_LEVEL="${FP2_MONITOR_LOG_LEVEL:-INFO}"
RUNTIME_ENV_FILE="${FP2_RUNTIME_ENV_FILE:-/tmp/fp2_runtime.env}"

BACKEND_PID=""
MONITOR_PID=""
MONITOR_RESTART_DELAY="${FP2_MONITOR_RESTART_DELAY:-5}"

write_runtime_env_file() {
  : > "${RUNTIME_ENV_FILE}"
  chmod 600 "${RUNTIME_ENV_FILE}" >/dev/null 2>&1 || true
  for key in \
    AQARA_EMAIL \
    AQARA_PASSWORD \
    AQARA_API_DOMAIN \
    AQARA_APP_ID \
    AQARA_APP_KEY \
    AQARA_KEY_ID \
    AQARA_ACCESS_TOKEN \
    AQARA_REFRESH_TOKEN \
    AQARA_OPEN_ID \
    AQARA_ACCESS_TOKEN_EXPIRES \
    FP2_DEVICE_ID \
    FP2_NAME \
    FP2_MODEL \
    FP2_FIRMWARE
  do
    eval "value=\${${key}:-}"
    if [ -n "${value}" ]; then
      printf '%s=%s\n' "${key}" "${value}" >> "${RUNTIME_ENV_FILE}"
    fi
  done
}

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

write_runtime_env_file
echo "Starting Aqara Cloud monitor against ${BACKEND_URL} using ${RUNTIME_ENV_FILE}"
(
  while true; do
    echo "Launching Aqara Cloud monitor loop"
    python3 /app/scripts/fp2_aqara_cloud_monitor.py \
      --env-file "${RUNTIME_ENV_FILE}" \
      --backend "${BACKEND_URL}" \
      --interval "${FP2_POLL_INTERVAL}" \
      --log-level "${FP2_MONITOR_LOG_LEVEL}"
    EXIT_CODE=$?
    echo "Aqara Cloud monitor exited with code ${EXIT_CODE}; restarting in ${MONITOR_RESTART_DELAY}s"
    sleep "${MONITOR_RESTART_DELAY}"
  done
) &
MONITOR_PID=$!

wait "${BACKEND_PID}"
