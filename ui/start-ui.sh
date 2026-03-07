#!/bin/bash

# Aqara FP2 Local Monitor UI Startup Script
# This script starts the FP2-only UI on port 3000 to avoid conflicts with the FastAPI backend on port 8000

echo "🚀 Starting Aqara FP2 Local Monitor UI..."
echo ""
echo "📋 Configuration:"
echo "   - UI Server: http://localhost:3000"
echo "   - Backend API: http://localhost:8000 (make sure it's running)"
echo ""

# Check if port 3000 is already in use
if lsof -Pi :3000 -sTCP:LISTEN -t >/dev/null ; then
    echo "⚠️  Port 3000 is already in use. Please stop the existing server or use a different port."
    echo "   You can manually start with: python -m http.server 3001"
    exit 1
fi

# Check if FastAPI backend is running on port 8000
if lsof -Pi :8000 -sTCP:LISTEN -t >/dev/null ; then
    echo "✅ FastAPI backend detected on port 8000"
else
    echo "⚠️  FastAPI backend not detected on port 8000"
    echo "   Start it manually from the repository root:"
    echo "   source venv/bin/activate && PYTHONPATH=. uvicorn src.app:app --host 0.0.0.0 --port 8000 --reload"
fi

echo ""
echo "🌐 Starting HTTP server on port 3000..."
echo "   Press Ctrl+C to stop"
echo ""

# Start the HTTP server
python -m http.server 3000
