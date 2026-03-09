# Aqara FP2 Documentation Index

This repository no longer treats `Matter`, `Google Home`, or `SmartThings` as the active integration path for this workspace.

The authoritative runtime path on this machine is:

`Aqara FP2 -> Aqara Open API -> scripts/fp2_aqara_cloud_monitor.py -> FastAPI backend -> UI`

## Read This First

1. [`FP2_RUNTIME_STATUS_2026-03-09.md`](FP2_RUNTIME_STATUS_2026-03-09.md)
   The current verified runtime status, local runbook, Render deployment, backend room-layout persistence, and known limits.

2. [`FP2_INTEGRATION_FINAL_STATUS.md`](FP2_INTEGRATION_FINAL_STATUS.md)
   Historical investigation summary explaining why the project was narrowed from multiple experimental paths to the current FP2 monitor.

3. [`LOCAL_ARCHIVE.md`](LOCAL_ARCHIVE.md)
   Explains where removed legacy files are kept locally if they are not needed in the tracked runtime.

4. [`FP2_RUNTIME_STATUS_2026-03-07.md`](FP2_RUNTIME_STATUS_2026-03-07.md)
   Previous runtime snapshot kept for historical comparison.

## Current Status

- `FP2` is currently monitored through Aqara Open API and pushed into the local backend.
- The UI is now `FP2-only` and exposes only `Dashboard` and `FP2 Monitor`.
- Public Render deployment is live at [https://wifi-densepose-qtgc.onrender.com](https://wifi-densepose-qtgc.onrender.com).
- Render uses a single backend-served UI instead of a separate frontend service.
- Room profiles, templates, and items are persisted through backend `layout-state`, with `Export Layout` and `Import Layout` kept as backup/migration tools.
- Legacy CSI/DensePose materials were removed from the tracked runtime tree and moved into the local archive.
- `Home Assistant` can still exist locally, but the live UI no longer depends on HA polling for the working sensor path.

## Local R&D References

- [`ESP32_ROOM_SETUP_PLAN_2026-03-09.md`](ESP32_ROOM_SETUP_PLAN_2026-03-09.md)
  Local room deployment plan for the experimental `ESP32-S3 + FP2 + Keenetic` sensing stand. This is an exploratory document and not part of the active FP2 production runtime.

## What Is Intentionally Out Of Scope

- Recommending `Matter` as the primary path for this FP2 setup
- Treating `Google Home` or `SmartThings` as the live source of truth
- Reconstructing the exact Aqara mobile floorplan from public API data

## Local-Only Artifacts

- `.fp2_pairing.json` is a local pairing artifact and must not be committed.
- `.fp2_homekit_code` stores the one-time HomeKit code for automatic re-pair and must not be committed.
- `.env` contains secrets and local settings and must not be committed.

## Notes

If a document in `docs/` still describes `Matter`, `Google Home`, `SmartThings`, or direct `HAP` as the recommended next step, treat it as historical unless it explicitly references the active cloud monitor path above.

If a document says that Render or cloud mode cannot show fresh target coordinates, treat that as historical too. The current runtime keeps `4.22.85` enabled and the UI now polls `/api/v1/fp2/current` in `aqara_cloud` mode.
