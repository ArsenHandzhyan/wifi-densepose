# FP2 Runtime Status

Date: 2026-03-09

This is the current authoritative runtime status for this workspace.

## Active Architecture

Verified live path:

`Aqara FP2 -> Aqara Open API -> scripts/fp2_aqara_cloud_monitor.py -> FastAPI backend -> UI`

This is the only actively maintained telemetry path in the tracked runtime.

## Verified Device

- Device: `Aqara Presence Sensor FP2`
- Model: `PS-SO2RU`
- Device ID: `54EF4479E003`
- Cloud DID: `lumi1.54ef4479e003`
- Aqara API domain: `open-ger.aqara.com`

## Runtime Topology

### Local

- Backend: `http://127.0.0.1:8000`
- UI: `http://127.0.0.1:3000`
- Start backend + cloud monitor: `./scripts/start_fp2_stack.sh`
- Start UI: `cd ui && ./start-ui.sh`

### Render

- Public URL: [https://wifi-densepose-qtgc.onrender.com](https://wifi-densepose-qtgc.onrender.com)
- Deployment model: single Render `web service`
- UI is served by the backend from `v1/src/app.py`
- The container starts both `uvicorn` and `scripts/fp2_aqara_cloud_monitor.py`
- Render startup materializes a runtime env file for the monitor, so Aqara token refresh and coordinate keepalive work without a committed `.env`
- Public API shares the same origin as the UI
- Free-tier cold starts remain possible after idle periods

## What Works

- Aqara token refresh and live cloud polling
- Backend ingestion of normalized FP2 payloads
- Continuous coordinate upload keepalive through `4.22.85`
- Live current-state API:
  - `/api/v1/fp2/status`
  - `/api/v1/fp2/current`
- Render deployment with working public UI and API
- Scenario presets:
  - presence + room map
  - corridor / directional flow
  - fall safety
  - bedside / sleep telemetry
- Room profile and room-item transfer through `Export Layout` / `Import Layout`
- Backend layout persistence through `/api/v1/fp2/layout-state`
- Optional Cloudflare R2 persistence for room layouts when `CLOUDFLARE_R2_*` is configured

## Important Runtime Improvements Since 2026-03-07

- Render now runs as a single-service deployment instead of requiring a separate worker
- Render now starts the cloud monitor inside the same web service, instead of relying only on on-demand refresh
- Backend refreshes Aqara Cloud snapshots before stale fallback in cloud mode
- `/api/v1/fp2/current` now falls back to the last cached Aqara snapshot if a direct cloud refresh fails, instead of breaking the UI with `502`
- The backend persists the last successful Aqara cloud snapshot, so Render can still draw a stale target map after short auth or rate-limit failures
- UI in cloud mode now polls `/api/v1/fp2/current`, which fixed stale target coordinates on Render
- Layout export/import was added so existing browser-local room configuration can be moved into backend-backed storage
- Scenario application now handles bedside reset more explicitly when switching away from sleep mode

## Current UI Scope

The active UI is intentionally limited to:

- `Dashboard`
- `FP2 Monitor`

The runtime UI now focuses on:

- presence
- target coordinates
- movement event codes
- zone occupancy
- zone analytics
- room map and room items
- Aqara Home parity surfaces that are actually backed by public data
- device scenarios and applied resource presets
- raw resource channels

## API Reality

The working source of truth is currently `aqara_cloud`.

Expected live markers:

- `metadata.source = "aqara_cloud"`
- `status.source = "aqara_cloud"`
- `status.connection.transport = "aqara_cloud"`

Useful local endpoints:

- `http://127.0.0.1:8000/health/live`
- `http://127.0.0.1:8000/api/v1/fp2/status`
- `http://127.0.0.1:8000/api/v1/fp2/current`
- `http://127.0.0.1:3000`

Useful public endpoints:

- [https://wifi-densepose-qtgc.onrender.com/health/live](https://wifi-densepose-qtgc.onrender.com/health/live)
- [https://wifi-densepose-qtgc.onrender.com/api/v1/fp2/status](https://wifi-densepose-qtgc.onrender.com/api/v1/fp2/status)
- [https://wifi-densepose-qtgc.onrender.com/api/v1/fp2/current](https://wifi-densepose-qtgc.onrender.com/api/v1/fp2/current)

## Local Commands

Start the active local stack:

```bash
./scripts/start_fp2_stack.sh
```

Start the local UI:

```bash
cd ui
./start-ui.sh
```

Run the cloud monitor directly:

```bash
python3 scripts/fp2_aqara_cloud_monitor.py --backend http://127.0.0.1:8000 --interval 1 --log-level INFO
```

Probe Aqara API access:

```bash
python3 scripts/aqara_api_probe.py probe --refresh-first
```

Exchange a fresh Aqara auth code into `.env`:

```bash
python3 scripts/aqara_api_probe.py exchange-auth-code 123456 --write-env
```

## Room Layout Storage

Room profiles, calibration, templates, and items are stored through the backend endpoint:

- `GET /api/v1/fp2/layout-state`
- `PUT /api/v1/fp2/layout-state`

Current behavior:

- Render can persist layout state in PostgreSQL when `DATABASE_URL` is configured
- the backend falls back to SQLite or file storage if the primary database is unavailable
- local and Render can still exchange layouts explicitly through `Export Layout` and `Import Layout`
- the UI shows which storage backend is currently active for the room editor
- saving a room template or editing room items triggers immediate server-side persistence, not only browser-local state

This is now a real server-side persistence layer, with file export/import still available as backup or migration tooling.

## Current Constraints

### Bedside / body telemetry

The bedside-related channels are visible but not fully writable through public API.

Current behavior:

- `14.58.85` can be written for bedside installation position
- the actual respiration/body channels are still effectively `read/report`
- selecting or applying the bedside scenario does not guarantee respiration or heart telemetry
- real bedside placement and Aqara app/cloud behavior still matter

### Aqara mobile parity

Still not available as a stable public API:

- the exact Aqara mobile room/floorplan scene graph
- full server-side room editor state from Aqara app
- all app-only features such as full AI Learning or Find Device control

### Render

- Public access works
- Render free tier can still sleep after inactivity
- first request after idle can be slower because of cold start

## Historical Notes

Some older documents in `docs/` predate the current cloud keepalive and Render deployment.

In particular, older notes that describe the runtime as permanently blocked on stale coordinates should be treated as historical investigation context, not as the current state.

## Bottom Line

The repository is now operating as a cloud-backed `Aqara FP2` telemetry console with:

- local developer runtime
- public Render deployment
- working target coordinates in cloud mode
- scenario presets
- file-based room-layout transfer between local and public UI

The next major gap is no longer basic room persistence. It is deeper multi-user synchronization and richer backend model/versioning for room layouts and items.
