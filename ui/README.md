# Aqara FP2 Local Monitor UI

This UI is no longer a general-purpose `WiFi DensePose` demo surface.

It is now the front end for the verified local runtime:

`Aqara FP2 -> HomeKit/HAP -> FastAPI backend -> UI`

## Current Scope

The main UI exposes only two tabs:

- `Dashboard`
- `FP2 Monitor`

The interface is fixed to a single paired device and does not expose:

- entity selection
- mock backend selection
- CSI hardware configuration panels
- live demo controls for the old pose pipeline

## Backend Assumptions

The UI expects a live backend that serves:

- `/health/live`
- `/api/v1/info`
- `/api/v1/fp2/status`
- `/api/v1/fp2/current`
- `/api/v1/fp2/ws`

When opened on `localhost` or `127.0.0.1`, the UI defaults to `http://127.0.0.1:8000`.

## What The FP2 Monitor Shows

- connection state
- transport
- device metadata
- presence state
- light level
- zone windows
- movement events
- movement map
- real-time presence graph
- raw payload

The active data source is expected to be:

- `source = hap_direct`
- `entity_id = hap_direct`

## Important Limitation

Direct `HomeKit/HAP` telemetry does not provide the exact Aqara mobile floorplan or exact person coordinates.

The UI therefore shows an honest zone/occupancy representation instead of a fabricated clone of the Aqara app map.

## Local Development

Start the backend first, then serve the UI:

```bash
source venv/bin/activate
PYTHONPATH=. uvicorn src.app:app --host 0.0.0.0 --port 8000 --reload
cd ui
./start-ui.sh
```

Open:

- `http://127.0.0.1:3000`

## Repository Cleanup Notes

The following legacy modules were removed from the primary UI flow:

- `HardwareTab`
- `LiveDemoTab`
- mock backend detector
- mock WebSocket server
- old integration-test HTML page
