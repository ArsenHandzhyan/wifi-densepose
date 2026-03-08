# 🚨 BACKEND НЕ РАБОТАЕТ - БЫСТРОЕ РЕШЕНИЕ

## ПРОБЛЕМА:
```
Backend connection failed
```

---

## ✅ БЫСТРОЕ РЕШЕНИЕ

### Шаг 1: Откройте НОВЫЙ терминал

### Шаг 2: Выполните команду:

```bash
cd /Users/arsen/Desktop/wifi-densepose
PYTHONPATH=/Users/arsen/Desktop/wifi-densepose/v1:$PYTHONPATH python3 -m uvicorn v1.src.app:app --host 0.0.0.0 --port 8000
```

### Шаг 3: Дождитесь сообщения:

```
INFO:     Uvicorn running on http://0.0.0.0:8000 (Press CTRL+C to quit)
INFO:     Application startup complete.
```

### Шаг 4: Проверьте в браузере:

```
http://127.0.0.1:3000
```

---

## 🔧 ЕСЛИ ОШИБКА "ModuleNotFoundError: No module named 'src'"

### Исправление импортов в app.py:

Откройте файл: `/Users/arsen/Desktop/wifi-densepose/v1/src/app.py`

**Замените:**
```python
from src.config.settings import Settings
from src.services.orchestrator import ServiceOrchestrator
from src.middleware.auth import AuthenticationMiddleware
from src.middleware.rate_limit import RateLimitMiddleware
from src.middleware.error_handler import ErrorHandlingMiddleware
from src.api.routers import pose, stream, health, fp2
from src.api.websocket.connection_manager import connection_manager
```

**На:**
```python
from .config.settings import Settings
from .services.orchestrator import ServiceOrchestrator
from .middleware.auth import AuthenticationMiddleware
from .middleware.rate_limit import RateLimitMiddleware
from .middleware.error_handler import ErrorHandlingMiddleware
from .api.routers import pose, stream, health, fp2
from .api.websocket.connection_manager import connection_manager
```

**Сохраните и перезапустите backend!**

---

## 📊 ПОЛНЫЙ ПЕРЕЗАПУСК ВСЕЙ СИСТЕМЫ

### Команда для полной перезагрузки:

```bash
# Убить все процессы
lsof -ti:8000 | xargs kill -9
lsof -ti:3000 | xargs kill -9
pkill -f fp2_aqara_cloud_monitor

# Запустить Backend
cd /Users/arsen/Desktop/wifi-densepose
PYTHONPATH=/Users/arsen/Desktop/wifi-densepose/v1:$PYTHONPATH \
python3 -m uvicorn v1.src.app:app --host 0.0.0.0 --port 8000 &

# Пауза
sleep 3

# Запустить Cloud Monitor
cd /Users/arsen/Desktop/wifi-densepose
python3 scripts/fp2_aqara_cloud_monitor.py > /tmp/cloud-monitor.log 2>&1 &

# Запустить UI
cd /Users/arsen/Desktop/wifi-densepose/ui
python3 -m http.server 3000 > /tmp/ui.log 2>&1 &

# Проверка
echo "✅ Все сервисы запущены!"
echo "🌐 Откройте: http://127.0.0.1:3000"
```

---

## 🎯 АРХИТЕКТУРА

```
Aqara Cloud API
     ↓
fp2_aqara_cloud_monitor.py
     ↓ (pushes data)
Backend API (port 8000)
     ↓ (HTTP REST)
UI Server (port 3000)
     ↓
Web Browser
```

**Если Backend не работает → UI не получит данные!**

---

## ✅ ПРОВЕРКА РАБОТОСПОСОБНОСТИ

### 1. Проверка Backend:

```bash
curl http://127.0.0.1:8000/health/live
```

**Ожидаемый ответ:**
```json
{"status":"ok"}
```

### 2. Проверка данных FP2:

```bash
curl http://127.0.0.1:8000/api/v1/fp2/current | python3 -m json.tool | head -20
```

**Ожидаемый ответ:**
```json
{
  "timestamp": "...",
  "persons": [...],
  "metadata": {
    "raw_attributes": {
      "presence": true,
      "movement_event": 7,
      ...
    }
  }
}
```

### 3. Проверка UI:

```bash
curl http://127.0.0.1:3000
```

**Ожидаемый ответ:** HTML страницы

---

## 📝 ЧАСТЫЕ ПРОБЛЕМЫ И РЕШЕНИЯ

### Проблема 1: "Address already in use"

**Решение:**
```bash
lsof -ti:8000 | xargs kill -9
```

### Проблема 2: "ModuleNotFoundError"

**Решение:**
- Исправить импорты в `v1/src/app.py` (см. выше)
- Или использовать PYTHONPATH

### Проблема 3: "Permission denied"

**Решение:**
```bash
chmod +x scripts/*.sh
chmod +x scripts/*.py
```

### Проблема 4: Cloud Monitor не запускается

**Проверка:**
```bash
cat /tmp/cloud-monitor.log
```

**Возможные ошибки:**
- Token expired → Обновить токены в `.env`
- Device not found → Проверить DID устройства

---

## 🔍 DEBUG MODE

### Запуск backend с подробными логами:

```bash
cd /Users/arsen/Desktop/wifi-densepose
PYTHONPATH=/Users/arsen/Desktop/wifi-densepose/v1:$PYTHONPATH \
python3 -m uvicorn v1.src.app:app \
  --host 0.0.0.0 \
  --port 8000 \
  --log-level debug \
  --reload
```

### Просмотр логов в реальном времени:

```bash
tail -f /tmp/backend.log
```

---

## ✅ ЧЕКЛИСТ ЗАПУСКА

- [ ] Backend запущен на порту 8000
- [ ] Cloud Monitor запущен
- [ ] UI Server запущен на порту 3000
- [ ] Браузер открывает http://127.0.0.1:3000
- [ ] В UI нет ошибки "Backend connection failed"
- [ ] Данные FP2 отображаются в Dashboard

---

## 🆘 АВARIЙНОЕ ВОССТАНОВЛЕНИЕ

### Если ничего не помогает:

```bash
# Полная очистка
killall -9 python3
killall -9 uvicorn

# Перезагрузка Mac
# sudo reboot

# После перезагрузки
cd /Users/arsen/Desktop/wifi-densepose
bash scripts/restart_fp2_full.sh
```

---

**Готово!** 🚀
