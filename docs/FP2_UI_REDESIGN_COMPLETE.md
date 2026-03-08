# FP2 Telemetry Console - Полный редизайн UI

## Дата: 2026-03-08

## Обзор изменений

Полная переработка UI консоли телеметрии Aqara FP2 с добавлением профессиональных визуализаций, расширенных метрик и улучшенного UX.

---

## ✅ Реализованные функции

### 1. **Визуальный индикатор RSSI (Gauge)**

**Что это:** Графический датчик качества сигнала в виде полукруглой шкалы

**Реализация:**
- Canvas элемент 80x44px
- Градиентная шкала от красного (-90 dBm) через жёлтый к зелёному (-30 dBm)
- Динамическая стрелка указывает текущее значение
- Анимация обновления в реальном времени

**Файлы:**
- `ui/index.html` - canvas элемент `#fp2RssiGauge`
- `ui/components/FP2Tab.js` - функция `drawRssiGauge()`
- `ui/style.css` - стили `.fp2-rssi-gauge`

**Пример использования:**
```javascript
if (Number.isFinite(rawAttributes.rssi)) {
  this.elements.rssiValue.textContent = this.formatDbm(rawAttributes.rssi);
  this.drawRssiGauge(rawAttributes.rssi); // -72 dBm → жёлто-зелёная зона
}
```

---

### 2. **Индикатор угла сенсора (Dial)**

**Что это:** Круглый компас, показывающий направление зоны обнаружения

**Реализация:**
- Canvas элемент 32x32px
- Жёлтый луч показывает направление (0-360°)
- Точка на конце луча
- Фоновый круг для контекста

**Файлы:**
- `ui/index.html` - canvas элемент `#fp2AngleDial`
- `ui/components/FP2Tab.js` - функция `drawAngleDial()`
- `ui/style.css` - стиль `.fp2-angle-row`

**Пример:**
```javascript
this.elements.sensorAngle.textContent = this.formatDegrees(rawAttributes.sensor_angle);
this.drawAngleDial(rawAttributes.sensor_angle); // 86° → луч направлен на 86°
```

---

### 3. **Алерт о падении (Fall Detection Banner)**

**Что это:** Большой красный баннер с анимацией при обнаружении падения

**Реализация:**
- Пульсирующая тень (анимация 2s)
- Трясущийся значок ⚠ (анимация shake)
- Градиентный красный фон
- Время события
- Два уровня критичности: Warning (Code 1) / Critical (Code 2)

**Файлы:**
- `ui/index.html` - блок `#fp2FallAlert`
- `ui/components/FP2Tab.js` - функция `updateFallAlert()`
- `ui/style.css` - стили `.fp2-fall-alert`, `@keyframes fp2-fall-alert-pulse`

**Логика:**
```javascript
if (fallState === 1 || fallState === 2) {
  this.elements.fallAlert.style.display = 'flex';
  this.elements.fallAlertText.textContent = FALL_LABELS[fallState];
  // Code 1: "Possible fall" (warning)
  // Code 2: "Fall detected" (critical)
} else {
  this.elements.fallAlert.style.display = 'none';
}
```

---

### 4. **Увеличенная карта движения (500px)**

**Что это:** Большая интерактивная карта с траекториями движения

**Улучшения:**
- Высота увеличена с 260px до 500px
- Отображение траекторий (trail history)
- Вектора скорости (Δx, Δy)
- Сетка координат с диапазонометром
- Луч угла сенсора с FOV конусом
- Zone fallback режим

**Файлы:**
- `ui/index.html` - canvas 960x500px
- `ui/components/FP2Tab.js` - функции `drawMovementMap()`, `drawCoordinateMap()`
- `ui/style.css` - `.fp2-card--map`

**Функционал траекторий:**
```javascript
// Сохранение истории позиций
this.state.trailHistory.push({
  targets: targets.map(t => ({ id: t.target_id, x: t.x, y: t.y })),
  timestamp: Date.now()
});

// Отрисовка fading trails
byId.forEach((points, id) => {
  points.forEach((point, i) => {
    const alpha = (i / points.length) * 0.6;
    ctx.fillStyle = `rgba(99,102,241,${alpha})`;
    // Draw trail point
  });
});
```

---

### 5. **Карточки целей с детальной информацией**

**Что это:** Сетка карточек для каждой отслеживаемой цели

**Элементы карточки:**
- ID цели (target_2, target_4)
- Зона (Detection Area, Zone 1)
- Координаты (x, y)
- Расстояние (см)
- Угол (градусы)
- Дельта движения (Δx, Δy)

**Файлы:**
- `ui/index.html` - блок `#fp2TargetList`
- `ui/components/FP2Tab.js` - функции `renderPrimaryTarget()`, `renderTargetList()`
- `ui/style.css` - `.fp2-target-list`, `.fp2-target-card`

**Структура:**
```html
<article class="fp2-target-card">
  <div class="fp2-target-card-header">
    <strong>target_2</strong>
    <span>Detection Area</span>
  </div>
  <div class="fp2-target-card-body">
    <span>49, 330</span>
    <span>333.62 cm</span>
    <span>81.6°</span>
    <span>Δ +3, +5</span>
  </div>
</article>
```

