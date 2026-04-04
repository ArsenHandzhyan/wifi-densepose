# AGENTCLOUD_EMPTY_DOOR_CENTER_CAPTURE_PROTOCOL1_REPORT

Дата: `2026-04-03`
Агент: `CODER_CENTER_DOOR_BALANCE5`
Задача: `Center-door balance sweep on fresh live supports`

## Что сделано

- Подготовлен отдельный канонический truth-backed сценарий записи:
  - `/Users/arsen/Desktop/wifi-densepose/docs/EMPTY_DOOR_CENTER_CANONICAL_CAPTURE_PROTOCOL_2026-04-03.md`
- Сценарий заведён в guided operator path как новый guided capture pack:
  - `truth_empty_door_center_minimal`
- Исправлен guided runtime payload:
  - `step.personCountExpected=0` теперь не затирается до `1`
  - `step.motionType` теперь проходит в `/api/v1/csi/record/start`

## Почему это важно

До этого `empty / static-at-door / center` фактически доучивались по нестабильным runtime verdict и по пакетам, где шаг `empty` нельзя было честно передать как `person_count=0`.

Новый сценарий фиксирует минимальный truth-backed набор:

- `120s empty`
- `120s static-at-door`
- `120s static-at-center`
- `60s door -> center`
- `60s center -> door`

## Изменённые файлы

- `/Users/arsen/Desktop/wifi-densepose/ui/data/guided-capture-packs.js`
- `/Users/arsen/Desktop/wifi-densepose/ui/services/csi-operator.service.js`
- `/Users/arsen/Desktop/wifi-densepose/ui/components/CsiOperatorApp.js`
- `/Users/arsen/Desktop/wifi-densepose/ui/operator-app.js`
- `/Users/arsen/Desktop/wifi-densepose/ui/csi-operator.html`

## Практический результат

Следующий сбор можно запускать через existing canonical operator flow, а не через ad-hoc сценарий:

- `CSI Operator UI`
- guided pack `T1 Truth Empty / Door / Center`
- `record/start -> status -> stop`
- `with_video=true`
- teacher source required
- `startup_signal_guard` обязателен

## Следующий шаг

Прогнать один чистый `T1` session и затем строить новый raw dataset builder уже по этому пакету, а не по unstable live labels.
