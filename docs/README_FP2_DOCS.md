# Aqara FP2 Documentation Index

This repository no longer treats `Matter`, `Google Home`, `SmartThings`, or `Aqara Cloud polling` as the active integration path for this workspace.

The authoritative runtime path on this machine is:

`Aqara FP2 -> HomeKit/HAP -> scripts/fp2_hap_client.py -> FastAPI backend -> UI`

## Read This First

1. [`FP2_RUNTIME_STATUS_2026-03-07.md`](FP2_RUNTIME_STATUS_2026-03-07.md)
   The current verified runtime status, architecture, limits, and local commands.

2. [`FP2_INTEGRATION_FINAL_STATUS.md`](FP2_INTEGRATION_FINAL_STATUS.md)
   Historical investigation summary explaining why the project was narrowed to direct HAP.

## Current Status

- `FP2` is paired locally and monitored directly over `HomeKit/HAP`.
- The UI is now `FP2-only` and exposes only `Dashboard` and `FP2 Monitor`.
- `CSI/DensePose` content remains in the repo as legacy project context, not as the active runtime.
- `Home Assistant` can still exist locally, but the live UI no longer depends on HA polling for the working sensor path.

## What Is Intentionally Out Of Scope

- Recommending `Matter` as the primary path for this FP2 setup
- Treating `Google Home` or `SmartThings` as the live source of truth
- Using `Aqara Cloud API` as the active telemetry path
- Reconstructing the exact Aqara mobile floorplan from `HAP`

## Local-Only Artifacts

- `.fp2_pairing.json` is a local pairing artifact and must not be committed.
- `.env` contains secrets and local settings and must not be committed.

## Notes

If a document in `docs/` still describes `Matter`, `Google Home`, or `SmartThings` as the recommended next step, treat it as historical unless it explicitly references the direct `HAP` runtime path above.
