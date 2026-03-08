# FP2 Telemetry Console - Coordinate Display Fix

## Проблема

1. **Coordinates Payload отображался нечитаемо**
   - Показывал все 20 слотов (включая пустые)
   - Пример: `[{"rangeId":0,"x":49,"y":330,...}, {"rangeId":"","x":0,"y":0,...}, ...]` (20 элементов)
   - Сложно было понять, какие цели активны

2. **Не было видно статичного положения**
   - Координаты обновлялись, но не менялись (Δ +0, +0)
   - Статус показывал "LIVE", хотя движения не было
   - Movement event = 7 (Moving), но координаты стояли на месте

## Решение

### 1. Улучшенное отображение координат

**Файл:** `ui/components/FP2Tab.js`

Теперь показываются **только активные цели**:

```javascript
// Фильтрация только активных целей (state="1" и x/y != 0)
const activeTargets = coords.filter(t => 
  t && t.state === "1" && (t.x !== 0 || t.y !== 0)
);

// Было (20 слотов):
[{"rangeId":0,"x":49,"y":330,"targetType":0,"id":2,"state":"1"},
 {"rangeId":"","x":0,"y":0,"targetType":0,"id":0,"state":"0"},
 ... 18 пустых слотов ...]

// Стало (только активные):
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

**CSS для красивого отображения:**

Добавлен стиль `.fp2-resource-value--json`:
- `white-space: pre-wrap` - сохраняет форматирование
- `word-break: break-word` - переносит длинные строки
- `max-height: 240px` - ограничивает высоту
- `overflow: auto` - добавляет скролл при необходимости

### 2. Новый статус "STATIC"

**Файл:** `ui/components/FP2Tab.js`

Добавлена проверка на движение координат:

```javascript
const hasMovement = this.hasTargetDeltas(targets);

if (ageSec <= 2.5 && hasMovement) {
  status = 'LIVE';      // Движение есть
} else if (ageSec <= 2.5 && !hasMovement) {
  status = 'STATIC';    // Координаты есть, но не двигаются
}
```

**Новые статусы:**

| Статус | Когда | Описание |
|--------|-------|----------|
| **LIVE** 🟢 | age < 2.5s + Δ != 0 | Координаты обновляются и двигаются |
| **STATIC** 🟡 | age < 2.5s + Δ = 0 | Координаты обновляются, но стоят на месте |
| **REPEATING** 🟡 | age 2.5-10s | Облако повторяет старые данные |
| **SLOW** 🟡 | age 10-60s | Задержка обновления |
| **STALE** 🔴 | age > 60s | Данные устарели |

### 3. Расширенная информация о событиях

**Файл:** `ui/components/FP2Tab.js`

Теперь события движения показывают больше контекста:

```javascript
// Для Code 1 (Static presence)
"Static presence (Code 1) · Angle 86°"

// Для Code 5/6/7 (Movement)
"Moving (Code 7) · 2 targets"
"Departing (Code 6) · 1 target"
"Approaching (Code 5) · 2 targets"
```

## Результат

### До изменений:

```
Coordinates Payload:
[{"rangeId":0,"x":49,"y":330,"targetType":0,"id":2,"state":"1"},{"rangeId":"","x":0,"y":0,"targetType":0,"id":0,"state":"0"},{"rangeId":"","x":0,"y":0,"targetType":0,"id":1,"state":"0"}...ещё 17 пустых...]

Coordinate Stream: LIVE
Movement Events: Moving (Code 7)
```

**Проблема:** Непонятно, сколько активных целей и двигаются ли они

### После изменений:

```
Coordinates Payload:
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

Coordinate Stream: STATIC
Movement Events: 
  - Moving (Code 7) · 2 targets
  - Static presence (Code 1) · Angle 86°
```

**Преимущества:**
- ✅ Видны только активные цели (2 вместо 20)
- ✅ Понятно, что координаты есть, но не двигаются (STATIC)
- ✅ Видно количество целей в событиях движения
- ✅ Угол сенсора для статичного присутствия

## Технические детали

### Изменённые файлы

1. **`ui/components/FP2Tab.js`**
   - Метод `renderResourceGrid()` - фильтрация координат
   - Метод `updateCoordinateStreamStatus()` - проверка hasMovement
   - Метод `trackMovement()` - расширенные метки событий

2. **`ui/style.css`**
   - Класс `.fp2-resource-value--json` - форматирование JSON

### Логика фильтрации координат

```javascript
// Проверяем, что цель активна
t.state === "1"        // state = "1" (активен)
&& (t.x !== 0 || t.y !== 0)  // и x/y не нулевые
```

### Проверка движения

```javascript
hasTargetDeltas(targets) {
  return targets.some(target => 
    isFinite(target?.dx) || isFinite(target?.dy)
  );
}
```

## Сценарии использования

### Сценарий 1: Человек стоит на месте

```
Presence: PRESENT
Targets: 2
Coordinates: [(49, 330), (21, 312)]
Δ: +0, +0
Coordinate Stream: STATIC
Movement Event: Static presence (Code 1) · Angle 86°
```

**Вывод:** Человек присутствует, но не двигается

### Сценарий 2: Человек идёт

```
Presence: PRESENT
Targets: 2
Coordinates: [(52, 335), (23, 315)]
Δ: +3, +5
Coordinate Stream: LIVE
Movement Event: Moving (Code 7) · 2 targets
```

**Вывод:** Человек двигается, координаты обновляются

### Сценарий 3: Облако повторяет данные

```
Presence: PRESENT
Targets: 2
Coordinates: [(49, 330), (21, 312)]
Last Update: 5s ago
Coordinate Stream: REPEATING
```

**Вывод:** Aqara Cloud отдаёт тот же snapshot

## Заключение

Теперь консоль телеметрии показывает:
- ✅ **Только активные цели** - нет шума от пустых слотов
- ✅ **Реальное движение** - STATIC vs LIVE статусы
- ✅ **Контекст событий** - количество целей, угол сенсора
- ✅ **Читаемый JSON** - форматированный вывод координат

Это даёт гораздо более точное представление о том, что на самом деле происходит с отслеживанием присутствия FP2.
