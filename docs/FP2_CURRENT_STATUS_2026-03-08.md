# Aqara FP2 Telemetry Console - Runtime Status

**Дата:** 2026-03-08  
**Статус:** ✅ UI работает, Backend требует перезапуска

---

## 📊 Текущее состояние системы

### UI (Frontend)
- **Статус:** ✅ РАБОТАЕТ
- **URL:** http://127.0.0.1:3000
- **Порт:** 3000 (Python http.server)
- **Файлы:**
  - `ui/index.html` - главная страница
  - `ui/components/FP2Tab.js` - основной компонент
  - `ui/style.css` - стили с анимациями
  - `ui/app.js` - основное приложение

### Backend (FastAPI)
- **Статус:** ⚠️ ТРЕБУЕТСЯ ПЕРЕЗАПУСК
- **Ожидаемый URL:** http://127.0.0.1:8000
- **Порт:** 8000
- **Эндпоинты:**
  - `/health/live` - проверка здоровья
  - `/api/v1/fp2/current` - текущие данные FP2
  - `/api/v1/fp2/status` - статус системы
  - `/api/v1/fp2/push` - приём данных от cloud monitor

### Cloud Monitor
- **Статус:** ⏸️ ОЖИДАЕТ запуска backend
- **Скрипт:** `scripts/fp2_aqara_cloud_monitor.py`
- **Интервал:** 1 секунда
- **Источник:** Aqara Cloud API (open-ger.aqara.com)

---

## 🎯 Проверенные функции UI

### ✅ Работающие компоненты:

1. **Движение и события:**
   - ✅ Movement Event: "Departing (Code 6)" - человеческий label
   - ✅ Fall State: "No fall detected (0)" - расшифровано
   - ✅ Event Log показывает "Departing (6) · 2 targets"

2. **Координатный трекинг:**
   - ✅ Coordinate Stream: "SLOW" (13s ago) - умный статус
   - ✅ Coordinates Payload:只显示 активные цели (2 из 20)
   - ✅ Отформатировано как JSON с отступами

3. **Target Telemetry:**
   - ✅ Primary Target: target_2 (49, 330)
   - ✅ Карточки целей с координатами, расстоянием, углом
   - ✅ Delta: Δ +0, +0 (статичное положение)

4. **Зоны:**
   - ✅ Zone Occupancy: Detection Area OCCUPIED (2 targets)
   - ✅ Zones Count: 1

5. **Диагностика:**
   - ✅ RSSI: -73 dBm (отображается)
   - ✅ Sensor Angle: 86°
   - ✅ Online: ONLINE
   - ✅ Device Timestamp: 9.5s ago

6. **Connection Info:**
   - ✅ API: Enabled
   - ✅ Sensor Link: LIVE
   - ✅ Transport: Aqara Cloud
   - ✅ Source: aqara_cloud
   - ✅ Last Packet: 0.2s

### ⚠️ Проблемы:

1. **Backend connection failed**
   - Причина: Backend процесс не запущен
   - Решение: Перезапустить `start_fp2_stack.sh`

2. **Coordinate Stream: SLOW**
   - Причина: Aqara Cloud не обновляет координаты (13s)
   - Это нормально для статичного присутствия
   - Движение отсутствует (Δ = 0)

---

## 🔧 Команды для запуска

### 1. Запустить полный стек:

```bash
cd /Users/arsen/Desktop/wifi-densepose
bash scripts/start_fp2_stack.sh
```

Это запустит:
- Backend на порту 8000
- Cloud Monitor (опрос Aqara Cloud каждые 1s)
- Проверит здоровье сервисов

### 2. Поочерёдный запуск:

```bash
# Backend
source venv/bin/activate
PYTHONPATH=. uvicorn src.app:app --host 0.0.0.0 --port 8000 --reload

# Cloud Monitor (в другом терминале)
python3 scripts/fp2_aqara_cloud_monitor.py --backend http://127.0.0.1:8000 --interval 1

# UI (в третьем терминале)
cd ui
python3 -m http.server 3000
```

### 3. Проверка работы:

```bash
# Backend health
curl -sf http://127.0.0.1:8000/health/live && echo "✅ OK"

# Текущие данные FP2
curl -s http://127.0.0.1:8000/api/v1/fp2/current | python3 -m json.tool | head -30

# Cloud Monitor лог
tail -f /tmp/wifi-densepose-cloud-monitor.log

# Backend лог
tail -f /tmp/wifi-densepose-backend.log
```

---

## 📈 Интерпретация текущих данных

### Присутствие:
```
Presence: PRESENT (12s)
Targets: 2
Movement: Departing (Code 6)
```

**Вывод:** Два человека присутствуют в зоне обнаружения. Один удаляется от сенсора (Code 6).

### Координаты:
```
target_2: (49, 330) → 333.6 см, 81.6°
target_4: (21, 312) → 312.7 см, 86.1°
Delta: +0, +0 для обеих целей
```

**Вывод:** Обе цели статичны (нет движения координат), поэтому статус "SLOW".

### Сигнал:
```
RSSI: -73 dBm
Sensor Angle: 86°
Online: ONLINE
```

**Вывод:** Качество сигнала среднее (-73 dBm), сенсор направлен на 86°.

