# FP2 Real Movement Testing (Local)

This guide explains how to validate real movement tracking with Aqara FP2 + Home Assistant + WiFi-DensePose UI.

> Archival FP2/Aqara note (2026-03-29):
> this document belongs to an earlier FP2/Home Assistant integration line and
> is preserved only as historical reference for that thread.
> Any setup flow, status wording, endpoint examples, or device metadata below
> should be read as archival context rather than current repo truth.
> For the current canonical repo state and active entrypoints, use
> `/Users/arsen/Desktop/wifi-densepose/docs/CURRENT_DOCS_ENTRYPOINT_20260329.md`
> and `/Users/arsen/Desktop/wifi-densepose/docs/CURRENT_PROJECT_STATE_20260329.md`.

> **Note:** Aqara Cloud API is not available for Russia region (`open-ru.aqara.com` is unreachable). This guide uses Home Assistant API as the working alternative.

Session log with detailed chronology is stored in:

- `docs/session-history-2026-03-01.md`

## 1. What is real right now

With your current hardware, the system can show:

- real `presence` changes (present/absent),
- movement events (`ENTER`, `EXIT`, `MOVE`),
- current zone and duration of presence,
- real-time presence graph in UI and CLI,
- data logging to CSV for analysis,
- live updates in FP2 Monitor.

It cannot show real WiFi CSI skeletons from Keenetic GIGA, because this router does not expose CSI.

## 2. Required services

From project root:

```bash
cd /Users/arsen/Desktop/wifi-densepose

# Home Assistant
Docker Desktop must be running

docker compose up -d homeassistant

# Backend
source venv/bin/activate
PYTHONPATH=. uvicorn src.app:app --host 0.0.0.0 --port 8000 --reload

# UI (in another terminal)
cd /Users/arsen/Desktop/wifi-densepose/ui
python3 -m http.server 3000
```

## 3. URLs to open

