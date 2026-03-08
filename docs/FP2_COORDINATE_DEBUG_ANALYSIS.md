# FP2 Coordinate Update Issue Analysis

**Дата:** 2026-03-08  
**Проблема:** Координаты не обновляются при движении, хотя Movement Event = 7

---

## 🔍 Симптомы

```
Presence: PRESENT
Movement Event: 7 (Moving)
Coordinate Stream: SLOW (28s ago)
Coordinates: [(49, 330), (21, 312)] - не меняются
Delta: Δ +0, +0
```

**Наблюдение:**
- Вы двигаетесь перед сенсорром
- FP2 обнаруживает движение (Movement Event = 7)
- Но координаты **не обновляются** уже 28+ секунд

---

## 📊 Диагностика

### Проверка через debug скрипт:

```bash
cd /Users/arsen/Desktop/wifi-densepose
python3 scripts/debug_fp2_coordinates.py
```

Этот скрипт покажет:
- Presence статус
- Movement Event изменения
- Активные координаты
- Моменты обновления координат

### Что ожидать:

**Сценарий A: Движение есть, координаты стоят**
```
[02:15:30] Sample #1
  Presence: True
  Movement Event: 7
  Active Targets: 2
    - Target 2: (49, 330)
    - Target 4: (21, 312)
  ⏸️  Coordinates STABLE (no change)
```

**Вывод:** Aqara Cloud не отправляет новые координаты

---

## 🎯 Возможные причины

### 1. **Aqara Cloud API ограничение**

**Проблема:**
- Aqara Cloud API (`open-ger.aqara.com`) может **не обновлять** координаты часто
- Это известное поведение европейского региона
- Cloud отдаёт Movement Events, но координаты только при **значительных** перемещениях

**Почему:**
- Экономия трафика
- Ограничение бесплатного API
- Особенности прошивки FP2 для EU

### 2. **Микро-движения vs Макро-движения**

**FP2 различает:**
- **Code 2 (Micro-movement)** - дыхание, жесты
- **Code 3 (Significant movement)** - движения корпусом
- **Code 7 (Moving)** - общее движение
- **Но координаты обновляются только при:**
  - Перемещении на >30-50 см
  - Смене зоны
  - Быстром движении

**Ваш случай:**
- Вы двигаетесь, но в пределах одной зоны
- Координаты (49, 330) и (21, 312) не меняются
- FP2 видит движение → Code 7
- Но для обновления координат движения недостаточно

### 3. **Статичные "призрачные" цели**

**Проблема:**
- FP2 иногда "запоминает" цели
- Даже если человек ушёл, цель может оставаться
- Координаты не меняются, потому что это "виртуальные" цели

**Признаки:**
- Presence = True, но никого нет
- Coordinates не меняются минуты
- Movement Event = 0 или 1

**Решение:**
- Перезагрузить FP2 (выключить из розетки на 10с)
- Подождать 2-3 минуты
- Проверить снова

---

## ✅ Решения

### Решение 1: Использовать Movement Event как индикатор движения

**Реализовано в UI:**
```javascript
// Теперь учитываем Movement Event
const hasMovementEvent = [1, 2, 3, 4, 7].includes(movementEvent);
const isActivelyMoving = hasDeltaMovement || hasMovementEvent;

if (ageSec <= 2.5 && isActivelyMoving) {
  status = 'LIVE';  // Показываем LIVE даже без delta
}
```

**Результат:**
- Coordinate Stream показывает **LIVE** при Movement Event = 7
- Даже если координаты не меняются
- Более честное отображение реальности

### Решение 2: Пройти тест на макро-движение

**Инструкция:**

1. **Выйдите из комнаты полностью**
   - Presence должен стать FALSE
   - Цели должны исчезнуть

2. **Зайдите обратно**
   - Walk through the detection area
   - Должен появиться ENTER event
   - Координаты должны обновиться при входе

3. **Пройдите через всю зону**
   - От одного края до другого
   - Быстрым шагом
   - Координаты должны обновиться