### События:
```
01:48:52  Departing (6) · 2 targets  TELEMETRY
01:48:47  Presence detected in Detection Area  ENTER
```

**Вывод:** 
- 01:48:47 - присутствие обнаружено
- 01:48:52 - движение на удаление (Code 6) с 2 целями

---

## 🎨 Визуальные улучшения (реализованы)

### 1. RSSI Gauge
- Графическая шкала от красного к зелёному
- Стрелка указывает текущее значение (-73 dBm)
- Мгновенная визуальная оценка качества сигнала

### 2. Sensor Angle Dial
- Компас с жёлтым лучом
- Показывает направление зоны обнаружения
- Угол 86° визуально понятен

### 3. Coordinate Stream Status
- **SLOW** (жёлтый) - обновление 10-60s
- Показывает реальное состояние потока
- Отличает STATIC от LIVE

### 4. Filtered Coordinates
- Показываются только активные цели
- Красивое JSON форматирование
- Нет шума от 18 пустых слотов

### 5. Enhanced Event Labels
- "Departing (6) · 2 targets" вместо "Code 6"
- Контекстная информация (количество целей)
- Понятно без документации

---

## 🐛 Диагностика проблем

### Если UI показывает "Backend connection failed":

1. **Проверить backend:**
   ```bash
   curl -sf http://127.0.0.1:8000/health/live
   ```

2. **Если не отвечает:**
   ```bash
   # Найти процессы
   ps aux | grep -E "uvicorn|python.*app"
   
   # Убить старые
   pkill -f "uvicorn src.app"
   pkill -f "fp2_aqara_cloud_monitor"
   
   # Перезапустить
   bash scripts/start_fp2_stack.sh
   ```

3. **Проверить логи:**
   ```bash
   tail -50 /tmp/wifi-densepose-backend.log
   tail -50 /tmp/wifi-densepose-cloud-monitor.log
   ```

### Если Coordinate Stream показывает "STALE" (>60s):

1. **Проверить облако Aqara:**
   ```bash
   tail -f /tmp/wifi-densepose-cloud-monitor.log
   ```

2. **Проверить токены:**
   ```bash
   python3 scripts/aqara_api_probe.py probe --refresh-first
   ```

3. **Переподключить cloud monitor:**
   ```bash
   pkill -f fp2_aqara_cloud_monitor
   python3 scripts/fp2_aqara_cloud_monitor.py --backend http://127.0.0.1:8000
   ```

### Если Movement Event не меняется:

1. **Проверить raw данные:**
   ```bash
   curl -s http://127.0.0.1:8000/api/v1/fp2/current | \
   python3 -c "import sys,json; d=json.load(sys.stdin); print(d['metadata']['raw_attributes'].get('movement_event'))"
   ```

2. **Двигаться перед сенсором:**
   - Code 7 (Moving) появляется при движении
   - Code 1 (Static presence) когда человек стоит
   - Code 6 (Departing) при удалении от сенсора

---

## 📝 Финальный чеклист

### Перед использованием:

- [ ] Backend запущен и отвечает на `/health/live`
- [ ] Cloud Monitor подключён к Aqara API
- [ ] UI доступен на http://127.0.0.1:3000
- [ ] Токены Aqara Cloud действительны
- [ ] FP2 устройство онлайн (RSSI > -90 dBm)

### Во время работы:

- [ ] Presence обновляется каждые 1-2s
- [ ] Coordinate Stream показывает LIVE или STATIC
- [ ] Movement Events отображаются с labels
- [ ] Fall Alert скрыт (если нет падения)
- [ ] RSSI Gauge в зелёной/жёлтой зоне

### При остановке:

- [ ] Остановить процессы (Ctrl+C в терминалах)
- [ ] Проверить сохранность логов
- [ ] Запомнить состояние системы

---

## 🚀 Следующие шаги

### Рекомендуется сделать:

1. **Протестировать движение:**
   - Пройти перед сенсором
   - Проверить смену Movement Events (6→7→5→...)
   - Убедиться, что Coordinate Stream становится LIVE

2. **Проверить траектории:**
   - Подвигаться 20-30 секунд
   - Обновить страницу
   - Проверить trail history на карте

3. **Протестировать Fall Detection:**
   - (Опционально) Сымитировать падение
   - Проверить появление красного баннера
   - Убедиться в пульсации и тряске

4. **Мониторинг RSSI:**
   - Проверить изменение gauge при изменении сигнала
   - Убедиться в цветовой индикации

---

## 📞 Контакты и поддержка

**Документация:**
- `docs/FP2_UI_REDESIGN_COMPLETE.md` - полное описание функций
- `docs/FP2_COORDINATE_DISPLAY_FIX.md` - исправление координат
- `docs/FP2_MOVEMENT_EVENT_CODES.md` - справочник кодов движения

**Логи:**
- Backend: `/tmp/wifi-densepose-backend.log`
- Cloud Monitor: `/tmp/wifi-densepose-cloud-monitor.log`
- UI: `/tmp/ui.log`

**Команды:**
- Запуск: `bash scripts/start_fp2_stack.sh`
- Остановка: Ctrl+C в терминале
- Перезапуск: Остановить → Запустить снова

---

**Текущий статус:** UI готов к работе, требуется перезапуск backend для полного функционала.
