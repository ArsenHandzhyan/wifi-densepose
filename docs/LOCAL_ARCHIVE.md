# Local Archive

This workspace uses a local-only archive for historical materials that are no longer required by the active FP2 application runtime.

Archive path:

`/.local-archive/`

Rules:

- The archive is ignored by git and is never pushed.
- Files moved there are kept only as local reference material.
- The active repository should contain only the files required for the current FP2 application runtime.

What is typically stored there:

- legacy CSI / DensePose code
- Home Assistant and Homebridge experiments
- old deployment manifests and infrastructure files
- one-off debug scripts and reverse-engineering probes
- local coding-agent and editor metadata that is not part of the app runtime

Current active runtime:

`Aqara FP2 -> Aqara Open API -> scripts/fp2_aqara_cloud_monitor.py -> FastAPI backend -> UI`
