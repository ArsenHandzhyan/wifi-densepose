# FP2 Integration Investigation Status

This document is historical context.

The active runtime status for this workspace is documented in [`FP2_RUNTIME_STATUS_2026-03-07.md`](FP2_RUNTIME_STATUS_2026-03-07.md).

## Final Outcome

The project was reduced to a single verified path:

`Aqara FP2 -> Aqara Open API -> local backend -> UI`

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

- The older `config.*` endpoints remained unreliable
- The working route is the newer `query.*` family with:
  - device DID `lumi1.54ef4479e003`
  - model `lumi.motion.agl001`
  - resource polling via `query.resource.value`

### Home Assistant Entity Polling

- HA helper and fallback entity approaches were useful during debugging
- They are no longer the primary data source for the working UI

### Direct HomeKit / HAP

- Reverse engineering reached the real setup-mode `HAP` endpoint
- Pair setup from `Mac` consistently failed with `kTLVError_MaxPeers`
- That block remained even after factory reset and removal from controllers
- Direct `HAP` is therefore documented as experimental and currently blocked by the accessory, not by this repository

## Important Limitation

The public Aqara/Open API path does not expose the full Aqara mobile app scene graph.

The repository can show:

- presence
- target coordinates
- light level
- occupancy channels / zone-like windows
- connection state
- event history

The repository cannot reproduce exactly from public API data:

- the Aqara room floorplan
- exact person coordinates on the room map
- all app-specific geometry and zone labels from the Aqara mobile UI

## Repository Direction

The cleaned project state should be interpreted as:

- `FP2-only UI`
- `Aqara Cloud monitor feeding the local backend`
- `legacy CSI/DensePose materials moved to the local archive and removed from the tracked runtime tree`
