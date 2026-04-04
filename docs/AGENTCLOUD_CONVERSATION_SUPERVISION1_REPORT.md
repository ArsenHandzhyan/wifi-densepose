# AGENTCLOUD_CONVERSATION_SUPERVISION1_REPORT

- Агент: `CODER_CENTER_DOOR_BALANCE5`
- Задача: `Center-door balance sweep on fresh live supports`
- Шаг: `Build user-confirmed supervision bundle from chat-confirmed garage states`
- Дата: `2026-04-03`

## Что сделано

Собран отдельный supervision layer, который не опирается на нестабильные zone-вердикты модели.

Источник truth:

- явные user-confirmed live trace:
  - `empty`
  - `door_passage`
  - `center`
- already-reviewed guided video manual annotations
- coarse 3-person video-backed session

## Почему это важно

Текущий doorway/center stack остаётся нестабильным. Поэтому для следующего dataset builder и offline eval нужен отдельный truth layer:

- `user/message-driven`
- `manual-review-driven`
- без доверия к live model zones как ground truth

## Выпущенные артефакты

- script:
  - `/Users/arsen/Desktop/wifi-densepose/scripts/build_user_confirmed_supervision1.py`
- manifest:
  - `/Users/arsen/Desktop/wifi-densepose/output/conversation_supervision1/conversation_supervision_manifest_v1.json`
- summary:
  - `/Users/arsen/Desktop/wifi-densepose/output/conversation_supervision1/conversation_supervision_summary_v1.json`

## Что внутри bundle

Всего `15` интервалов:

- `1` coarse 3-person session
- `7` gold manual intervals из guided video
- `7` user-confirmed minute traces

Разбивка:

- `occupied = 14`
- `empty = 1`

По зонам:

- `center = 5`
- `door_passage = 3`
- `door_passage_inside = 2`
- `transition = 3`
- `empty = 1`
- `center_dominant_coarse = 1`

## Политика использования

Этот bundle предназначен для:

- `offline_eval`
- `dataset_builder bootstrap`
- `weak supervision`
- `telemetry alignment`

И не предназначен для:

- promotion raw runtime predictions в ground truth
- трактовки live model zone verdict как источника истины

## Главный вывод

Да, уже сейчас можно выделять:

- `occupancy`
- `empty garage`
- `zone у двери`
- `zone в центре`

но делать это нужно по user-confirmed trace и manual-reviewed video слоям, а не по текущим unstable doorway/center предсказаниям runtime.
