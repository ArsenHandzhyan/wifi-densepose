# AGENTCLOUD_FP2_RAW_COORD_DISCOVERY1_REPORT

## Task

- Agent: `FP2_RAW_COORD_DISCOVERY1`
- Task: `Investigate whether Aqara FP2 raw target coordinates are available`

## Summary

Да, Aqara Cloud в текущем контуре реально отдаёт сырые target coordinates.

Ключевой источник:

- `query.resource.value`
- `resourceId = 4.22.700`

Этот resource содержит JSON-массив tracked targets с полями вида:

- `rangeId`
- `x`
- `y`
- `targetType`
- `id`
- `state`

До правки эти координаты терялись между custom component и backend:

- Aqara payload содержал target positions
- `custom_components/aqara_fp2` не публиковал их в HA entity attributes
- из-за этого `/api/v1/fp2/current` возвращал `persons = []`

После правки live `FP2` path начал отдавать координаты end-to-end.

## Root Cause

Потеря координат происходила не в Aqara Cloud и не в backend `FP2Service`, а в
Home Assistant custom component:

- `binary_sensor.aqara_fp2` публиковал только `device_class` и `friendly_name`
- backend `FP2Service` уже умел читать `attrs.targets`, но этих атрибутов не было

Отдельный operational drift:

- live Home Assistant использует Docker volume `wifi-densepose_ha_config`, а не
  repo-local `/.ha-core/config`
- поэтому одного `sync_aqara_fp2_shadow_copy.sh` было недостаточно для live HA

## Changes Made

- добавлен parser сырого target payload:
  - `/Users/arsen/Desktop/wifi-densepose/custom_components/aqara_fp2/payload_parser.py`
- `binary_sensor.aqara_fp2` теперь публикует:
  - `targets`
  - `zones`
  - `target_count`
  - `aqara_param_count`
  - файл:
    - `/Users/arsen/Desktop/wifi-densepose/custom_components/aqara_fp2/binary_sensor.py`
- добавлены regression tests:
  - `/Users/arsen/Desktop/wifi-densepose/tests/test_aqara_fp2_payload_parser.py`
  - `/Users/arsen/Desktop/wifi-densepose/v1/tests/unit/test_fp2_current_runtime_contract.py`

## Live Verification

Прямая signed Aqara query подтвердила наличие raw coordinates в `4.22.700`.

После копирования канонического bundle прямо в live HA volume и рестарта
`wifi-densepose-ha`:

- `GET /api/v1/fp2/current` начал возвращать `persons`
- `GET /api/v1/fp2/entities` начал показывать `targets` в атрибутах

Зафиксированный live snapshot:

- `presence = true`
- `target_count = 1`
- `person_id = 0`
- `x = 132.0`
- `y = 159.0`
- `zone_id = range_1`
- `fp2_state = fresh`
- `upstream_available = true`

## Validation

Узкий релевантный срез:

- `tests/test_aqara_fp2_payload_parser.py` -> passed
- `v1/tests/unit/test_fp2_current_runtime_contract.py` -> passed

Полный `pytest` после этой правки не зелёный, но красные тесты не относятся к
этому FP2 coordinate fix:

- `35 failed, 423 passed`

Кластеры падений: `esp32 mapping`, `auth dependency`, `csi prediction`,
`hardware placeholder`, `settings`, `training live capture/viewer`.

## Outcome

FP2 coordinate path теперь реально существует в live API:

- раньше: `/api/v1/fp2/current` -> `persons = []`
- теперь: `/api/v1/fp2/current` -> `persons[0].bounding_box.x/y` присутствуют

Дальнейшая live-проверка была остановлена по команде пользователя после того,
как он сообщил, что уже вышел из зоны проверки.