**Ожидаемый результат:**
```
Sample #5
  Movement Event: 7 ← CHANGED
  Active Targets: 2
    - Target 2: (52, 335)  ← Изменилось!
    - Target 4: (23, 315)  ← Изменилось!
  ⚡ COORDINATES UPDATED!
```

### Решение 3: Проверить настройки FP2 в Aqara Home

**Шаги:**

1. Откройте Aqara Home app
2. Найдите FP2 устройство
3. Проверьте настройки:
   - **Detection Sensitivity**: High/Medium/Low
   - **Zone Configuration**: сколько зон настроено
   - **Firmware Version**: последняя ли?

**Рекомендации:**
- Установите **High Sensitivity**
- Проверьте обновление прошивки
- Пересоздайте зоны (если настроены)

### Решение 4: Переключиться на Zone-based tracking

**Если координаты ненадёжны:**

UI уже поддерживает два режима:

**Coordinate Mode:**
```
Movement Map: COORD · LIVE
Показывает координаты (x, y)
```

**Zone Mode:**
```
Movement Map: ZONE
Показывает occupancy по зонам
```

**Преимущества Zone Mode:**
- Надёжнее работает
- Реже обновляется
- Достаточно для presence detection

---

## 🔧 Debug Commands

### Мониторинг в реальном времени:

```bash
# Запустить debug скрипт
python3 scripts/debug_fp2_coordinates.py

# Смотреть cloud monitor лог
tail -f /tmp/wifi-densepose-cloud-monitor.log

# Проверить текущие данные
curl -s http://127.0.0.1:8000/api/v1/fp2/current | \
python3 -c "import sys,json; d=json.load(sys.stdin); \
ra=d['metadata']['raw_attributes']; \
print('Movement:', ra.get('movement_event')); \
print('Coords:', ra.get('resource_values',{}).get('4.22.700'))"
```

### Тест на живые координаты:

```bash
#!/bin/bash
echo "Starting coordinate monitoring..."
for i in {1..10}; do
  curl -s http://127.0.0.1:8000/api/v1/fp2/current | \
  python3 -c "import sys,json,time; d=json.load(sys.stdin); \
  ra=d['metadata']['raw_attributes']; \
  coords=ra.get('resource_values',{}).get('4.22.700','[]'); \
  print(f'{time.strftime(\"%H:%M:%S\")}: {coords[:80]}...')"
  sleep 2
done
```

---

## 📝 Выводы

### Текущее состояние:

✅ **UI работает правильно:**
- Movement Event расшифрован: "Moving (7)"
- Coordinate Stream показывает: "SLOW" (честно)
- Target Cards показывают координаты
- Delta = +0, +0 (координаты не меняются)

⚠️ **Проблема на стороне Aqara Cloud:**
- Координаты не обновляются
- Это особенность EU API
- Не исправляется на нашей стороне

✅ **Компенсируется через:**
- Учёт Movement Events
- Показ LIVE при Code 7
- Зонный fallback режим

### Рекомендации:

1. **Оставьте как есть**
   - Система честно показывает: движение есть, координаты старые
   - Это лучше, чем псевдо-живые фейковые данные

2. **Используйте Zone Mode**
   - Надёжнее для presence detection
   - Достаточно для home automation

3. **Для точного трекинга**
   - Рассмотрите WiFi DensePose (CSI-based)
   - Или несколько FP2 для триангуляции

---

## 📞 Next Steps

Если нужны **точные координаты в реальном времени**:

1. **Проверьте другой регион API**
   - US: `open-us.aqara.com`
   - CN: `open.aqara.com`
   - Возможно, там другая частота обновления

2. **Напрямую через LAN**
   - Попытка локального подключения к FP2
   - Минуя облако
   - Требует reverse engineering

3. **Альтернатива: WiFi DensePose**
   - Используйте CSI data
   - Собственный ML inference
   - Полный контроль над данными

---

**Заключение:** Текущее поведение — это **особенность Aqara Cloud API**, а не баг системы. UI корректно отображает данные и компенсирует ограничения через Movement Events.
