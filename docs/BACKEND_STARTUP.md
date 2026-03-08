# Backend Manual Startup Instructions

## Quick Start

```bash
cd /Users/arsen/Desktop/wifi-densepose

# Option 1: Use startup script
./scripts/start_backend.sh

# Option 2: Manual start
source venv/bin/activate  # or .venv/bin/activate
PYTHONPATH=. uvicorn src.app:app --host 0.0.0.0 --port 8000 --reload
```

## Step-by-Step Manual Launch

### 1. Find Python Environment

```bash
# Check for virtual environment
ls -la | grep -E "venv|env"

# If exists, activate it
source venv/bin/activate
# OR
source .venv/bin/activate

# If no venv, use system Python
which python3
```

### 2. Install Dependencies (if needed)

```bash
pip install -r requirements.render.txt
# OR
pip3 install fastapi uvicorn requests python-dotenv
```

### 3. Kill Existing Processes

```bash
pkill -f "uvicorn src.app"
pkill -f "fp2_aqara_cloud_monitor"
```

### 4. Start Backend

```bash
cd /Users/arsen/Desktop/wifi-densepose
PYTHONPATH=. uvicorn src.app:app --host 0.0.0.0 --port 8000 --reload
```

### 5. Verify Backend is Running

Open new terminal window:

```bash
# Test health endpoint
curl -sf http://127.0.0.1:8000/health/live && echo "✅ OK"

# Test FP2 API
curl -s http://127.0.0.1:8000/api/v1/fp2/current | python3 -m json.tool | head -20
```

## Common Issues

### Issue: ModuleNotFoundError

```bash
# Install required packages
pip install fastapi uvicorn requests python-dotenv aiohttp
```

### Issue: Port 8000 already in use

```bash
# Find process using port 8000
lsof -i :8000

# Kill it
kill -9 <PID>
# OR
pkill -f "port.*8000"
```

### Issue: Backend starts but doesn't respond

```bash
# Check if process is running
ps aux | grep uvicorn

# Check logs
tail -f /tmp/backend.log

# Try without --reload flag
PYTHONPATH=. uvicorn src.app:app --host 0.0.0.0 --port 8000
```

## Background Mode

```bash
# Start in background
nohup uvicorn src.app:app --host 0.0.0.0 --port 8000 > /tmp/backend.log 2>&1 &

# Save PID
echo $! > /tmp/backend.pid

# Check status
curl -sf http://127.0.0.1:8000/health/live

# Stop later
kill $(cat /tmp/backend.pid)
```

## Full Stack Launch

To launch everything together:

```bash
cd /Users/arsen/Desktop/wifi-densepose

# Start backend
./scripts/start_backend.sh &

# Wait for backend
sleep 5

# Start cloud monitor
python3 scripts/fp2_aqara_cloud_monitor.py --backend http://127.0.0.1:8000 &

# Start UI (in separate terminal)
cd ui
python3 -m http.server 3000
```

## Verification Checklist

After startup, verify:

- [ ] Backend responds: `curl http://127.0.0.1:8000/health/live`
- [ ] FP2 data available: `curl http://127.0.0.1:8000/api/v1/fp2/current`
- [ ] No errors in log: `tail /tmp/backend.log`
- [ ] Process running: `ps aux | grep uvicorn`
- [ ] UI can connect: Open http://127.0.0.1:3000 and check "Backend connection"

## Environment Variables

Check `.env` file exists with required variables:

```bash
cat .env | grep -E "AQARA|API"
```

Required:
- AQARA_ACCESS_TOKEN
- AQARA_REFRESH_TOKEN
- AQARA_OPEN_ID
- AQARA_API_DOMAIN (e.g., open-ger.aqara.com)

## Logs Location

- Backend: `/tmp/backend.log`
- Cloud Monitor: `/tmp/wifi-densepose-cloud-monitor.log`
- UI: `/tmp/ui.log`

View logs in real-time:

```bash
tail -f /tmp/backend.log
```

## Service Status Script

Create quick status check:

```bash
#!/bin/bash
echo "Backend: $(curl -sf http://127.0.0.1:8000/health/live && echo '✅' || echo '❌')"
echo "UI: $(curl -sf http://127.0.0.1:3000 && echo '✅' || echo '❌')"
echo "Cloud Monitor: $(pgrep -f fp2_aqara_cloud_monitor && echo '✅' || echo '❌')"
```
