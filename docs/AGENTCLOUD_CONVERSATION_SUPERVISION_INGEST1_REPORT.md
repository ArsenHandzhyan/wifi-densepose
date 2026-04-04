# AGENTCLOUD_CONVERSATION_SUPERVISION_INGEST1_REPORT

- Агент: `CODER_CENTER_DOOR_BALANCE5`
- Задача: `Center-door balance sweep on fresh live supports`
- Шаг: `Ingest user-confirmed conversation supervision into builder-ready eval tables`
- Дата: `2026-04-03`

## Что сделано

Поверх уже выпущенного `conversation_supervision_manifest_v1` собран builder-ready ingest слой.

Новый ingest не использует runtime zone predictions как truth. Он использует только:

- user-confirmed live traces
- gold manual video annotations
- coarse 3-person video-backed occupancy truth

## Выпущенные артефакты

- script:
  - `/Users/arsen/Desktop/wifi-densepose/scripts/ingest_conversation_supervision1.py`
- summary:
  - `/Users/arsen/Desktop/wifi-densepose/output/conversation_supervision_ingest1/conversation_supervision_ingest_summary_v1.json`
- CSV tables:
  - `/Users/arsen/Desktop/wifi-densepose/output/conversation_supervision_ingest1/conversation_supervision_intervals_v1.csv`
  - `/Users/arsen/Desktop/wifi-densepose/output/conversation_supervision_ingest1/conversation_supervision_occupancy_eval_v1.csv`
  - `/Users/arsen/Desktop/wifi-densepose/output/conversation_supervision_ingest1/conversation_supervision_zone_eval_v1.csv`
  - `/Users/arsen/Desktop/wifi-densepose/output/conversation_supervision_ingest1/conversation_supervision_motion_eval_v1.csv`

## Что внутри

- `interval_rows = 15`
- `occupancy_rows = 15`
- `zone_rows = 10`
- `motion_rows = 14`

Разбивка zone eval:

- `door_passage = 5`
- `center = 5`

Разбивка occupancy eval:

- `occupied = 14`
- `empty = 1`

Разбивка motion eval:

- `static = 11`
- `motion = 3`

## Политика

### occupancy table

Включает все интервалы, включая coarse `3-person` session и `empty`.

### zone table

Включает только точные occupied интервалы с нормализованными зонами:

- `door_passage`
- `center`

Исключает:

- `transition`
- `empty`
- `center_dominant_coarse`

### motion table

Правило:

- `transition -> motion`
- другие occupied интервалы -> `static`
- `empty` не включается

## Практический смысл

Теперь уже можно честно строить offline eval и dataset slices:

1. `empty vs occupied`
2. `door_passage vs center`
3. `static vs transition`

И всё это на user-confirmed / manual-reviewed truth, а не на unstable runtime self-labeling.
