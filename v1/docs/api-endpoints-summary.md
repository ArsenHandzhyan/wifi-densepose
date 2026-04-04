# WiFi-DensePose API Endpoints Summary

## Overview

The WiFi-DensePose API provides RESTful endpoints and WebSocket connections for real-time human pose estimation using WiFi CSI (Channel State Information) data. The API is built with FastAPI and supports both synchronous REST operations and real-time streaming via WebSockets.

## Base URL

- **Development**: `http://localhost:8000`
- **API Prefix**: `/api/v1`
- **Documentation**: `http://localhost:8000/docs`

## Authentication

Authentication is configurable via environment variables:
- The tracked current runtime defaults to `ENABLE_AUTHENTICATION=false`; authentication is opt-in unless you explicitly enable it in your local or deployment env.
- When `ENABLE_AUTHENTICATION=true`, protected HTTP and WebSocket control surfaces require a valid JWT token.
- Current public live-read surfaces remain reachable without JWT even when auth is enabled: `health/*`, `/api/v1/health`, `/api/v1/ready`, app-level info/status/metrics aliases, public `pose` read routes, `stream/status`, `stream/metrics`, `fp2/status`, `fp2/current`, `fp2/entities`, `fp2/recommended-entity`, and `fp2/ws`.
- Internal FP2 HAP ingest/diagnostic routes become protected when auth is enabled: `POST /api/v1/fp2/push`, `GET /api/v1/fp2/hap-status`, `WS /api/v1/fp2/ws/hap`.
- Tokens can be passed via:
  - Authorization header: `Bearer <token>`
  - Query parameter: `?token=<token>`
  - Cookie: `access_token`

## Rate Limiting

Rate limiting is configurable and when enabled (`ENABLE_RATE_LIMITING=true`):
- Anonymous: 100 requests/hour
- Authenticated: 1000 requests/hour
- Admin: 10000 requests/hour

## Endpoints

### 1. Health & Status

#### GET `/health/health`
System health check with component status and metrics.

**Response Example:**
```json
{
  "status": "healthy",
  "timestamp": "2025-06-09T16:00:00Z",
  "uptime_seconds": 3600.0,
  "components": {
    "hardware": {...},
    "pose": {...},
    "stream": {...}
  },
  "system_metrics": {
    "cpu": {"percent": 24.1, "count": 2},
    "memory": {"total_gb": 7.75, "available_gb": 3.73},
    "disk": {"total_gb": 31.33, "free_gb": 7.09}
  }
}
```

#### GET `/health/ready`
Readiness check for load balancers. `ready=true` now reflects required resource
checks (`memory_available`, `disk_space_available`), while service-level
readiness like `pose_ready`, `stream_ready`, and `hardware_ready` is reported as
advisory detail in the response message instead of being silently ignored.

#### GET `/health/live`
Simple liveness check.

#### GET `/health/metrics`
Detailed system metrics. The base metrics surface is public; authenticated
requests receive additional detail.

Current hardware service note:
- Internal hardware health is no longer treated as `healthy` just because the service is running with a nominal live backend.
- In live mode the hardware layer is now only `healthy` when at least one live-capable router is actually healthy; `0/N` or partial healthy routers surface as `degraded`.

Current CSI control note:
- `POST /api/v1/csi/start` is idempotent and may return `started` or `already_running`.
- `POST /api/v1/csi/stop` is idempotent and may return `stopped` or `already_stopped`.
- `POST /api/v1/csi/record/stop` is idempotent and may return the last finalized stop payload with `already_stopped=true`, or a minimal `already_stopped` payload when no recording session is active.
- `POST /api/v1/csi/record/start` reuses the same runtime startup guard and no longer masks a foreign UDP port conflict as `already_running`.
- `POST /api/v1/csi/record/start` now also distinguishes recording-start failures honestly:
  `409 already_recording`, `400 invalid_teacher_config`, and `503` for preflight/teacher source unavailability.
