#!/bin/bash
# FP2 Stack Quick Restart Script
# Usage: ./scripts/restart_fp2.sh

set -e

echo "🔄 Stopping FP2 stack..."

# Kill existing processes
pkill -f "uvicorn src.app" 2>/dev/null || true
pkill -f "fp2_aqara_cloud_monitor" 2>/dev/null || true
pkill -f "http.server.*3000" 2>/dev/null || true

sleep 2

echo "✅ Processes stopped"
echo ""
echo "🚀 Starting FP2 stack..."
echo ""

# Start everything using the main script
bash scripts/start_fp2_stack.sh &

# Wait for backend to be ready
echo "Waiting for backend..."
for i in {1..30}; do
  if curl -sf http://127.0.0.1:8000/health/live >/dev/null 2>&1; then
    echo "✅ Backend is ready"
    break
  fi
  sleep 1
done

# Check UI
if curl -sf http://127.0.0.1:3000 >/dev/null 2>&1; then
  echo "✅ UI is running"
else
  echo "⚠️  UI not responding yet"
fi

echo ""
echo "======================================"
echo "FP2 Stack Status:"
echo "======================================"
echo "Backend:  http://127.0.0.1:8000"
echo "UI:       http://127.0.0.1:3000"
echo "Logs:     /tmp/wifi-densepose-*.log"
echo ""
echo "Open browser: http://127.0.0.1:3000"
echo "Press Ctrl+C to stop all services"
echo "======================================"
