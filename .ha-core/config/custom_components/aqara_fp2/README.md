# Aqara FP2 Cloud Integration - Установка и настройка

## 📦 Установка кастомной интеграции

### Шаг 1: Скопируйте файлы в Home Assistant

```bash
# Создайте директорию для кастомной интеграции
mkdir -p /Users/arsen/Desktop/wifi-densepose/.ha-core/config/custom_components

# Скопируйте интеграцию
cp -r /Users/arsen/Desktop/wifi-densepose/custom_components/aqara_fp2 \
      /Users/arsen/Desktop/wifi-densepose/.ha-core/config/custom_components/
```

Или вручную:
- Создайте папку `custom_components` в папке конфигурации Home Assistant
- Скопируйте туда папку `aqara_fp2`

### Шаг 2: Перезапустите Home Assistant

```bash
# Если используете Docker
docker restart homeassistant

# Или через веб-интерфейс
Настройки → Система → Перезагрузка
```

### Шаг 3: Добавьте интеграцию

1. Откройте Home Assistant: `http://localhost:8123`

2. Перейдите: **Настройки** → **Устройства и службы**

3. Нажмите **"ДОБАВИТЬ ИНТЕГРАЦИЮ"** (желтая кнопка)

4. В поиске введите: **`Aqara FP2 Cloud`**

5. Выберите интеграцию из списка

### Шаг 4: Настройте интеграцию

Заполните форму настройки:

**Поля:**
- **Region**: `europe` (Germany)
- **Access Token**: `928a72b8088cac5c79473fca295d5523`
- **Refresh Token** (опционально): `13ed4606510581b47ca3485365e54748`

Нажмите **"Отправить"**

### Шаг 5: Получите Device ID

После добавления интеграции нужно узнать ID устройства FP2:

1. Откройте терминал
2. Запустите скрипт для получения списка устройств:

```bash
cd /Users/arsen/Desktop/wifi-densepose
python3 scripts/fp2_aqara_api.py
```

В output найдите строку с вашим FP2:
```
📦 Aqara FP2 Presence Sensor
   ID: lumi.xxxx
   Model: lumi.sensor_occupy.agl1
```

Скопируйте **ID** (например, `lumi.12345678`)

### Шаг 6: Обновите конфигурацию

1. В Home Assistant перейдите: **Настройки** → **Устройства и службы**

2. Найдите интеграцию **"Aqara FP2 (europe)"**

3. Нажмите **"Настроить"**

4. Добавьте поле **Device ID**: `lumi.xxxxx` (из шага 5)

5. Сохраните

---

## 🔍 Проверка работы

После настройки проверьте:

1. **Настройки** → **Устройства и службы** → **Объекты**
2. Найдите объекты с префиксом `aqara_fp2`:
   - `binary_sensor.aqara_fp2_occupancy` - присутствие (True/False)
   - `sensor.aqara_fp2_light_level` - освещенность (lux)
   - `sensor.aqara_fp2_distance` - расстояние (m)

---

## 🛠️ Решение проблем

### Ошибка: "Integration not found"

**Причина**: Файлы не скопированы или Home Assistant не перезагружен

**Решение**:
```bash
# Проверьте структуру файлов
ls -la /Users/arsen/Desktop/wifi-densepose/.ha-core/config/custom_components/aqara_fp2/

# Должны быть файлы:
# - __init__.py
# - manifest.json
# - const.py
# - config_flow.py
# - binary_sensor.py
# - sensor.py
```

### Ошибка: "API request failed"

**Причины**:
1. Неверный токен
2. Истек срок действия токена
3. Неправильный регион

**Решение**:
- Проверьте токен в приложении Aqara Home
- При необходимости обновите токен
- Убедитесь, что выбран регион Europe

### Объекты не обновляются

**Причина**: Проблемы с polling API

**Решение**:
1. Проверьте логи Home Assistant:
   ```
   Настройки → Система → Журналы
   ```

2. Увеличьте интервал опроса в `const.py`:
   ```python
   SCAN_INTERVAL = 60  # секунд (вместо 30)
   ```

---

## 📊 Доступные сенсоры

| Сенсор | Тип | Описание | Единицы |
|--------|-----|----------|---------|
| Occupancy | Binary Sensor | Присутствие человека | True/False |
| Light Level | Sensor | Уровень освещенности | lx (люкс) |
| Distance | Sensor | Расстояние до объекта | m (метры) |

---

## ⚙️ Расширенная настройка

### Изменение интервала опроса

Отредактируйте файл `const.py`:

```python
SCAN_INTERVAL = 30  # секунды (по умолчанию)
```

Минимальное значение: 10 секунд  
Рекомендуемое: 30-60 секунд

### Добавление дополнительных сенсоров

Отредактируйте файл `binary_sensor.py` или `sensor.py`, добавив новые классы сенсоров.

Пример для сенсора движения:

```python
class AqaraFp2MotionSensor(CoordinatorEntity, BinarySensorEntity):
    _attr_has_entity_name = True
    _attr_translation_key = "motion"

    @property
    def is_on(self) -> bool | None:
        if not self.coordinator.data:
            return None
        
        result = self.coordinator.data.get("result", {})
        params = result.get("params", [])
        
        for param in params:
            if param.get("resId") == "0.4.85":  # Motion resource ID
                return param.get("value") == "1"
        
        return False
```

Затем добавьте его в список `entities` в функции `async_setup_entry`.

---

## 🔄 Обновление токенов

Токены истекают! Для обновления:

### Вариант 1: Через приложение Aqara Home

1. Откройте Aqara Home app
2. Профиль → Настройки → О приложении
3. Найдите раздел с токенами

### Вариант 2: Через API

Используйте Refresh Token для получения нового Access Token:

```bash
curl -X POST https://open-ger.aqara.com/v3.0/open/api \
  -H "Content-Type: application/json" \
  -d '{
    "intent": "account.refreshToken",
    "data": {
      "refreshtoken": "13ed4606510581b47ca3485365e54748"
    }
  }'
```

Ответ будет содержать новый `accessToken` и `refreshToken`.

---

## 📝 Следующие шаги

После успешной настройки:

1. ✅ Создайте автоматизации с использованием сенсоров
2. ✅ Добавьте дашборд с картами сенсоров
3. ✅ Настройте уведомления о событиях

Пример автоматизации:

```yaml
# automations.yaml
- id: fp2_light_on
  alias: "FP2: Включить свет при обнаружении"
  trigger:
    platform: state
    entity_id: binary_sensor.aqara_fp2_occupancy
    to: "on"
  action:
    - service: light.turn_on
      target:
        entity_id: light.living_room
```

---

## 🆘 Поддержка

При возникновении проблем:

1. Проверьте логи Home Assistant
2. Проверьте логи Aqara API (запускайте скрипт вручную)
3. Убедитесь, что токены действительны
4. Проверьте подключение к интернету

Контакты для поддержки:
- GitHub Issues: https://github.com/arsen/fp2-cloud-hass/issues
- Форум Home Assistant: https://community.home-assistant.io/