---

### 6. **Улучшенный график присутствия**

**Что это:** Расширенный timeline с несколькими слоями данных

**Новые возможности:**
- Отображение presence (зелёный/красный)
- Overlay количества таргетов (синяя линия)
- Легенда с цветовыми кодами
- Плавная анимация (120ms interpolation)

**Файлы:**
- `ui/index.html` - canvas `#fp2RealtimeGraph` 960x220px
- `ui/components/FP2Tab.js` - функция `updateGraphData()`, `drawRealtimeGraph()`
- `ui/style.css` - `.fp2-graph-legend`, `.legend-color`

**Легенда:**
```html
<div class="fp2-graph-legend">
  <span class="legend-item"><span class="legend-color present"></span> Present</span>
  <span class="legend-item"><span class="legend-color absent"></span> Absent</span>
  <span class="legend-item"><span class="legend-color targets"></span> Targets</span>
</div>
```

---

### 7. **Улучшенные(zone windows)**

**Что это:** Визуальные карточки зон occupancy

**Улучшения:**
- Анимированная "сканирующая" линия при активности
- Градиентные границы
- Количество таргетов в зоне
- Подсветка текущей зоны

**Файлы:**
- `ui/index.html` - блок `#fp2ZoneWindows`
- `ui/components/FP2Tab.js` - функция `renderZoneWindows()`
- `ui/style.css` - `.fp2-zone-window`, `@keyframes fp2-zone-scan`

**Анимация:**
```css
.fp2-zone-window.active::after {
  opacity: 1;
  animation: fp2-zone-scan 2s linear infinite;
}

@keyframes fp2-zone-scan {
  0% { transform: translateX(-100%); }
  100% { transform: translateX(100%); }
}
```

---

### 8. **Расширенный лог событий**

**Что это:** Объединённый журнал событий движения и присутствия

**Структура:**
- Секция "Event Log" - события движения
- Разделитель "Presence History"
- Секция "Recent Presence Changes"

**Типы событий:**
- ENTER - вход в зону
- EXIT - выход из зоны
- MOVE - перемещение между зонами
- TELEMETRY - события телеметрии (movement codes)
- ALERT - события падения

**Файлы:**
- `ui/index.html` - списки `#fp2MovementList`, `#fp2HistoryList`
- `ui/components/FP2Tab.js` - функции `trackMovement()`, `pushMovementEvent()`
- `ui/style.css` - `.fp2-movement-list`, `.fp2-events-divider`

**Примеры:**
```
01:04:41  Presence detected in Detection Area  ENTER
01:04:38  Moving (Code 7) · 2 targets          TELEMETRY
01:04:21  Departing (Code 6) · 1 target        TELEMETRY
01:04:00  Static presence (Code 1) · Angle 86° TELEMETRY
```

---

### 9. **Умный статус потока координат**

**Что это:** Индикатор режима работы координатного трекинга

**Статусы:**
- **LIVE** 🟢 - координаты обновляются <2.5s + есть движение (Δ != 0)
- **STATIC** 🟡 - координаты <2.5s, но нет движения (Δ = 0)
- **REPEATING** 🟡 - облако повторяет данные (2.5-10s)
- **SLOW** 🟡 - задержка обновления (10-60s)
- **STALE** 🔴 - данные устарели (>60s)
- **ZONE-ONLY** 🟡 - только zone occupancy, без координат

**Файлы:**
- `ui/index.html` - chip `#fp2CoordinateStream`
- `ui/components/FP2Tab.js` - функция `updateCoordinateStreamStatus()`

**Логика:**
```javascript
const hasMovement = this.hasTargetDeltas(targets);

if (ageSec <= 2.5 && hasMovement) {
  status = 'LIVE';      // Движение есть
} else if (ageSec <= 2.5 && !hasMovement) {
  status = 'STATIC';    // Координаты есть, но стоят
} else if (ageSec <= 10) {
  status = 'REPEATING'; // Облако повторяет
}
```

---

### 10. **Фильтрация активных координат**

**Что это:** Показываются только активные цели, без пустых слотов

**Было:**
```json
[{"rangeId":0,"x":49,"y":330,"state":"1"},
 {"rangeId":"","x":0,"y":0,"state":"0"},
 ... ещё 18 пустых ...]
```

**Стало:**
```json
[
  {
    "rangeId": 0,
    "x": 49,
    "y": 330,
    "targetType": 0,
    "id": 2,
    "state": "1"
  },
  {
    "rangeId": 0,
    "x": 21,
    "y": 312,
    "targetType": 0,
    "id": 4,
    "state": "1"
  }
]
```

**Файлы:**
- `ui/components/FP2Tab.js` - функция `renderResourceGrid()`
- `ui/style.css` - `.fp2-resource-value--json`

**Код фильтрации:**
```javascript
if (resourceId === '4.22.700') {
  const coords = typeof value === 'string' ? JSON.parse(value) : value;
  const activeTargets = Array.isArray(coords) 
    ? coords.filter(t => t && t.state === "1" && (t.x !== 0 || t.y !== 0))
    : [];
  
  if (activeTargets.length > 0) {
    displayValue = JSON.stringify(activeTargets, null, 2);
  } else {
    displayValue = '[] (no active targets)';
  }
}
```

