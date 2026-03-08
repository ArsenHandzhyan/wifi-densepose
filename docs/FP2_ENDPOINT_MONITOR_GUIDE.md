# FP2 All Endpoints Monitor - Quick Guide

## Что это делает:

Скрипт мониторит **ВСЕ** resource endpoint'ы вашего FP2 устройства в реальном времени и показывает:
- Какие endpoint'ы существуют
- Какие обновляются при движении
- Какие обновляются при дыхании
- Какие вообще не меняются

## Запуск:

```bash
cd /Users/arsen/Desktop/wifi-densepose
python3 scripts/fp2_monitor_all_endpoints.py --interval 1.0
```

## Тестовые сценарии:

### Сценарий 1: Полное отсутствие
```bash
# Выйдите из комнаты
# Наблюдайте: все endpoint'ы статичны
```

### Сценарий 2: Присутствие без движения
```bash
# Войдите и замрите
# Ожидайте изменения:
#   3.51.85 → 1 (Presence)
#   13.27.85 → 1 (Static presence)
```

### Сценарий 3: Микро-движения
```bash
# Дышите, двигайте руками
# Ожидайте:
#   13.27.85 → 2 (Micro-movement)
#   Возможно 4.22.700 → координаты
```

### Сценарий 4: Активное движение
```bash
# Ходите перед сенсорром
# Ожидайте:
#   13.27.85 → 7 (Moving)
#   4.22.700 → новые координаты
#   3.X.85 → смена зон occupancy
```

### Сценарий 5: Уход из зоны
```bash
# Выйдите из detection area
# Ожидайте:
#   3.51.85 → 0 (Absent)
#   13.27.85 → 0 (No event)
```

## Расшифровка маркеров:

- 🔴 - Критически важные (presence, movement, coordinates)
- 🟡 - Зоны (occupancy, target count)
- ⚪ - Остальные (RSSI, light, angle)

## Формат вывода:

```
⚡ CHANGED RESOURCES (3):
  🔴 13.27.85: Moving (Movement Event Code)
  🔴 4.22.700: 2 targets: [(52, 335), (23, 315)] (Coordinates Payload)
      Raw: [{"rangeId":0,"x":52,"y":335,"state":"1"}, ...]
  🟡 3.1.85: Zone 1: OCCUPIED (Zone occupancy)
```

## Остановка:

Нажмите `Ctrl+C` для остановки

## Логирование:

Для сохранения вывода:
```bash
python3 scripts/fp2_monitor_all_endpoints.py | tee /tmp/fp2_endpoints.log
```