- `POST /api/v1/fp2/training/capture/live-csi` now reuses the canonical CSI startup path instead of a private listener bootstrap. It returns `503` when hardware or CSI runtime is not healthy enough for a valid live capture, `409` only for real conflicts like `already_recording` or UDP port ownership, and treats `csi_dead_on_start` as a failed capture instead of a successful clip.
- `GET /api/v1/fp2/training/catalog` and `GET /api/v1/fp2/training/status` now expose `live_capture_runtime`, and `catalog` also exposes `fp2_runtime` plus per-program `launch_gate`. This means FP2-required programs such as `compare_short_walk` no longer look startable in the catalog when FP2 is disabled or unhealthy.
- `POST /api/v1/fp2/training/runs` now applies the same live capture runtime gate to capture programs before spawning a local run. Capture programs reject `disabled`/`not_ready` runtime states up front, while non-capture analysis programs such as `rebuild_baselines` still bypass the live CSI gate.
- Training programs with `require_fp2=true` such as `compare_short_walk` now also require a healthy FP2 runtime before launch; `fp2 disabled` is rejected as `409 fp2_runtime_disabled`, and non-healthy FP2 runtime states are rejected as `503 fp2_runtime_not_ready`.
- `GET /api/v1/fp2/training/runs/current`, `GET /api/v1/fp2/training/status`, `GET /api/v1/fp2/training/runs/{run_id}`, and `POST /api/v1/fp2/training/runs/current/stop` now reconcile stale dead subprocess state before responding. Dead local runs no longer appear as still active, no longer block new launches as fake conflicts, and no longer return a misleading `Active process no longer exists` on stop.
- `GET /api/v1/fp2/training/runs/{run_id}` and related stop/details payloads now expose `artifact_status`, `artifact_status_reason`, `viewer_ready`, and `artifact_counts`. This distinguishes `validated_capture_ready`, `completed_without_viewer`, `failed_partial_artifacts`, and `pending` without requiring a separate `/viewer` call.
- `GET /api/v1/fp2/training/runs/{run_id}/viewer` now requires validated capture clips before reporting `viewer.available=true`. Summary-only, manifest-only, or otherwise partial artifact leftovers no longer look like a complete viewable run, and stale dead runs are reconciled before viewer generation.
- The local `run_atomic_csi_training_capture.py` launcher and `/api/v1/fp2/training/runs` reconciliation now share the same capture-completion contract. A run is not treated as successful just because the subprocess exited `0`: it must also have a readable recording summary with `session_status=completed`, `labeling_verdict.suitable_for_labeling=true`, and, when teacher video is enabled, acceptable teacher-video coverage plus a generated `video_teacher_manifest`.
- `rebuild_baselines` and other analysis runs no longer look `completed` from exit code or a stray single report file alone. The training run now requires the expected published analysis output set to exist and, for JSON outputs, to be readable before it surfaces as `analysis_artifacts_ready`.
- `GET /api/v1/fp2/training/catalog` and `GET /api/v1/fp2/training/status` now also expose `analysis_publication`, and the `rebuild_baselines` catalog entry exposes `publication_summary`. This summary validates referenced dataset CSVs, model summary/model JSON/predictions outputs, and the ablation dataset/ranking instead of inferring readiness from the top-level suite report alone.
- `POST /api/v1/csi/voice/start` and `POST /api/v1/csi/tts/speak` now report the real playback backend: `elevenlabs` when live voice synthesis is available, otherwise `macos_say` instead of silently claiming ElevenLabs while producing no speech.
- `POST /api/v1/csi/voice/stop` and `POST /api/v1/csi/tts/stop` are now honest about inactive playback and may return `already_stopped`.
- `GET /api/v1/csi/status` now exposes a top-level lifecycle contract via `status`, `status_reason`, and `status_message`, instead of forcing the UI to infer health from scattered listener/model/node fields.
- `GET /api/v1/csi/record/status` now exposes `status`, `status_reason`, and `status_scope`, so inactive recording state can still report whether the last session completed, degraded, or failed.
- `dropout_summary.latest_last_seen_sec` and `dropout_summary.oldest_last_seen_sec` now match their names; explicit `freshest_last_seen_sec` and `stalest_last_seen_sec` aliases are also present.

### 2. Pose Estimation

Current runtime note: every public route in the `/api/v1/pose/*` family is a
legacy compatibility surface today. The canonical live UI fallback path is
`/api/v1/fp2/current` and `/api/v1/fp2/ws`; `/pose` remains documented here
only because the routes still exist.

#### GET `/api/v1/pose/current`
Legacy mock-only pose surface. The route is reachable, but the canonical
behavior today is `503 pose_api_mock_only` until `/pose` is rewired to live CSI.

**Query Parameters:**
- `zone_ids`: List of zone IDs to analyze
- `confidence_threshold`: Minimum confidence (0.0-1.0)
- `max_persons`: Maximum persons to detect
- `include_keypoints`: Include keypoint data (default: true)
- `include_segmentation`: Include DensePose segmentation (default: false)

