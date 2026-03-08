# 🚀 ПЕРЕЗАПУСК СИСТЕМЫ FP2 MONITORING

## ✅ АВТОМАТИЧЕСКИЙ ЗАПУСК

### Команда для запуска:

```bash
cd /Users/arsen/Desktop/wifi-densepose
bash scripts/restart_fp2_full.sh
```

---

## 📋 ЧТО ДЕЛАЕТ СКРИПТ:

1. **Останавливает** все существующие процессы
2. **Запускает Backend API** (порт 8000)
3. **Запускает Aqara Cloud Monitor** (сбор данных)
4. **Запускает UI Server** (порт 3000)
5. **Проверяет** что все сервисы работают
6. **Показывает** финальный статус

---

## 🌐 ОТКРОЙТЕ В БРАУЗЕРЕ:

```
http://127.0.0.1:3000
```

Вы увидите **FP2 Telemetry Console** со всеми обновлениями:

### Что отображается в UI:

#### 🔴 ВАЖНЫЕ МЕТРИКИ:
- **Presence** - Присутствие (PRESENT/ABSENT)
- **Movement Event** - Код движения с расшифровкой
- **Targets** - Количество целей
- **Fall State** - Обнаружение падения
- **RSSI** - Уровень сигнала (с gauge)
- **Sensor Angle** - Угол сенсора (с dial)

#### 🟡 ЗОНЫ:
- **Zone Occupancy** - Занятость зон (если настроены)
- **Target Count by Zone** - Цели по зонам

#### ⚪ ТЕЛЕМЕТРИЯ:
- **Light Level** - Освещённость (lux)
- **Online State** - Статус онлайн
- **Coordinates** - Координаты целей (отфильтрованные)
- **Resource Channels** - Все endpoint'ы

---

## 🎯 ФУНКЦИОНАЛЬНОСТЬ UI:

### Dashboard вкладки:

1. **FP2 Monitor** - Основная телеметрия
2. **Movement Map** - Карта движения с trajectory
3. **Zone Occupancy** - Зоны с анимацией
4. **Event Log** - История событий
5. **Resource Channels** - Сырые данные

### Визуализации:

✅ **RSSI Gauge** -Canvas-based semi-circle gauge  
✅ **Sensor Angle Dial** - Circular compass dial  
✅ **Movement Trajectory** - Fading trail history  
✅ **Zone Scanning Animation** - Animated scanning line  
✅ **Fall Alert Banner** - Pulsing red alert  
✅ **Target Cards** - Detailed per-target info  

---

## ⌨️ УПРАВЛЕНИЕ

### Проверка статуса:

```bash
bash scripts/check_fp2_status.sh
```

### Просмотр логов:

```bash
# Backend
tail -f /tmp/backend.log

# Cloud Monitor
tail -f /tmp/cloud-monitor.log

# UI Server
tail -f /tmp/ui.log
```

### Остановка:

```bash
# Вариант 1: Kill all
killall -9 python3

# Вариант 2: По PID
kill <BACKEND_PID> <CLOUD_PID> <UI_PID>
```

---

## 🔧 ЕСЛИ ЧТО-ТО НЕ РАБОТАЕТ

### "Backend не отвечает"

```bash
# Проверить порт 8000
lsof -ti:8000 | xargs kill -9

# Запустить вручную
cd /Users/arsen/Desktop/wifi-densepose
PYTHONPATH=/Users/arsen/Desktop/wifi-densepose/v1:$PYTHONPATH \
python3 -m uvicorn v1.src.app:app --host 0.0.0.0 --port 8000
```

### "Cloud Monitor не запускается"

```bash
# Проверить логи
cat /tmp/cloud-monitor.log

# Запустить вручную
cd /Users/arsen/Desktop/wifi-densepose
python3 scripts/fp2_aqara_cloud_monitor.py
```

### "UI не открывается"

```bash
# Проверить порт 3000
lsof -ti:3000 | xargs kill -9

# Запустить вручную
cd /Users/arsen/Desktop/wifi-densepose/ui
python3 -m http.server 3000
```

---

## 📊 АРХИТЕКТУРА СИСТЕМЫ

```
┌─────────────────┐
│   Aqara Cloud   │
│  (open-ger.aqara.com) │
└────────┬────────┘
         │ HTTPS API
         ↓
┌─────────────────┐
│ Cloud Monitor   │ ← Собирает данные
│ (fp2_aqara_cloud_monitor.py) │
└────────┬────────┘
         │ Push API
         ↓
┌─────────────────┐
│   Backend API   │ ← Обрабатывает
│   (FastAPI)     │
│  port 8000      │
└────────┬────────┘
         │ HTTP REST
         ↓
┌─────────────────┐
│    UI Server    │ ← Отображает
│ (Python http.server) │
│  port 3000      │
└────────┬────────┘
         │
         ↓
┌─────────────────┐
│   Web Browser   │
│ http://127.0.0.1:3000 │
└─────────────────┘
```

---

## ✅ ПОСЛЕ ПЕРЕЗАПУСКА

### Проверьте в UI:

1. **Dashboard → FP2 Monitor**
   - Presence должен показывать PRESENT/ABSENT
   - Movement Event с расшифровкой (Moving, Static, etc.)
   - RSSI gauge показывает уровень сигнала
   - Sensor angle dial показывает направление

2. **Movement Map**
   - Coordinate stream status (LIVE/STATIC/SLOW/STALE)
   - Target cards с координатами и дельтой
   - Trajectory history (если движется)

3. **Zone Occupancy**
   - Зоны показывают OCCUPIED/CLEAR
   - Target count badges
   - Scanning animation

4. **Event Log**
   - События presence/movement/fall
   - Timestamps и labels

5. **Resource Channels**
   - Все endpoint'ы отфильтрованы
   - Только active targets в coordinates
   - Human-readable labels

---

## 🎯 ГОТОВО К ТЕСТИРОВАНИЮ!

После перезапуска:

1. **Откройте** http://127.0.0.1:3000
2. **Пройдитесь** перед датчиком FP2
3. **Наблюдайте** за изменениями в UI
4. **Проверьте** Fall Detection (аккуратно!)
5. **Изучите** статистику в логах

---

**СИСТЕМА ГОТОВА!** 🚀
