#!/bin/bash

set -euo pipefail

echo "Starting Aqara FP2 UI"
echo "  UI:      http://127.0.0.1:3000"
echo "  Backend: http://127.0.0.1:8000"
echo

if lsof -Pi :3000 -sTCP:LISTEN -t >/dev/null 2>&1; then
  echo "Port 3000 is already in use."
  exit 1
fi

if ! curl -sf http://127.0.0.1:8000/health/live >/dev/null 2>&1; then
  echo "Backend is not healthy on port 8000."
  echo "Start it from the repository root with:"
  echo "  ./scripts/start_fp2_stack.sh"
fi

echo "Serving UI on port 3000"
exec python3 -m http.server 3000
