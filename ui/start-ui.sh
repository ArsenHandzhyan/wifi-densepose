#!/bin/bash

# WiFi DensePose UI Startup Script
# This script starts the UI on port 3000 to avoid conflicts with the FastAPI backend on port 8000

echo "🚀 Starting WiFi DensePose UI..."
echo ""
echo "📋 Configuration:"
echo "   - CSI Operator UI: http://127.0.0.1:3000/csi-operator.html"
echo "   - CSI Live Console: http://127.0.0.1:3000/csi-live.html"
echo "   - UI Server Root: http://127.0.0.1:3000"
echo "   - Canonical Backend API: http://127.0.0.1:8000"
echo "   - Canonical backend launch: uvicorn src.app:app --app-dir /Users/arsen/Desktop/wifi-densepose/v1 --host 127.0.0.1 --port 8000"
echo "   - Test Runner: http://localhost:3000/tests/test-runner.html"
echo "   - Integration Tests: http://localhost:3000/tests/integration-test.html"
echo ""

# Check if port 3000 is already in use
if lsof -Pi :3000 -sTCP:LISTEN -t >/dev/null ; then
    echo "⚠️  Port 3000 is already in use. Please stop the existing server or use a different port."
    echo "   You can manually start with: python3 dev_server.py"
    exit 1
fi

# Check if FastAPI backend is running on port 8000
BACKEND_PIDS=$(lsof -nP -iTCP:8000 -sTCP:LISTEN -t | sort -u)
BACKEND_COUNT=$(echo "${BACKEND_PIDS}" | sed '/^$/d' | wc -l | tr -d ' ')

if [ "${BACKEND_COUNT}" -gt 1 ]; then
    echo "❌ Найдено несколько backend-процессов на :8000. UI target двусмысленный."
    echo ""
    ps -p ${BACKEND_PIDS} -o pid=,command=
    echo ""
    echo "Оставь только канонический backend:"
    echo "   uvicorn src.app:app --app-dir /Users/arsen/Desktop/wifi-densepose/v1 --host 127.0.0.1 --port 8000"
    exit 1
elif [ "${BACKEND_COUNT}" -eq 1 ]; then
    BACKEND_CMD=$(ps -p ${BACKEND_PIDS} -o command=)
    if echo "${BACKEND_CMD}" | grep -q "src.app:app --app-dir /Users/arsen/Desktop/wifi-densepose/v1 --host 127.0.0.1 --port 8000"; then
        echo "✅ Канонический FastAPI backend detected on port 8000"
    else
        echo "❌ На :8000 найден неканонический backend target:"
        echo "   ${BACKEND_CMD}"
        echo ""
        echo "Нужен launch path:"
        echo "   uvicorn src.app:app --app-dir /Users/arsen/Desktop/wifi-densepose/v1 --host 127.0.0.1 --port 8000"
        exit 1
    fi
else
    echo "⚠️  FastAPI backend not detected on port 8000"
    echo "   Start canonical runtime with:"
    echo "   uvicorn src.app:app --app-dir /Users/arsen/Desktop/wifi-densepose/v1 --host 127.0.0.1 --port 8000"
    echo ""
    echo "   The UI will still work with the mock server for testing."
fi

echo ""
echo "🌐 Starting UI dev server on port 3000..."
echo "   Press Ctrl+C to stop"
echo ""

# Start the UI server with forensic endpoints
python3 dev_server.py