**Current response shape (`503`):**
```json
{
  "error": {
    "code": 503,
    "message": {
      "error": "pose_api_mock_only",
      "mock_only_api_surface": true,
      "live_signal_available": false
    },
    "type": "http_error",
    "path": "/api/v1/pose/current"
  }
}
```

#### POST `/api/v1/pose/analyze` 🔒
Legacy mock-only pose surface. After auth, this route is also expected to fail
with `503 pose_api_mock_only` until the pose runtime is rewired.

#### GET `/api/v1/pose/zones/{zone_id}/occupancy`
Get occupancy for a specific zone.

#### GET `/api/v1/pose/zones/summary`
Get occupancy summary for all zones.

Current zone calibration control note:
- `POST /api/v1/csi/zone/calibrate/start` now surfaces real control states instead of a generic `400`: it may return `capturing`, `already_capturing`, `404 unknown_zone`, or `409 capture_in_progress`.
- `POST /api/v1/csi/zone/calibrate/stop` is idempotent and may return `stopped` or `already_stopped`.
- `POST /api/v1/csi/zone/calibrate/fit` now surfaces rejected calibration states as `409` with structured reasons such as `insufficient_zone_coverage` or `centroids_too_close`, instead of collapsing every rejected fit into a generic `400`.

#### GET `/api/v1/pose/activities`
Get recently detected activities.

**Query Parameters:**
- `zone_id`: Filter by zone
- `limit`: Maximum results (1-100)

#### POST `/api/v1/pose/historical` 🔒
Query historical pose data (requires auth).

**Request Body:**
```json
{
  "start_time": "2025-06-09T15:00:00Z",
  "end_time": "2025-06-09T16:00:00Z",
  "zone_ids": ["zone_1"],
  "aggregation_interval": 300,
  "include_raw_data": false
}
```

#### GET `/api/v1/pose/stats`
Get pose estimation statistics.

**Query Parameters:**
- `hours`: Hours of data to analyze (1-168)

### 3. Calibration

#### POST `/api/v1/pose/calibrate` 🔒
Start system calibration (requires auth).

#### GET `/api/v1/pose/calibration/status` 🔒
Get calibration status (requires auth).

### 4. Streaming

#### GET `/api/v1/stream/status`
Get streaming service status. `status` may be `healthy`, `inactive`, or
`unhealthy`; `inactive` means the stream service is available but not actively
streaming, and should not be read as a backend failure.

#### POST `/api/v1/stream/start` 🔒
Start streaming service (requires auth). Idempotent: if the service is already
active, the route returns a non-error status with an `already active` message.

#### POST `/api/v1/stream/stop` 🔒
Stop streaming service (requires auth). Idempotent: if the service is already
inactive, the route returns a non-error status with an `already inactive`
message.

#### GET `/api/v1/stream/clients` 🔒
List connected WebSocket clients (requires auth).

#### DELETE `/api/v1/stream/clients/{client_id}` 🔒
Disconnect specific client (requires auth).

#### POST `/api/v1/stream/broadcast` 🔒
Broadcast message to clients (requires auth).

### 5. WebSocket Endpoints

#### WS `/api/v1/stream/pose`
Legacy compatibility stream. It may close with a mock-only error until `/pose`
is rewired; the current live UI fallback stream is `/api/v1/fp2/ws`.

**Query Parameters:**
- `zone_ids`: Comma-separated zone IDs
- `min_confidence`: Minimum confidence (0.0-1.0)
- `max_fps`: Maximum frames per second (1-60)
- `token`: Auth token (if authentication enabled)

**Message Types:**
- `connection_established`: Initial connection confirmation
- `pose_update`: Pose data updates
- `error`: Error messages
- `ping`/`pong`: Keep-alive

#### WS `/api/v1/stream/events`
Real-time event streaming.

**Query Parameters:**
- `event_types`: Comma-separated event types
- `zone_ids`: Comma-separated zone IDs
- `token`: Auth token (if authentication enabled)

### 6. FP2 Integration

#### GET `/api/v1/fp2/status`
Current FP2 integration status. `status` is now honest about upstream state:
`healthy`, `initializing`, `inactive`, `degraded`, `upstream_unavailable`, or
`disabled`. Cached-only FP2 data is surfaced as `degraded`/`stale=true` instead
of looking fully healthy.

#### GET `/api/v1/fp2/current`
Current FP2 snapshot converted to the pose-like response used by the UI.
When Home Assistant is unavailable:
- if a cached FP2 snapshot exists, the route still responds `200` but marks the
  payload as `metadata.fp2_state=stale_cache`, `metadata.stale=true`,
  `metadata.upstream_available=false`;
