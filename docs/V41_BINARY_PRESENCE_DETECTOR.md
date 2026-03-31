# V4.1 Binary Presence Detector

## Обзор

Бинарный детектор присутствия на основе CSI-сигналов от 7 ESP32-S3 узлов с прошивкой v4.1 (TEXT-формат).

**Модель**: GradientBoosting, 2 класса (empty / present)
**CV F1 macro**: 0.976
**Дата обучения**: 2026-03-31

## Формат данных v4.1

Прошивка v4.1 отправляет CSI в текстовом формате через UDP:

```
CSI_DATA,type,mac,router_mac,rssi,...,csi_len,"[I Q I Q ...]"
```

- 192 поднесущих (384 значения I,Q в скобках, разделённых пробелами)
- Данные кодируются в base64 и передаются в поле `payload_b64` JSON-пакета
- ~3 pps суммарно от всех 7 узлов (низкая частота по сравнению с предыдущими прошивками)

## Архитектура признаков

8 признаков на узел × 7 узлов = **56 признаков**:

| Признак | Описание |
|---------|----------|
| mean_rssi | Средний RSSI за окно |
| std_rssi | Стандартное отклонение RSSI |
| mean_amp | Средняя амплитуда по всем поднесущим |
| std_amp | Стандартное отклонение амплитуды |
| max_amp | Максимальная амплитуда |
| low_amp | Средняя амплитуда нижней трети поднесущих |
| mid_amp | Средняя амплитуда средней трети |
| high_amp | Средняя амплитуда верхней трети |

### Ключевые дискриминирующие признаки

| Признак | Важность |
|---------|----------|
| n06_std_rssi | 32.5% |
| n04_mid_amp | 22.0% |
| n03_std_amp | 18.6% |

### Ключевые узлы

- **n06** (192.168.0.132): 21 поднесущая с |Cohen's d| > 2, дисперсия RSSI ×2.9
- **n04** (192.168.0.125): дисперсия RSSI ×3.3
- **n07** (192.168.0.153): дисперсия RSSI ×3.4

## Данные обучения

- **318 сэмплов**: 88 empty + 230 present
- Calibration snapshots (marker1–marker8, center, door → "present")
- Записи пустого гаража (3 сессии) → "empty"
- Записи с 2 людьми (4 сессии) → "present"
- Скользящие окна с 50% перекрытием

## Файлы

| Файл | Описание |
|------|----------|
| `output/epoch4_v41_model/v41_position_classifier.pkl` | Обученная модель |
| `output/epoch4_v41_model/v41_position_classifier_meta.json` | Метаданные |
| `scripts/retrain_v41_model.py` | Скрипт обучения (12 классов) |
| `scripts/retrain_v41_3class.py` | Скрипт обучения (3 класса) |
| `scripts/csi_v41_text_compare.py` | Сравнение CSI-сигналов empty vs present |
| `output/csi_v41_binary_deep_comparison.png` | 6-панельная визуализация |

## Изменения в runtime

### Post-start signal guard (csi_recording_service.py)

Пороги адаптированы под низкий PPS v4.1:

| Параметр | Было | Стало |
|----------|------|-------|
| GRACE_SEC | 6.0 | 20.0 |
| MIN_ACTIVE_CORE_NODES | 1 | 3 |
| MIN_PACKETS | 20 | 3 |
| MIN_PPS | 5.0 | 0.3 |

### Port management (commands/stop.py)

Добавлены утилиты для надёжного перезапуска сервера:
- `find_port_holders(port)` — поиск процессов на порту через lsof
- `kill_port_holders(port)` — SIGTERM → timeout → SIGKILL
- `ensure_port_free(port)` — очистка порта перед запуском

## Известные проблемы

1. **Модель не переключается на "empty"** при уходе людей из гаража — требуется диагностика буфера пакетов и выравнивание window_size между обучением и runtime
2. **Дисбаланс классов** (230 present vs 88 empty) — может вызывать смещение в сторону "present"
3. **Window size mismatch**: обучение с WINDOW_SIZE=7, runtime _EPOCH4_WIN=5