---

## 📁 Изменённые файлы

### HTML (`ui/index.html`)

**Добавлено:**
- Блок алерта о падении `#fp2FallAlert`
- Hero bar с RSSI gauge и Coordinate stream status
- Увеличенный canvas карты движения (960x500)
- Sensor diagnostics с angle dial
- Target summary panel
- Legend для графика присутствия

**Обновлено:**
- Version cache-bust: `v=20260308-fp2ultra1`

### JavaScript (`ui/components/FP2Tab.js`)

**Новые функции:**
- `updateFallAlert(fallState, timestamp)` - управление баннером падения
- `drawRssiGauge(rssi)` - отрисовка индикатора RSSI
- `drawAngleDial(angle)` - отрисовка компаса сенсора
- `updateCoordinateStreamStatus(...)` - умный статус координат
- `formatMovementEventCode(value)` - расшифровка movement codes
- `formatFallStateCode(value)` - расшифровка fall codes

**Улучшенные функции:**
- `renderResourceGrid()` - фильтрация активных координат
- `trackMovement()` - enhanced event labels
- `drawMovementMap()` - траектории и вектора
- `renderTargetList()` - детальные карточки

### CSS (`ui/style.css`)

**Добавлено (291 строка):**
- `.fp2-fall-alert` - баннер падения с анимацией
- `.fp2-rssi-gauge` - стили для canvas RSSI
- `.fp2-angle-row` - компас сенсора
- `.fp2-map-badges` - бейджи на карте
- `.fp2-target-list` - сетка карточек целей
- `.fp2-target-card` - детальная карточка
- `.fp2-zone-window::after` - сканирующая линия
- `.fp2-graph-legend` - легенда графика
- `@keyframes fp2-fall-alert-pulse` - пульсация
- `@keyframes fp2-fall-alert-shake` - тряска
- `@keyframes fp2-zone-scan` - сканирование зоны

---

## 🎯 Итоговые улучшения UX

### До изменений:

```
RSSI: -72 dBm (просто текст)
Movement: Code 7 (непонятно)
Coordinates: [20 элементов с пустыми слотами]
Map: 260px, без истории
Fall: Code 0 (просто текст)
Zones: Минимальные прямоугольники
```

### После изменений:

```
RSSI: [🟢🟡🔴 Gauge] -72 dBm (визуально)
Movement: Moving (Code 7) · 2 targets (понятно)
Coordinates: [2 активных цели, красиво отформатированы]
Map: 500px с траекториями, векторами, сеткой
Fall: ⚠ Fall Detected (баннер с анимацией)
Zones: Анимированные окна со сканирующей линией
```

---

## 🚀 Как использовать

### Запуск:

```bash
# Backend
source venv/bin/activate
PYTHONPATH=. uvicorn src.app:app --host 0.0.0.0 --port 8000

# Cloud Monitor
python3 scripts/fp2_aqara_cloud_monitor.py --backend http://127.0.0.1:8000

# UI
cd ui && python3 -m http.server 3000
```

### Открыть UI:

```
http://127.0.0.1:3000
→ Вкладка "FP2 Monitor"
```

---

## 📊 Текущие метрики

**Размеры файлов:**
- `index.html`: ~357 строк
- `FP2Tab.js`: ~1474 строки
- `style.css`: ~2403 строки (+291 новых)

**Количество функций:** 40+
**Canvas элементов:** 4 (movement map, realtime graph, RSSI gauge, angle dial)
**Анимаций:** 4 (pulse, shake, scan, graph interpolation)

---

## 🔧 Расширенные возможности

### Для разработчиков:

1. **Отладка траекторий:**
   ```javascript
   console.log('Trail history:', this.state.trailHistory.length);
   ```

2. **Мониторинг RSSI:**
   ```javascript
   drawRssiGauge(-72); // Проверка цвета
   ```

3. **Тест алерта:**
   ```javascript
   updateFallAlert(2, '12:34:56'); // Показать Critical alert
   ```

### Для пользователей:

1. **Проверка качества сигнала:**
   - Зелёная зона: Отлично (-30 to -60 dBm)
   - Жёлтая зона: Нормально (-60 to -75 dBm)
   - Красная зона: Плохо (-75 to -90 dBm)

2. **Мониторинг движения:**
   - LIVE: Человек двигается
   - STATIC: Человек присутствует, но не двигается
   - REPEATING: Облако отдаёт те же данные

3. **Безопасность:**
   - Красный баннер = падение обнаружено
   - Требуется немедленная проверка

---

## 📝 Заключение

UI трансформирован из базового монитора в **профессиональную консоль телеметрии** с:

✅ Визуальными индикаторами (RSSI, Angle)
✅ Анимированными элементами (Fall Alert, Zone Scan)
✅ Детальной историей (Trails, Events, Timeline)
✅ Умной интерпретацией данных (Smart Status)
✅ Красивым представлением (Cards, Grids, Charts)

Теперь система готова к production использованию для мониторинга присутствия и безопасности.