- if no cached snapshot exists, the route responds with `503
  fp2_upstream_unavailable` instead of returning a synthetic empty-room payload.

#### GET `/api/v1/fp2/entities`
Discover FP2-related Home Assistant entities.

#### GET `/api/v1/fp2/recommended-entity`
Best-effort recommended entity for the current FP2 installation.

#### WS `/api/v1/fp2/ws`
Canonical live UI fallback stream for FP2 pose-like data.

#### POST `/api/v1/fp2/push` 🔒
Internal direct-HAP ingest endpoint. When `ENABLE_AUTHENTICATION=true`, send a
bearer token from the HAP client to push snapshots into the backend.

#### GET `/api/v1/fp2/hap-status` 🔒
Internal HAP ingest diagnostics surface.

#### WS `/api/v1/fp2/ws/hap` 🔒
Internal HAP ingest WebSocket diagnostics surface.

### 7. API Information

#### GET `/`
Root endpoint with API information.

#### GET `/api/v1/info`
Detailed app-level API configuration. This remains a public read-only alias.

#### GET `/api/v1/status`
App-level API/service summary alias. For current CSI runtime/operator truth use
`/api/v1/csi/status`. This remains a public read-only alias.

#### GET `/api/v1/metrics`
App-level metrics alias (if enabled). The canonical health metrics route is
`/health/metrics`. This remains a public read-only alias.

### 8. Development Endpoints

These endpoints are only available when `ENABLE_TEST_ENDPOINTS=true`:

#### GET `/api/v1/dev/config`
Get current configuration (development only).

#### POST `/api/v1/dev/reset`
Reset services (development only).

## Error Handling

All errors follow a consistent format:

```json
{
  "error": {
    "code": 400,
    "message": "Error description",
    "type": "error_type"
  }
}
```

Error types:
- `http_error`: HTTP-related errors
- `validation_error`: Request validation errors
- `authentication_error`: Authentication failures
- `rate_limit_exceeded`: Rate limit violations
- `internal_error`: Server errors

## WebSocket Protocol

### Connection Flow

1. **Connect**: `ws://host/api/v1/stream/pose?params`
2. **Receive**: Connection confirmation message
3. **Send/Receive**: Bidirectional communication
4. **Disconnect**: Clean connection closure

### Message Format

All WebSocket messages use JSON format:

```json
{
  "type": "message_type",
  "timestamp": "ISO-8601 timestamp",
  "data": {...}
}
```

### Client Messages

- `{"type": "ping"}`: Keep-alive ping
- `{"type": "update_config", "config": {...}}`: Update stream config
- `{"type": "get_status"}`: Request status
- `{"type": "disconnect"}`: Clean disconnect

### Server Messages

- `{"type": "connection_established", ...}`: Connection confirmed
- `{"type": "pose_update", ...}`: Pose data update
- `{"type": "event", ...}`: Event notification
- `{"type": "pong"}`: Ping response
- `{"type": "error", "message": "..."}`: Error message

## CORS Configuration

CORS is enabled with configurable origins:
- Development: Allow all origins (`*`)
- Production: Restrict to specific domains

## Security Headers

The API includes security headers:
- `X-Content-Type-Options: nosniff`
- `X-Frame-Options: DENY`
- `X-XSS-Protection: 1; mode=block`
- `Referrer-Policy: strict-origin-when-cross-origin`
- `Content-Security-Policy: ...`

## Performance Considerations

1. **Batch Requests**: Use zone summaries instead of individual zone queries
2. **WebSocket Streaming**: Adjust `max_fps` to reduce bandwidth
3. **Historical Data**: Use appropriate `aggregation_interval`
4. **Caching**: Results are cached when Redis is enabled

## Testing

Use the provided test scripts:
- `scripts/test_api_endpoints.py`: Comprehensive endpoint testing
- `scripts/test_websocket_streaming.py`: WebSocket functionality testing

## Production Deployment

For production:
1. Set `ENVIRONMENT=production`
2. Enable authentication and rate limiting
3. Configure proper database (PostgreSQL)
4. Enable Redis for caching
5. Use HTTPS with valid certificates
6. Restrict CORS origins
7. Disable debug mode and test endpoints
8. Configure monitoring and logging

## API Versioning

The API uses URL versioning:
- Current version: `v1`
- Base path: `/api/v1`

Future versions will be available at `/api/v2`, etc.
