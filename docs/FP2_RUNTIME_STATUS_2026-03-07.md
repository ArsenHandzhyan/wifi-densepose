# FP2 Runtime Status

Date: 2026-03-07

This is the authoritative runtime status for the current workspace.

## Active Architecture

`Aqara FP2 -> HomeKit/HAP -> scripts/fp2_hap_client.py -> FastAPI backend -> UI`

This path is local-first and does not depend on `Matter`, `SmartThings`, `Google Home`, or `Aqara Cloud` for live telemetry.

## Verified Device

- Device: `Aqara Presence Sensor FP2`
- Model: `PS-SO2RU`
- Device ID: `54EF4479E003`
- MAC: `54:EF:44:79:E0:03`
- Local IP: `192.168.1.52`

## What Works

- Direct `HomeKit/HAP` pairing to the physical FP2
- Live presence updates pushed into the backend
- Live light level updates pushed into the backend
- Fixed single-device UI bound to `hap_direct`
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

The working source of truth is `hap_direct`.

Expected fields in the active runtime:

- `metadata.source = "hap_direct"`
- `metadata.entity_id = "hap_direct"`
- `status.hap_connected = true`
- `status.connection.transport = "hap_direct"`

Useful local endpoints:

- `http://127.0.0.1:8000/api/v1/fp2/status`
- `http://127.0.0.1:8000/api/v1/fp2/current`
- `http://127.0.0.1:8000/api/v1/fp2/hap-status`
- `http://127.0.0.1:3000`

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

Direct `HAP` does not expose the exact Aqara mobile map model.

Available directly:

- occupancy / presence
- ambient light
- occupancy-channel style zones

Not available directly:

- exact person coordinates
- Aqara mobile floorplan geometry
- full app-defined room layout metadata

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

Run the direct HAP monitor:

```bash
python3 scripts/fp2_hap_client.py monitor --backend http://127.0.0.1:8000 --interval 1.0
```

Store the HomeKit code once for automatic re-pair after Wi-Fi or modem changes:

```bash
python3 scripts/fp2_hap_client.py set-code
```

Inspect the paired device:

```bash
python3 scripts/fp2_hap_client.py info
```

## Local-Only Files

- `.fp2_pairing.json` stores local HomeKit pairing state and must not be committed
- `.fp2_homekit_code` stores the local HomeKit code used for automatic re-pair and must not be committed
- `.env` stores local secrets and must not be committed

## Deprecated Paths For This Workspace

These paths are historical investigation branches, not the active runtime:

- `Matter`
- `Google Home`
- `SmartThings`
- `Aqara Cloud API polling`
- `Home Assistant helper/entity selection as the primary live source`

## Bottom Line

The repository is now operating as a local `Aqara FP2` monitor with a cleaned `FP2-only` UI and direct `HAP` telemetry.
