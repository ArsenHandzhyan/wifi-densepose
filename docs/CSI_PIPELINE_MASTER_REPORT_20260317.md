# CSI Motion Detection — Master Report
**Дата**: 2026-03-17 | **Ветка**: `csi-motion-v4-full-corpus-grind`

## Железо
| Компонент | IP | Статус |
|-----------|-----|--------|
| ESP32 n01 | 192.168.1.101 | OK, ~23 pps |
| ESP32 n02 | 192.168.1.117 | OK, ~23 pps |
| ESP32 n03 | 192.168.1.125 | OK, ~23 pps |
| ESP32 n04 | 192.168.1.137 | OK, ~23 pps |
| Pixel 8 Pro | 192.168.1.148 | RTSP 640x480 |
| Mac host | 192.168.1.132 | UDP:5005 |

4 ноды CSI на потолке гаража, WiFi канал 6, firmware RunBot CSI Node v0.2.0.

## Данные
| Метрика | Значение |
|---------|----------|
| Всего клипов | 252 |
| С CSI данными | 246 |
| С видео | 55 |
| С YOLO аннотациями | 51 |
| С Enhanced YOLO | 51 |
| Keyframes | 1331 |
| Эпохи | "early" (датчики свободно), "garage_ceiling_v2" (на потолке) |

## Эволюция моделей

### Track A — Богатые фичи, метки из clip.json

| Версия | Фичи | Окна | Binary BalAcc | Coarse BalAcc | S/M BalAcc | Проблема |
|--------|-------|------|---------------|---------------|------------|----------|
| v3 | 1844 (PCA,ICA,STFT) | — | OOM crash | — | — | Слишком тяжёлый |
| v4 | 1844 (wavelet,MI) | 6134 | **0.707** | **0.621** | **0.742** | Лучший на clip-метках |
| v5 | 51 | 6134 | 0.58 | 0.52 | — | Мало фич |
| v5-cascade | 80 | 847 | 0.41 | — | — | Баг: только 22 клипа |
| v6 | 113 (breathing FFT) | 6134 | 0.699 | 0.642 | 0.761 | Breathing фичи = 0 importance |
| v7 (quick) | 300 (MI selected) | 6134 | **0.694** | **0.660** | **0.791** | XGB + MLP лучшие модели |
| v8 | 356 (from scratch) | 4756 | 0.651 | 0.591 | 0.736 | Упрощённые фичи хуже |
| v10 unified | 100 | 5850 | 0.620 | 0.554 | 0.678 | Шумные YOLO motion метки |

### Track B — Простые фичи, честные метки (другой агент)

| Версия | Фичи | Окна | Binary BalAcc | 3-class BalAcc | Проблема |
|--------|-------|------|---------------|----------------|----------|
| v5 (CSI labels) | 40 | 8061 | 0.54 | 0.41 | Circular labeling! |
| v6 (framediff) | 40 | 4599 | 0.50 | 0.32 | Framediff unreliable |
| v7 (manual GT) | 30 | 222 | **0.89** | 0.48 | Только 7 клипов |
| **v8 (manual+YOLO)** | **40** | **876** | **0.80** | **0.63** | **Лучший честный результат** |
| v9 (all sources) | 40 | 876 | 0.80 | 0.44 | YOLO motion noisy |

## Ключевые находки

### Что работает
1. **Ручная разметка** — 7 клипов дали 0.89 binary (vs 0.707 с 219 клипами)
2. **YOLO positive detection** — когда видит человека, это надёжно
3. **Enhanced YOLO** (gamma+CLAHE+denoise) — +132 кадра (+9.9%), pixel8pro 0%→50%
4. **XGBoost** — лучший для coarse classification
5. **MLP** — лучший для STATIC vs MOTION
6. **Temporal variance** — главный дискриминатор motion
7. **Baseline deviation** — главный дискриминатор presence
8. **Epoch "early"** — 87.3% coarse BalAcc (лучше balance STATIC данных)

### Что НЕ работает
1. **CSI-derived labels** → circular (модель учит свои же фичи)
2. **YOLO absence в темноте** ≠ пустая комната
3. **Frame differencing** — не различает empty vs static
4. **Stacking ensemble** — хуже одиночных моделей
5. **Breathing FFT (0.1-0.5 Hz)** — нулевая importance на 5с окнах
6. **YOLO motion_score** — слишком шумный (<0.04) для static/walking

### Ceiling_v2 проблема
- STATIC recall = 9-22% на ceiling_v2
- Только 35 STATIC клипов в ceiling_v2 (vs 68% в "early")
- Сигнал неподвижного человека ≈ пустая комната в CSI

## Enhanced YOLO — Прорыв

| Метрика | Оригинал | Enhanced | Best |
|---------|----------|----------|------|
| Кадров с людьми | 799 (60%) | 920 (69%) | **931 (70%)** |
| four_person_static | 1/2 (50%) | **2/2 (100%)** | 100% |
| bend_pick_up | 0/20 (0%) | **10/20 (50%)** | 50% |
| squat_stand_cycle | 0/25 (0%) | **12/25 (48%)** | 48% |
| stand_corridor | 0/15 (0%) | **15/15 (100%)** | 100% |
| longcap_chunk0010 | 20/30 (67%) | **30/30 (100%)** | 100% |

Enhancement pipeline: `gamma=0.3 → CLAHE(clip=4.0, tile=8×8) → fastNlMeansDenoising`

## Текущий статус

**v11 в разработке** — объединяет:
- Enhanced YOLO метки (лучшая разметка)
- ~153 богатых CSI фичи
- Все доступные клипы (~250+)
- XGBoost + HistGBT + RF + MLP

## Следующие шаги (приоритет)

1. **v11 с enhanced YOLO** — запущен
2. **Больше пустых записей** — разное время суток, дверь открыта/закрыта
3. **Session3 pack** — 12 структурированных клипов (не запускался)
4. **LED свет** — кардинально улучшит YOLO
5. **Ручная разметка longcap** — 21 чанк с видео
6. **Temporal models** — LSTM/1D CNN на последовательностях окон
7. **Transfer learning** — early→ceiling_v2

## Скрипты

| Скрипт | Назначение |
|--------|-----------|
| `scripts/csi_motion_pipeline_v7.py` | Track A лучший (1844 фич, v4 cache) |
| `scripts/csi_motion_pipeline_v8.py` | Track A full corpus (356 фич) |
| `scripts/csi_motion_pipeline_v8_full_corpus.py` | Track B лучший (40 фич, honest labels) |
| `scripts/csi_motion_pipeline_v10_unified.py` | Первая попытка объединения |
| `scripts/csi_motion_pipeline_v11_enhanced.py` | Enhanced YOLO + rich features |
| `scripts/enhance_and_reannotate_yolo.py` | Low-light enhancement + YOLO |
| `scripts/detect_persons_yolo.py` | Базовый YOLO detection |

## Модели

| Файл | BalAcc | Описание |
|------|--------|----------|
| `output/v8_full_corpus_model_20260317_223719.pkl` | 0.80 binary | Лучший честный |
| `output/csi_pipeline_v4_results/dataset_v4_cache.pkl` | — | 6134×1844 кэш фич |
| `output/csi_pipeline_v7_results/quick_results.json` | 0.660 coarse | Лучший на clip-метках |
