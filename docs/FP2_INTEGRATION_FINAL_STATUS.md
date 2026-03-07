# FP2 Integration Investigation Status

This document is historical context.

The active runtime status for this workspace is documented in [`FP2_RUNTIME_STATUS_2026-03-07.md`](FP2_RUNTIME_STATUS_2026-03-07.md).

## Final Outcome

The project was reduced to a single verified path:

`Aqara FP2 -> HomeKit/HAP -> local backend -> UI`

That path works on the current hardware and is the only integration route treated as active in this repository snapshot.

## Closed Paths

### Matter

- Not the working path for this FP2 setup
- No verified end-to-end local runtime was achieved through Matter on this machine

### SmartThings

- Reauthentication succeeded, but the account path still did not expose usable FP2 devices to Home Assistant
- The user explicitly does not want to buy an additional hub

### Google Home

- Linking existed as an experiment, but it did not become the active runtime telemetry source for the project

### Aqara Cloud API

- The tested account/app path returned authorization failures for device state calls
- It was not reliable enough to remain the primary integration method

### Home Assistant Entity Polling

- HA helper and fallback entity approaches were useful during debugging
- They are no longer the primary data source for the working UI

## Why Direct HAP Won

- It provides a local path without relying on cloud polling
- It works with the existing `Aqara FP2` and Wi-Fi network
- It exposes live presence and light telemetry fast enough for the current UI

## Important Limitation

Direct `HomeKit/HAP` does not expose the full Aqara mobile app scene graph.

The repository can show:

- presence
- light level
- occupancy channels / zone-like windows
- connection state
- event history

The repository cannot reproduce exactly from direct HAP:

- the Aqara room floorplan
- exact person coordinates on the room map
- all app-specific geometry and zone labels from the Aqara mobile UI

## Repository Direction

The cleaned project state should be interpreted as:

- `FP2-only UI`
- `direct HAP monitoring`
- `legacy CSI/DensePose materials retained only as original project context`
