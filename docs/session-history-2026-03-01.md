# Session History - 2026-03-01 (FP2 + Home Assistant + WiFi-DensePose)

## Scope

This file captures what was done during the local integration session with:

- WiFi-DensePose backend/UI
- Home Assistant in Docker
- Aqara FP2 (presence sensor)

## What was implemented in project code

- Added FP2 backend service and API router.
- Added FP2 UI tab with:
  - live status block,
  - counters,
  - recent presence changes,
  - movement events,
  - live movement map,
  - auto entity selection.
- Added endpoint for recommended FP2 entity selection.
- Added `entity_id` support for FP2 current/ws API calls.
- Fixed websocket compatibility issue in frontend (`clearPingInterval` runtime error path).
- Updated local compose/backend startup flow to run API correctly from `src.app:app`.

## Runtime setup performed

- Home Assistant container was started via Docker Compose.
- WiFi-DensePose backend was started and health-checked.
- UI served locally and connected to backend.
- FP2 monitor API status reached `healthy` state with configured entity.

## Credentials/actions performed in session

- Home Assistant temporary login was reset for user `mac`.
- Long-lived Home Assistant token was used for backend polling.
- Aqara account credentials and FP2 HomeKit code were provided in-session for test setup.

All current session credentials were saved to `.env` (latest values).

## Current state at end of session

- In Home Assistant, only helper entity is reliably visible for project:
  - `input_boolean.fp2_presence`
- FP2 Monitor in WiFi-DensePose shows live backend connectivity and presence stream from configured entity.
- Full native FP2 HomeKit accessory discovery in HA is still inconsistent:
  - during pairing flow HA often sees only `HASS Bridge ...` (its own bridge),
  - real FP2 accessory is not consistently listed in the HomeKit Device picker.

## Observed blocker

Main blocker is HomeKit accessory discovery/pairing path, not backend code.

Symptoms seen:

- HA integration screen can fail to list real FP2 accessory.
- Pairing attempt may target wrong accessory (`HASS Bridge`) and fail with invalid code.

## Verified working path right now

- End-to-end project path works with `input_boolean.fp2_presence`:
  - backend polls HA,
  - FP2 tab receives updates,
  - movement/presence timeline renders in UI.

## Next action to complete real FP2 entity integration

1. Put FP2 in pairing mode and keep it close to HA host/network.
2. In HA add `HomeKit Device` (not `HomeKit Bridge`).
3. Ensure picker shows Aqara FP2 accessory (not only HASS Bridge).
4. Pair with code saved in `.env`:
   - `FP2_HOMEKIT_CODE` / `FP2_HOMEKIT_CODE_RAW`
5. After real FP2 entities appear, select them in FP2 Monitor (Auto Select or manual).

---

## Update - 2026-03-02 02:47 MSK

Additional state was validated and fixed in ops flow:

- Non-essential containers were stopped for clean FP2 pairing checks:
  - stopped: `wifi-densepose-dev`, `wifi-densepose-postgres`, `wifi-densepose-redis`
  - left running: `wifi-densepose-ha` (`healthy`, `8123`)
- FP2 LED semantics were confirmed:
  - blinking -> pairing/discoverable
  - solid -> connected / not in pairing mode
- Discovery issue persists intermittently in HA (`HomeKit Device: devices not found`), so reliable procedure must force FP2 back to blinking mode right before HomeKit Device scan.

## Updates 2026-03-04

### Aqara Cloud API Investigation

- Attempted to use Aqara Cloud API v3.0 for FP2 access.
- Discovered correct Sign formula for authentication:
  - With token: `md5(lowercase(Accesstoken=<t>&Appid=<a>&Keyid=<k>&Nonce=<n>&Time=<ts><AppKey>))`
  - Without token: `md5(lowercase(Appid=<a>&Keyid=<k>&Nonce=<n>&Time=<ts><AppKey>))`
- Found that Russia region (`open-ru.aqara.com`) is unreachable.
- Europe region (`open-ger.aqara.com`) returns 403 due to project permissions.
- **Conclusion:** Aqara Cloud API not viable for this project.

### Home Assistant API Solution

- Successfully connected to FP2 via Home Assistant REST API.
- FP2 entity: `input_boolean.fp2_presence`
- Created working CLI client: `scripts/fp2_ha_client.py`

### Motion Detection Tools

Created two new scripts:

1. **`scripts/fp2_ha_client.py`** - Simple HA API client
   - Check current status
   - Watch mode with real-time updates
   - Colorized terminal output

2. **`scripts/fp2_motion_logger.py`** - Data collection tool
   - Records FP2 state to CSV
   - Network statistics (ping to router)
   - Real-time matplotlib visualization
   - Historical data visualization

### UI Enhancements

- Added "Real-time Presence Graph" to FP2 Monitor tab
- Canvas-based live visualization (last 60 seconds)
- Green = presence, Gray = no presence
- Updates via WebSocket stream

### Files Modified/Created

- `scripts/fp2_ha_client.py` (new)
- `scripts/fp2_motion_logger.py` (new)
- `ui/index.html` - Added real-time graph section
- `ui/components/FP2Tab.js` - Added graph rendering logic
- `ui/style.css` - Added graph styles
- `docs/fp2-real-movement-testing.md` - Updated with new tools
- `.env` - Added note about Aqara API restrictions

