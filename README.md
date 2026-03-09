# Aqara FP2 Telemetry Console

This repository is currently maintained as a single-purpose `Aqara FP2` telemetry stack.

Active runtime:

`Aqara FP2 -> Aqara Open API -> scripts/fp2_aqara_cloud_monitor.py -> FastAPI backend -> UI`

The old CSI / DensePose / WiFi sensing experiments are not part of the active runtime anymore.

## Current Entry Points

- Public Render deployment: [https://wifi-densepose-qtgc.onrender.com](https://wifi-densepose-qtgc.onrender.com)
- Local backend: `http://127.0.0.1:8000`
- Local UI: `http://127.0.0.1:3000`

## What Works Now

- Aqara Open API auth and token refresh
- Live cloud-backed FP2 telemetry in the backend
- Continuous target coordinate upload via `4.22.85`
- `FP2 Monitor` and `Dashboard` as the only active UI surfaces
- Scenario presets for room, corridor, fall, and bedside modes
- Public Render deployment with backend-served UI
- Room/layout export from local UI and import into Render UI
- Backend-backed room/template/item persistence through `/api/v1/fp2/layout-state`

## Local Start

1. Start backend and Aqara Cloud monitor:

```bash
./scripts/start_fp2_stack.sh
```

2. Start the local UI in a second terminal:

```bash
cd ui
./start-ui.sh
```

3. Open:

- `http://127.0.0.1:8000/health/live`
- `http://127.0.0.1:8000/api/v1/fp2/status`
- `http://127.0.0.1:8000/api/v1/fp2/current`
- `http://127.0.0.1:3000`

## Render Deployment

The current production deployment is a single Render `web service`.

- The backend serves the UI directly from `v1/src/app.py`
- The same container now starts the Aqara Cloud monitor alongside the backend
- Render startup writes a runtime env file for the monitor, so token refresh and coordinate keepalive do not depend on a committed `.env`
- The public site and the API share the same origin
- No separate paid worker is required for the deployed runtime
- On Render free tier, cold starts after idle time are still possible

Current public site:

- [https://wifi-densepose-qtgc.onrender.com](https://wifi-densepose-qtgc.onrender.com)

Useful public endpoints:

- [https://wifi-densepose-qtgc.onrender.com/health/live](https://wifi-densepose-qtgc.onrender.com/health/live)
- [https://wifi-densepose-qtgc.onrender.com/api/v1/fp2/status](https://wifi-densepose-qtgc.onrender.com/api/v1/fp2/status)
- [https://wifi-densepose-qtgc.onrender.com/api/v1/fp2/current](https://wifi-densepose-qtgc.onrender.com/api/v1/fp2/current)

## Room Layout Persistence

Room profiles, calibration, templates, and room items are now written to backend storage through:

- `GET /api/v1/fp2/layout-state`
- `PUT /api/v1/fp2/layout-state`

Runtime behavior:

- On Render, when `DATABASE_URL` is set, layout state is stored in PostgreSQL
- If PostgreSQL is unavailable, the backend falls back to SQLite or file fallback depending on runtime
- The UI shows the active storage backend in the room-layout section
- Room templates and room items are saved server-side immediately after changes or template save actions

`Export Layout` / `Import Layout` are still available as an explicit backup and transfer path between browsers or environments.

Recommended migration flow from an older local browser state:

1. Open local UI at `http://127.0.0.1:3000`
2. Click `Export Layout`
3. Open Render UI at [https://wifi-densepose-qtgc.onrender.com](https://wifi-densepose-qtgc.onrender.com)
4. Click `Import Layout`
5. Select the exported JSON
6. Verify that the room-layout storage badge shows backend persistence instead of a temporary fallback

## Runtime Notes

- Current live transport is `aqara_cloud`
- The backend now refreshes cloud snapshots before stale fallback in cloud mode
- If direct cloud refresh fails on Render, `/api/v1/fp2/current` now falls back to the latest cached Aqara snapshot instead of returning `502`
- The UI now polls `/api/v1/fp2/current` in cloud mode so Render shows fresh target coordinates
- Render is intended to run the same cloud monitor loop as local startup so `4.22.85` stays enabled
- Direct `HomeKit/HAP` pairing was investigated, but it is not the active runtime path

## Secrets And Local Files

These files remain local and must not be committed:

- `.env`
- `.fp2_pairing.json`
- `.fp2_homekit_code`
- `.fp2_pairing.backup.*.json`

## Documentation

- [Current Runtime Status](docs/FP2_RUNTIME_STATUS_2026-03-09.md)
- [Previous Runtime Snapshot](docs/FP2_RUNTIME_STATUS_2026-03-07.md)
- [Integration Status](docs/FP2_INTEGRATION_FINAL_STATUS.md)
- [Docs Index](docs/README_FP2_DOCS.md)
- [Local Archive](docs/LOCAL_ARCHIVE.md)
