# AGENTCLOUD_TELEMETRY_DOORWAY_AUDIT1_REPORT

- Агент: `CODER_CENTER_DOOR_BALANCE5`
- Задача: `Center-door balance sweep on fresh live supports`
- Шаг: `Telemetry doorway audit on near-day live ndjson streams`
- Дата: `2026-04-03`

## Что проверялось

Нужно было не запускать новую запись, а использовать уже накопленный длинный telemetry-поток и понять, где реально рушится doorway-case:

- top-level `runtime`
- `v8_shadow`
- `door_center_candidate_shadow`
- `fewshot_adaptation_shadow`

Слои были сведены по ближайшему `ts` с tolerance `2.5s`.

## Главный факт по данным

Почти суточного **raw continuous archive** в каноническом `record/start` формате сейчас нет. В `temp/captures` найден только короткий run:

- `continuous_signal_archive_20260403_014237`
- примерно `5` минут (`01:43:38` -> `01:48:04`)

Почти суточный поток существует как **telemetry**, а не как truth-backed capture:

- `runtime_telemetry.ndjson`
- `v8_shadow_telemetry.ndjson`
- `door_center_candidate_shadow_telemetry.ndjson`
- `fewshot_adaptation_shadow_telemetry.ndjson`

## Покрытие

- `runtime`: `197303` строк, `2026-03-25 03:33:46` -> `2026-04-03 19:53:58` MSK
- `v8_shadow`: `217087` строк, тот же длинный горизонт
- `door_center_candidate_shadow`: `7053` строк, только `2026-04-03 05:39:16` -> `19:54:00` MSK
- `fewshot_adaptation_shadow`: `6263` строк, но нужный doorway overlap ограничен candidate-слоем

Полное multi-layer overlap окно:

- `2026-04-03 05:39:16` -> `2026-04-03 19:53:58` MSK
- `14.245h`
- `7044` согласованных runtime-окон

Текущий активный fewshot-session:

- `fewshot_balance5_80dim_20260403_v11`
- `2026-04-03 18:49:35` -> `19:53:58` MSK
- `1.073h`
- `1347` согласованных окон

## Главное наблюдение

Проблема выглядит не как “датчики отваливаются”, а как конфликт логики слоёв.

Прямое подтверждение:

- на overlap окне `6937 / 7044` окон шли при `7/7` активных нодах
- на текущем `v11` окне `1334 / 1347` тоже шли при `7/7`
- крупнейшие false-empty серии тоже шли при `7/7` и нормальном `pps ~38.8`

То есть doorway-failures происходят **не из-за node dropout**, а при здоровом тракте.

## Overlap-аудит (`05:39 -> 19:53`)

### Top-level runtime

- `occupied = 4801`
- `empty = 2243`
- `avg_pps = 34.709`
- switch rate:
  - `runtime_binary = 35.24/h`
  - `runtime_zone = 48.437/h`
  - `candidate_zone = 38.75/h`

### Spatial layers

- `candidate_zone`: `door_passage = 3618`, `center = 3402`
- `fewshot_zone`: `door_passage = 2591`, `center = 2216`, `<missing> = 2237`
- `v8_binary`: `empty = 6652`

### Ключевые fail-мотивы

1. `false_empty_with_door_evidence`

- `1533` окон
- `218` серий
- самая длинная серия:
  - `17:02:46 -> 17:05:00`
  - `52` окон
  - `134.55s`
  - `runtime = empty`
  - `candidate = door_passage`
  - `fewshot = door_passage`
  - `7/7` нод
  - `avg_pps = 38.965`

2. `false_empty_with_center_consensus`

- `1980` окон
- `215` серий
- самые длинные серии:
  - `19:17:56 -> 19:21:45`, `90` окон
  - `19:10:30 -> 19:14:22`, `89` окон
- в обоих случаях:
  - `runtime = empty`
  - `prototype/temporal = center`
  - ноды `7/7`
  - `avg_pps ~38.8-39.8`

3. `occupied_but_v8_empty`

- `4507` окон
- `264` серий
- самая длинная серия:
  - `07:17:00 -> 07:36:58`
  - `412` окон
  - `1197.757s`
  - top-level runtime уже считает сцену `occupied/center`
  - `v8` всё ещё говорит `empty`

4. `doorway_support_suppressed_to_center`

- `562` окон
- `135` серий
- самая длинная серия:
  - `07:35:17 -> 07:36:41`
  - `30` окон
  - `84.059s`
  - `fewshot = door_passage`
  - но `candidate = center`

## Текущий активный режим `v11` (`18:49 -> 19:53`)

### Top-level runtime

- `empty = 747`
- `occupied = 600`
- `avg_pps = 35.179`
- switch rate:
  - `runtime_binary = 136.981/h`
  - `runtime_zone = 228.301/h`
  - `candidate_zone = 184.505/h`

Это очень высокий уровень дёрганья.

### Spatial layers в `v11`

- `candidate_zone`: `center = 1045`, `door_passage = 302`
- `fewshot_zone`: `center = 971`, `door_passage = 376`
- `v8_binary`: `empty = 1311`

То есть именно в активном текущем режиме стек перекошен в две стороны одновременно:

- `v8` почти всё время тянет сцену в `empty`
- `candidate/fewshot` спорят между `center` и `door_passage`

### Ключевые серийные сбои в `v11`

1. `false_empty_with_door_evidence`

- `301` окон
- `65` серий
- крупнейшая серия:
  - `19:11:16 -> 19:12:14`
  - `23` окна
  - `57.646s`
  - top-level runtime = `empty`
  - fewshot = `door_passage`

2. `false_empty_with_center_consensus`

- `559` окон
- `60` серий
- крупнейшие серии:
  - `19:17:56 -> 19:21:45`, `90` окон
  - `19:10:30 -> 19:14:22`, `89` окон

3. `doorway_support_suppressed_to_center`

- `94` окна
- `42` серии
- типичный паттерн:
  - runtime уже `occupied`
  - `fewshot = door_passage`
  - `candidate = center`

## Вывод

Главная проблема сейчас не в нестабильности железа.

Telemetry показывает другое:

1. Сбои происходят при `7/7` нодах и нормальном `pps`, то есть тракт жив.
2. Основной конфликт находится в логике:
   - сверху `v8 empty-guard`
   - снизу `prototype/temporal center-bias`
   - отдельно fewshot-door assist
3. Текущий активный `v11` режим очень дёрганый:
   - top-level runtime почти пополам делит `empty` и `occupied`
   - doorway и center support постоянно спорят между собой

## Что делать дальше

1. Не пытаться лечить doorway ещё одним локальным threshold.
2. Разделить задачу иерархически:
   - сначала `empty vs occupied`
   - потом только внутри `occupied` решать `door vs center`
3. Для doorway-case перестать опираться только на текущий `prototype/temporal` surface.
4. Снять новый канонический truth-backed пакет:
   - `2 мин empty`
   - `2 мин статично у двери`
   - `2 мин статично в центре`
   - `1 мин дверь -> центр`
   - `1 мин центр -> дверь`
5. Использовать этот пакет уже не для ещё одного `fewshot_balance5_vN`, а для нового feature-level doorway pass.

## Артефакты

- summary: `/Users/arsen/Desktop/wifi-densepose/output/telemetry_doorway_audit1/telemetry_doorway_audit_summary_v1.json`
- fail intervals: `/Users/arsen/Desktop/wifi-densepose/output/telemetry_doorway_audit1/telemetry_doorway_fail_intervals_v1.json`
- script: `/Users/arsen/Desktop/wifi-densepose/scripts/telemetry_doorway_audit1.py`
