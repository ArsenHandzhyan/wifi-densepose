# Aqara FP2 Local Monitor

This repository is currently maintained in a single purpose mode:

`Aqara FP2 -> Aqara Open API -> scripts/fp2_aqara_cloud_monitor.py -> FastAPI backend -> UI`

The old CSI / DensePose / WiFi sensing experiments are not part of the active runtime anymore.

## Active Runtime

Kept in git:
- `v1/src/` — active backend
- `ui/` — active UI
- `scripts/aqara_api_probe.py` — Aqara API diagnostics
- `scripts/fp2_aqara_cloud_monitor.py` — live FP2 cloud monitor
- `scripts/start_fp2_stack.sh` — local startup entrypoint
- `docker-compose.yml` — minimal local stack
- `render.yaml` — Render deployment
- `docs/FP2_RUNTIME_STATUS_2026-03-07.md`
- `docs/FP2_INTEGRATION_FINAL_STATUS.md`
- `docs/README_FP2_DOCS.md`
- `docs/LOCAL_ARCHIVE.md`

Moved out of git-tracked runtime:
- legacy CSI code
- Home Assistant and Homebridge experiments
- old deployment variants
- one-off probes and reverse-engineering scripts
- historical docs and backups

Those materials are stored only in the local ignored folder:
- `.local-archive/`

## Local Start

1. Start backend and cloud monitor:

```bash
./scripts/start_fp2_stack.sh
```

2. Start UI:

```bash
cd ui
./start-ui.sh
```

3. Open:
- `http://127.0.0.1:8000/api/v1/fp2/status`
- `http://127.0.0.1:8000/api/v1/fp2/current`
- `http://127.0.0.1:3000`

## Runtime Notes

- Current live source is `aqara_cloud`.
- Direct `HAP` pairing was investigated separately and is documented, but it is not the active runtime path.
- Secrets remain local and ignored:
  - `.env`
  - `.fp2_pairing.json`
  - `.fp2_homekit_code`
  - `.fp2_pairing.backup.*.json`

## Documentation

- [Runtime Status](docs/FP2_RUNTIME_STATUS_2026-03-07.md)
- [Integration Status](docs/FP2_INTEGRATION_FINAL_STATUS.md)
- [Docs Index](docs/README_FP2_DOCS.md)
- [Local Archive](docs/LOCAL_ARCHIVE.md)