- Home Assistant: [http://127.0.0.1:8123](http://127.0.0.1:8123)
- API docs: [http://127.0.0.1:8000/docs](http://127.0.0.1:8000/docs)
- UI: [http://127.0.0.1:3000](http://127.0.0.1:3000)

## 4. Where to get HA token

In Home Assistant web UI:

1. Open your profile (bottom-left user icon).
2. Go to `Security`.
3. In `Long-lived access tokens`, click `Create token`.
4. Copy the token once (HA will not show it again).

Put it into project `.env`:

```env
FP2_ENABLED=true
HA_URL=http://localhost:8123
HA_TOKEN=your_long_lived_access_token
FP2_ENTITY_ID=input_boolean.fp2_presence
FP2_POLL_INTERVAL=1.0
```

Then restart backend.

Optional credentials used in this local session are also stored in `.env`:

- `HA_USERNAME` / `HA_PASSWORD`
- `AQARA_EMAIL` / `AQARA_PASSWORD`
- `FP2_HOMEKIT_CODE` / `FP2_HOMEKIT_CODE_RAW`

## 5. How to check movement end-to-end

1. Open UI tab `FP2 Monitor`.
2. Confirm status is green:
   - API = Enabled
   - Stream = connected (or connecting then connected)
3. Move in FP2 coverage area.
4. Verify updates:
   - `Presence` switches to `PRESENT`.
   - `Current Zone` changes when you move between zones.
   - `Presence Duration` increments while you stay detected.
   - `Movement Events` receives `ENTER/EXIT/MOVE` records.
   - `Live Movement Map` shows projected movement points in real time.
   - `Real-time Presence Graph` shows presence history (last 60 seconds).

### UI Real-time Graph

The FP2 Monitor tab now includes a live canvas graph showing:
- Green line = presence detected
- Gray line = no presence
- Last 60 seconds of history
- Updates in real-time via WebSocket

### Auto-select mode (recommended)

If you are not sure which FP2 entity is best:

1. Open `FP2 Monitor`.
2. Click `Auto Select Entity`.
3. The UI requests `/api/v1/fp2/recommended-entity` and switches to the best candidate.
4. Stream reconnects automatically with `?entity_id=...`.

Optional direct API check:

```bash
curl -s http://127.0.0.1:8000/api/v1/fp2/current
curl -s http://127.0.0.1:8000/api/v1/fp2/status
```

### CLI Script (Alternative)

For quick status checks without UI, use the Python CLI script:

```bash
# Check current status
python3 scripts/fp2_ha_client.py

# Watch mode - real-time updates
python3 scripts/fp2_ha_client.py --watch

# Watch with custom interval (0.5 seconds)
python3 scripts/fp2_ha_client.py --watch -i 0.5
```

Expected output:
```
============================================================
  📡 FP2 СТАТУС
============================================================

   Entity:     input_boolean.fp2_presence
   Состояние:  🟢 ПРИСУТСТВИЕ ОБНАРУЖЕНО
   Обновлено:  2026-03-04T13:09:13.800868+00:00
```

### Motion Logger (Data Collection)

For recording FP2 data with network statistics:

```bash
# Record for 60 seconds to CSV
python3 scripts/fp2_motion_logger.py --duration 60

# Real-time visualization
python3 scripts/fp2_motion_logger.py --realtime

# Visualize saved data
python3 scripts/fp2_motion_logger.py --visualize
```

CSV format:
```
timestamp,fp2_state,ping_ms,packet_loss,event
2026-03-04T17:46:47.101199,on,,,MOTION_START
```

Data saved to: `data/fp2_motion_log.csv`

## 6. If FP2 Monitor is empty

Check in this order:

1. HA is running:

```bash
docker compose ps homeassistant
```

2. Token is valid (no 401 in backend logs).
3. Entity exists in HA (`input_boolean.fp2_presence` or your real FP2 entity).
4. Backend listens on `127.0.0.1:8000`.
5. Hard refresh browser (Safari cache can keep old JS).

## 7. Why Live Demo may be black

`Live Demo` canvas is for pose stream rendering and can be disconnected from FP2 monitor state.
For real FP2 validation, use `FP2 Monitor` as the source of truth.

## 8. Next step for true WiFi body/skeleton scanning

To get real WiFi-based skeleton from radio signals, you need CSI-capable hardware:

- ESP32 (ESP-CSI), or
- OpenWrt + supported Atheros chipset, or
- Nexmon-compatible Broadcom setup.

Then connect CSI stream to the pose inference pipeline.

## 9. Automatic migration of Home Assistant to Linux (recommended)

If HomeKit discovery does not work in Docker Desktop on macOS, migrate HA to Linux host/VM with bridged network.

Backup is already stored in:

- `backups/homeassistant/config-<timestamp>`

Run one-command migration script from project root:

```bash
./scripts/migrate_ha_to_linux.sh <user@linux-host> [ssh_port]
```

Example:

```bash
./scripts/migrate_ha_to_linux.sh user@<linux-host-ip>
```

After migration:

1. Open remote HA UI (`http://<linux-ip>:8123`).
2. Add `HomeKit Device` and pair FP2.
3. Update local `.env`:

```env
HA_URL=http://<linux-ip>:8123
HA_TOKEN=<new_token_from_remote_ha>
```

## 10. Fixed notes from current troubleshooting (2026-03-02)

This was confirmed during the latest run:

- FP2 LED behavior:
  - blinking = pairing mode (discoverable by HomeKit Device),
  - solid = already connected / not in pairing mode.
- For FP2 pairing checks, only `homeassistant` container is required.
  - `wifi-densepose`, `postgres`, `redis` can be stopped.
- In current environment, HA UI often shows:
  - `HomeKit Device -> devices not found`.

### Minimal command set used in this state

```bash
cd /Users/arsen/Desktop/wifi-densepose

# leave only HA running
docker compose stop wifi-densepose postgres redis
docker compose ps
```

Expected result:

- only `wifi-densepose-ha` is `Up (healthy)` on port `8123`.

### Practical pairing sequence (must be followed in order)

1. Open HA in Chrome: `http://127.0.0.1:8123`.
2. Put FP2 into pairing mode until LED blinks.
3. Immediately run: `Settings -> Devices & Services -> Add Integration -> HomeKit Device`.
4. Pair with the FP2 HomeKit code (`XXX-XX-XXX` format).

If LED becomes solid before step 3, repeat pairing mode and retry.
