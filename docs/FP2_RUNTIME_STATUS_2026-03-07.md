# FP2 Runtime Status

Date: 2026-03-07

This is the authoritative runtime status for the current workspace.

## Active Architecture

`Aqara FP2 -> Aqara Open API -> scripts/fp2_aqara_cloud_monitor.py -> FastAPI backend -> UI`

This is the currently verified live telemetry path on this machine. It does not depend on `Matter`, `SmartThings`, or `Google Home`.

## Verified Device

- Device: `Aqara Presence Sensor FP2`
- Model: `PS-SO2RU`
- Device ID: `54EF4479E003`
- MAC: `54:EF:44:79:E0:03`
- Local IP: `192.168.1.52`

## What Works

- Aqara Open API token refresh and auth-code exchange
- Cloud DID resolution for the physical FP2: `lumi1.54ef4479e003`
- Live presence updates pushed into the backend
- Live target coordinates pushed into the backend
- Live light level and online/RSSI state pushed into the backend
- Fixed single-device UI bound to the active runtime source
- `Dashboard` rewritten for `FP2-only` mode
- `FP2 Monitor` rewritten as the primary operational view

## What The UI Now Shows

- backend health
- HAP link state
- device passport
- presence
- light level
- zone windows based on live occupancy channels
- movement event history
- movement map
- real-time presence graph
- raw payload

There is no longer any user-facing entity picker, mock-server toggle, or legacy CSI control surface in the main UI.

## API Reality

The working source of truth is currently `aqara_cloud`.

Expected fields in the active runtime:

- `metadata.source = "aqara_cloud"`
- `metadata.entity_id = "aqara_cloud"`
- `status.source = "aqara_cloud"`
- `status.stream_connected = true`
- `status.connection.transport = "aqara_cloud"`

Useful local endpoints:

- `http://127.0.0.1:8000/api/v1/fp2/status`
- `http://127.0.0.1:8000/api/v1/fp2/current`
- `http://127.0.0.1:3000`

Typical live fields now visible in `/api/v1/fp2/current`:

- `persons[0].bounding_box.x`
- `persons[0].bounding_box.y`
- `persons[0].distance`
- `persons[0].angle`
- `zone_summary.detection_area`
- `metadata.raw_attributes.light_level`
- `metadata.raw_attributes.rssi`
- `metadata.raw_attributes.online`

## Current UI Scope

The cleaned front end intentionally keeps only:

- `Dashboard`
- `FP2 Monitor`

The following legacy tabs were removed from the primary UI:

- `Hardware`
- `Live Demo`
- `Architecture`
- `Performance`
- `Applications`

## Current Runtime Constraints

The current cloud path returns presence, coordinates, light, online state, and movement/fall metadata, but not the exact Aqara mobile floorplan scene graph.

Available now:

- occupancy / presence
- active targets with coordinates
- ambient light
- movement and fall flags
- online state / RSSI
- zone occupancy channels

Not available as a stable public API:

- the exact Aqara mobile floorplan geometry
- full app-defined room layout metadata
- a reliable direct `HomeKit/HAP` pairing path from this Mac

Because of that, the repository renders an honest zone-window and occupancy view instead of pretending to reproduce the Aqara mobile map one-to-one.

## Local Commands

Start the backend:

```bash
source venv/bin/activate
PYTHONPATH=. uvicorn src.app:app --host 0.0.0.0 --port 8000 --reload
```

Start the UI:

```bash
cd ui
./start-ui.sh
```

Run the active cloud monitor:

```bash
python3 scripts/fp2_aqara_cloud_monitor.py --backend http://127.0.0.1:8000 --interval 2 --log-level INFO
```

Exchange a fresh Aqara auth code into `.env`:

```bash
python3 scripts/aqara_api_probe.py exchange-auth-code 123456 --write-env
```

Probe Aqara API access and current FP2 resources:

```bash
python3 scripts/aqara_api_probe.py probe --refresh-first
```

## Local-Only Files

- `.env` stores local secrets and must not be committed

## Deprecated Paths For This Workspace

These paths are historical investigation branches, not the active runtime:

- `Matter`
- `Google Home`
- `SmartThings`
- `direct HAP telemetry as the primary live source`
- `Home Assistant helper/entity selection as the primary live source`

## Bottom Line

The repository is now operating as an `Aqara FP2` monitor with a cleaned `FP2-only` UI and live telemetry delivered through Aqara Open API into the local backend.
