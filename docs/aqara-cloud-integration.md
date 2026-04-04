# Интеграция Aqara Cloud для FP2

> Archival FP2/Aqara note (2026-03-29):
> this document belongs to an earlier FP2/Home Assistant integration line and
> is preserved only as historical reference for that thread.
> Any setup flow, status wording, endpoint examples, or device metadata below
> should be read as archival context rather than current repo truth.
> For the current canonical repo state and active entrypoints, use
> `/Users/arsen/Desktop/wifi-densepose/docs/CURRENT_DOCS_ENTRYPOINT_20260329.md`
> and `/Users/arsen/Desktop/wifi-densepose/docs/CURRENT_PROJECT_STATE_20260329.md`.

## Настройка через HACS (Рекомендуется)

### Шаг 1: Установка кастомной интеграции

1. **Установите HACS** (если еще не установлен):
   - В Home Assistant: Настройки → Устройства и службы
   - Добавить интеграцию → Найдите "HACS"
   - Следуйте инструкциям по установке

2. **Добавьте репозиторий Aqara**:
   - Откройте HACS в боковом меню
   - Нажмите "Интеграции"
   - Нажмите три точки (справа сверху) → "Настраиваемые репозитории"
   - Добавьте URL: `https://github.com/niceboygithub/AqaraGateway`
   - Категория: "Интеграции"
   - Нажмите "Добавить"

3. **Установите интеграцию**:
   - Найдите "Aqara Gateway" в списке HACS
   - Нажмите "Загрузить"
   - Перезапустите Home Assistant

### Шаг 2: Настройка интеграции Aqara

После перезапуска:

1. **Настройки** → **Устройства и службы**
2. **Добавить интеграцию**
3. Найдите **"Aqara Gateway"** или **"Aqara Cloud"**
4. Выберите регион: **Europe (Germany)**
5. Введите учетные данные:
   - Email/телефон от аккаунта Aqara Home
   - Пароль

### Шаг 3: Проверка FP2

После настройки:
- FP2 должен автоматически появиться в списке устройств
- Проверьте: Настройки → Устройства и службы → [Ваша интеграция Aqara]
- Должны быть доступны объекты:
  - `binary_sensor.fp2_occupancy` - присутствие
  - `sensor.fp2_distance` - расстояние
  - `sensor.fp2_light_level` - освещенность

---

## Альтернатива: Интеграция через MQTT

Если официальная интеграция не работает, можно использовать MQTT:

### Требуемые компоненты:
1. Mosquitto broker (установлен в Docker?)
2. Скрипт-прослойка между Aqara API и MQTT
3. MQTT интеграция в Home Assistant

### Схема работы:
```
Aqara Cloud API → Python скрипт → MQTT Broker → Home Assistant
```

---

## Быстрая проверка API

Перед настройкой проверим, что ваш аккаунт работает:

```bash
cd /Users/arsen/Desktop/wifi-densepose
python3 scripts/fp2_aqara_api.py
```

Если видите список устройств - все работает!

---

## Текущие учетные данные (Europe)

- **Region**: Europe (Germany)
- **API Endpoint**: https://open-ger.aqara.com
- **Access Token**: `<redacted_access_token>`
- **Expires**: 2026-03-11 15:50:02
- **Refresh Token**: `<redacted_refresh_token>`
- **Expires**: 2026-04-10 15:50:02

Реальные токены не должны храниться в документации; используйте собственные
секреты из локального защищённого окружения.

---

## Создание кастомной интеграции (Extended)

Если готовые варианты не подходят, создадим свою интеграцию:

### Файловая структура:
```
custom_components/
└── aqara_cloud/
    ├── __init__.py
    ├── manifest.json
    ├── config_flow.py
    ├── const.py
    ├── binary_sensor.py
    └── sensor.py
```

### manifest.json:
```json
{
  "domain": "aqara_cloud",
  "name": "Aqara Cloud",
  "version": "1.0.0",
  "config_flow": true,
  "documentation": "https://github.com/yourusername/aqara-cloud-hass",
  "requirements": ["aiohttp>=3.8.0"],
  "codeowners": ["@yourusername"],
  "iot_class": "cloud_polling"
}
```

### const.py:
```python
DOMAIN = "aqara_cloud"
CONF_REGION = "region"
CONF_ACCESS_TOKEN = "access_token"
CONF_REFRESH_TOKEN = "refresh_token"

REGIONS = {
    "europe": "open-ger.aqara.com",
    "china": "open-cn.aqara.com",
    "usa": "open-usa.aqara.com",
    "russia": "open-rus.aqara.com",
}
```

Это займет ~2-3 часа на разработку. Хотите начать?
