# AGENTCLOUD_CONTINUOUS_CSI_RUNTIME1_REPORT

Дата: 2026-04-03
Репозиторий: `/Users/arsen/Desktop/wifi-densepose`
Ветка: `codex/agent-cloud-video-curation`

## Что сделано

- Встроен signal dashboard прямо в `csi-operator` signal tab:
  - Chart.js подключён в [`/Users/arsen/Desktop/wifi-densepose/ui/csi-operator.html`](/Users/arsen/Desktop/wifi-densepose/ui/csi-operator.html)
  - временные ряды, event log и node cards добавлены в [`/Users/arsen/Desktop/wifi-densepose/ui/components/CsiOperatorApp.js`](/Users/arsen/Desktop/wifi-densepose/ui/components/CsiOperatorApp.js)
  - стили добавлены в [`/Users/arsen/Desktop/wifi-densepose/ui/operator.css`](/Users/arsen/Desktop/wifi-densepose/ui/operator.css)
  - версия импорта обновлена в [`/Users/arsen/Desktop/wifi-densepose/ui/operator-app.js`](/Users/arsen/Desktop/wifi-densepose/ui/operator-app.js)
- Добавлен env-driven auto-start always-on CSI archive в [`/Users/arsen/Desktop/wifi-densepose/v1/src/services/orchestrator.py`](/Users/arsen/Desktop/wifi-densepose/v1/src/services/orchestrator.py):
  - на startup backend пытается поднять continuous archive через canonical recording service
  - сначала пробует честный preflight
  - если preflight падает только на HTTP node probe, но live stream уже видит >=3 online nodes, делает retry через `skip_preflight=True`
  - на shutdown backend честно вызывает `stop_recording(...)`, чтобы не потерять последний chunk
- Добавлены примерные env-переменные в [`/Users/arsen/Desktop/wifi-densepose/.env.example`](/Users/arsen/Desktop/wifi-densepose/.env.example)
- Локально исправлены метаданные двух ошибочно названных 3-person сессий в `temp/captures/`:
  - `occupied_3person_v57_midnight`
  - `occupied_3person_v57c_midnight2`
  - внутри summary/clip файлов теперь согласованы `label`, `person_count_expected=3`, `motion_type=freeform`
- Запущена живая continuous-сессия:
  - label: `continuous_signal_archive_20260403_014237`
  - старт через `/api/v1/csi/record/start`
  - post-start guard passed
- Переобучен runtime-parity bundle через `scripts/retrain_v55_synced.py`
- Новый bundle перегружен в живой runtime через `POST /api/v1/csi/model/select`

## Анализ последних 10 минут

Анализ выполнен по последней длинной подтверждённой 3-person записи `occupied_3person_v56_garage`, потому что backend до этого не держал 10-минутный persisted buffer в памяти.

- `73` total windows, в анализ взяты последние `60` окон по `10` секунд
- `occupied_proba_mean = 0.9491`
- `occupied_proba_min = 0.8945`
- `occupied_proba_max = 0.9885`
- `occupied_pred_ratio = 1.0`
- `active_nodes_mean = 7.0`
- эффективный packet rate по окнам: `31.2 pkt/s`
- `tvar_mean = 6.589`
- `tvar_max_mean = 10.9943`
- `phase_std_mean = 1.5366`
- `phase_coherence_mean = 0.0664`
- `rssi_mean_global = -53.208`
- `rssi_std_global = 2.598`

Node means за последние 10 минут `occupied_3person_v56_garage`:

- `node01`: RSSI `-54.86`, TVAR `6.248`, phase_std `1.5122`, packets/window `24.8`
- `node02`: RSSI `-53.63`, TVAR `7.598`, phase_std `1.5937`, packets/window `31.7`
- `node03`: RSSI `-50.76`, TVAR `7.218`, phase_std `1.6304`, packets/window `83.4`
- `node04`: RSSI `-51.74`, TVAR `6.196`, phase_std `1.3725`, packets/window `23.0`
- `node05`: RSSI `-50.59`, TVAR `4.842`, phase_std `1.6153`, packets/window `94.6`
- `node06`: RSSI `-55.31`, TVAR `7.977`, phase_std `1.5238`, packets/window `26.6`
- `node07`: RSSI `-55.56`, TVAR `6.044`, phase_std `1.5081`, packets/window `27.9`

Chunk-level last 10 minutes `occupied_3person_v56_garage`:

- mean PPS across last 10 chunks: `29.99`
- min/max PPS: `20.9` / `34.1`
- packet totals:
  - `192.168.0.110`: `5165`
  - `192.168.0.143`: `4559`
  - `192.168.0.117`: `1818`
  - `192.168.0.153`: `1608`
  - `192.168.0.132`: `1471`
  - `192.168.0.137`: `1300`
  - `192.168.0.125`: `1257`

Вывод: на подтверждённой 3-person записи модель уверенно и стабильно держит `occupied`; самый плотный трафик идёт через `node05` и `node03`, при этом все `7` нод остаются активными.

## Retrain

Команда: `python3 scripts/retrain_v55_synced.py`

Результат:

- total windows: `1863`
- empty: `1292`
- occupied: `571`
- feature dim: `208`
- CV F1-macro: `0.9620 ± 0.0077`

Top feature importances включают phase surface:

- `node04_phase_std` — rank `13`, importance `0.0203`
- `phase_std_mean` — rank `18`, importance `0.0157`

Bundle сохранён в:

- [`/Users/arsen/Desktop/wifi-densepose/output/train_runs/v48_production/v48_production.pkl`](/Users/arsen/Desktop/wifi-densepose/output/train_runs/v48_production/v48_production.pkl)
- [`/Users/arsen/Desktop/wifi-densepose/output/train_runs/v45_retrain/v53_shadow.pkl`](/Users/arsen/Desktop/wifi-densepose/output/train_runs/v45_retrain/v53_shadow.pkl)

## Верификация

- `node --check ui/operator-app.js` — ok
- `node --check ui/components/CsiOperatorApp.js` — ok
- `python3 -m py_compile v1/src/services/orchestrator.py` — ok
- `python3 -m py_compile v1/src/config/settings.py` — ok
- `python3 -m pytest -q v1/tests/unit/test_csi_listener_autostart.py` — не выполнен: в системном `python3` отсутствует `pytest`

## Локальные операционные изменения вне git-коммита

- обновлён локальный `.env`:
  - `CSI_CONTINUOUS_RECORDING_ENABLED=1`
  - `CSI_CONTINUOUS_RECORDING_CHUNK_SEC=60`
  - `CSI_CONTINUOUS_RECORDING_LABEL_PREFIX=continuous_signal_archive`
  - `CSI_CONTINUOUS_RECORDING_MOTION_TYPE=continuous_archive`
  - `CSI_CONTINUOUS_RECORDING_NOTES=Automatic always-on CSI archive`
- исправлены ignored-файлы в `temp/captures/`
- переобученные `.pkl` bundle обновлены локально и подхвачены runtime через model-select, но намеренно не добавлены в git-коммит
