# FP2 Full Device Audit

- Generated: `2026-03-09 00:23:44`
- Device IP: `192.168.1.52`
- Backend: `http://127.0.0.1:8000`

## 1. Current Live Snapshot

- `effective_presence`: `True`
- `presence_raw`: `True`
- `presence_mode`: `raw`
- `presence_reason`: `None`
- `persons_count`: `1`
- `raw_target_count`: `1`
- `zone_count`: `1`
- `current_zone`: `detection_area`
- `movement_event`: `7`
- `fall_state`: `0`
- `light_level`: `16.0`
- `rssi`: `-21`
- `sensor_angle`: `83.0`
- `coordinates_source`: `live`

### Advanced Metrics

- `realtime_people_count`: `0`
- `people_count_1m`: `2`
- `area_entries_10s`: `6`
- `walking_distance_m`: `23.76`
- `people_statistics_enabled`: `True`
- `walking_distance_enabled`: `True`

## 2. Transport / Reachability

- Open ports on device: `[443]`
- Local HAP expectation: port `55553` should be open for direct HomeKit/HAP
- Actual result: `55553` is `closed`
- HTTPS/cloud port `443`: `open`

## 3. Active Resource Coverage

- Active resources from Aqara Cloud: `66`
- Explicit UI labels in `FP2Tab.js`: `36`
- Semantically processed: `58`
- Raw grid + translated label only: `8`
- Raw grid fallback only: `0`

### Semantic Resources

- `0.4.85` -> `light_level`
- `0.60.85` -> `realtime_people_count`
- `0.61.85` -> `people_count_1m`
- `0.63.85` -> `walking_distance_m`
- `1.10.85` -> `bed_height`
- `1.11.85` -> `installation_height`
- `13.120.85` -> `area_entries_10s`
- `13.121.85` -> `zone_1_entries_10s`
- `13.122.85` -> `zone_2_entries_10s`
- `13.123.85` -> `zone_3_entries_10s`
- `13.124.85` -> `zone_4_entries_10s`
- `13.125.85` -> `zone_5_entries_10s`
- `13.126.85` -> `zone_6_entries_10s`
- `13.127.85` -> `zone_7_entries_10s`
- `13.128.85` -> `zone_8_entries_10s`
- `13.129.85` -> `zone_9_entries_10s`
- `13.130.85` -> `zone_10_entries_10s`
- `13.131.85` -> `zone_11_entries_10s`
- `13.132.85` -> `zone_12_entries_10s`
- `13.133.85` -> `zone_13_entries_10s`
- `13.134.85` -> `zone_14_entries_10s`
- `13.135.85` -> `zone_15_entries_10s`
- `13.136.85` -> `zone_16_entries_10s`
- `13.137.85` -> `zone_17_entries_10s`
- `13.138.85` -> `zone_18_entries_10s`
- `13.139.85` -> `zone_19_entries_10s`
- `13.140.85` -> `zone_20_entries_10s`
- `13.141.85` -> `zone_21_entries_10s`
- `13.142.85` -> `zone_22_entries_10s`
- `13.143.85` -> `zone_23_entries_10s`
- `13.144.85` -> `zone_24_entries_10s`
- `13.145.85` -> `zone_25_entries_10s`
- `13.146.85` -> `zone_26_entries_10s`
- `13.147.85` -> `zone_27_entries_10s`
- `13.148.85` -> `zone_28_entries_10s`
- `13.149.85` -> `zone_29_entries_10s`
- `13.150.85` -> `zone_30_entries_10s`
- `13.27.85` -> `movement_event`
- `13.35.85` -> `installation_angle_status`
- `14.1.85` -> `presence_sensitivity`
- `14.30.85` -> `fall_detection_sensitivity`
- `14.47.85` -> `approach_detection_level`
- `14.49.85` -> `work_mode`
- `14.55.85` -> `detection_mode`
- `14.57.85` -> `installation_position`
- `14.59.85` -> `fall_detection_delay`
- `3.51.85` -> `presence`
- `4.22.700` -> `coordinates`
- `4.22.85` -> `realtime_position_upload_switch`
- `4.23.85` -> `do_not_disturb_switch`
- `4.31.85` -> `fall_state`
- `4.71.85` -> `people_statistics_enabled`
- `4.75.85` -> `walking_distance_enabled`
- `8.0.2026` -> `rssi`
- `8.0.2032` -> `indicator_light`
- `8.0.2045` -> `online_state`
- `8.0.2116` -> `sensor_angle`
- `8.0.2207` -> `do_not_disturb_schedule`

### Raw-Labeled Only

- `0.12.85` -> `上报呼吸率（按分钟）`
- `0.13.85` -> `心率置信度`
- `0.14.85` -> `呼吸率置信度`
- `0.9.85` -> `上报呼吸率`
- `13.11.85` -> `体动级别`
- `14.58.85` -> `床头安装位置设置`
- `4.60.85` -> `设备首次入网`
- `4.66.85` -> `重置无人状态`

### Raw-Only Fallback

- none

## 4. Recent Backend History

- Captures analyzed: `25`
- Movement events seen: `[6, 7]`
- Max active targets seen: `1`
- Coordinate payload variants: `1`

### Recently Changing Resources

- `0.4.85` changed `24` time(s)
- `13.27.85` changed `1` time(s)

## 6. Conclusions

- Aqara Cloud is currently the only working full-telemetry transport.
- All active resources are at least visible in the raw resource grid.
- Not all active resources are elevated into first-class UI widgets yet.
- The main remaining UX opportunity is to promote configuration/diagnostic resources into dedicated cards instead of leaving them only in the raw grid.
- The next best audit pass is a movement session with `--duration 20 --interval 1` while the user walks through the room/garage.

