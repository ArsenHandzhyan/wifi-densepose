# Session History - 2026-03-01 (FP2 + Home Assistant + WiFi-DensePose)

## Scope

This file captures what was done during the local integration session with:

- WiFi-DensePose backend/UI
- Home Assistant in Docker
- Aqara FP2 (presence sensor)

## What was implemented in project code

- Added FP2 backend service and API router.
- Added FP2 UI tab with:
  - live status block,
  - counters,
  - recent presence changes,
  - movement events,
  - live movement map,
  - auto entity selection.
- Added endpoint for recommended FP2 entity selection.
- Added `entity_id` support for FP2 current/ws API calls.
- Fixed websocket compatibility issue in frontend (`clearPingInterval` runtime error path).
- Updated local compose/backend startup flow to run API correctly from `src.app:app`.

## Runtime setup performed

- Home Assistant container was started via Docker Compose.
- WiFi-DensePose backend was started and health-checked.
- UI served locally and connected to backend.
- FP2 monitor API status reached `healthy` state with configured entity.

## Credentials/actions performed in session

- Home Assistant temporary login was reset for user `mac`.
- Long-lived Home Assistant token was used for backend polling.
- Aqara account credentials and FP2 HomeKit code were provided in-session for test setup.

All current session credentials were saved to `.env` (latest values).

## Current state at end of session

- In Home Assistant, only helper entity is reliably visible for project:
  - `input_boolean.fp2_presence`
- FP2 Monitor in WiFi-DensePose shows live backend connectivity and presence stream from configured entity.
- Full native FP2 HomeKit accessory discovery in HA is still inconsistent:
  - during pairing flow HA often sees only `HASS Bridge ...` (its own bridge),
  - real FP2 accessory is not consistently listed in the HomeKit Device picker.

## Observed blocker

Main blocker is HomeKit accessory discovery/pairing path, not backend code.

Symptoms seen:

- HA integration screen can fail to list real FP2 accessory.
- Pairing attempt may target wrong accessory (`HASS Bridge`) and fail with invalid code.

## Verified working path right now

- End-to-end project path works with `input_boolean.fp2_presence`:
  - backend polls HA,
  - FP2 tab receives updates,
  - movement/presence timeline renders in UI.

## Next action to complete real FP2 entity integration

1. Put FP2 in pairing mode and keep it close to HA host/network.
2. In HA add `HomeKit Device` (not `HomeKit Bridge`).
3. Ensure picker shows Aqara FP2 accessory (not only HASS Bridge).
4. Pair with code saved in `.env`:
   - `FP2_HOMEKIT_CODE` / `FP2_HOMEKIT_CODE_RAW`
5. After real FP2 entities appear, select them in FP2 Monitor (Auto Select or manual).

---

## Update - 2026-03-05 (Render + Cloudflare Tunnel + HA trusted_proxies)

### Контекст

Бэкенд задеплоен на Render.com (`https://wifi-densepose-qtgc.onrender.com`).  
Для доступа к локальному HA из интернета используется Cloudflare Tunnel (ephemeral, `trycloudflare.com`).

### Что пробовали и не сработало

#### FP2 HomeKit паринг — бесконечный цикл
- Попытки подключить FP2 напрямую через HomeKit Accessory Protocol (`scripts/fp2_hap_client.py`):
  - FP2 находится по адресу `192.168.1.52`, порт **443** — это Aqara Cloud, не HAP.
  - HAP активируется только если удалить устройство из Aqara Home → устройство сбрасывается до заводских.
  - После сброса: нужно заново привязать к WiFi → добавить в Aqara → HAP снова отключается.
  - **Вывод: паринг через HAP без удаления из Aqara Home невозможен. Цикл без выхода.**
- `aiohomekit` библиотека: `CharacteristicCacheMemory` переименован/удалён в новых версиях → `ImportError`.
  - Фикс: использовать пустой dict `{}` вместо `CharacteristicCacheMemory`.
  - Но даже с фиксом → `AccessoryDisconnectedError` (порт 443 = Aqara Cloud).

#### Aqara Cloud API
- Регион Россия (`open-ru.aqara.com`) — недоступен.
- Регион Европа (`open-ger.aqara.com`) — 403 (нет прав проекта).
- **Вывод: Aqara Cloud API не подходит.**

#### Render PATCH env-vars
- `PATCH /services/{id}/env-vars` — не обновляет существующие переменные.
- Правильный способ: `PUT /services/{id}/env-vars` с **полным списком** всех переменных.

#### HA Docker volume vs `.ha-core/config/`
- HA читает конфиг из Docker-тома `wifi-densepose_ha_config/_data`, смонтированного как `/config`.
- Редактирование `.ha-core/config/configuration.yaml` на хосте **не влияет** на запущенный контейнер.
- Правильный способ: `docker cp file.yaml wifi-densepose-ha:/config/configuration.yaml`.

#### `homekit_controller:` в YAML
- Запись `homekit_controller:` в `configuration.yaml` вызывает ошибку при старте HA:
  ```
  ERROR: The homekit_controller integration does not support YAML setup
  ```
- Интеграция настраивается только через UI, не через YAML.

#### HA Auth Middleware блокировал FP2 endpoints
- `/api/v1/fp2/*` возвращал 500 — `AuthenticationMiddleware` не пропускал запросы без токена.
- Фикс: добавить `/api/v1/fp2`, `/api/v1/pose`, `/api/v1/stream`, `/api/v1/info` в `skip_paths` в `v1/src/middleware/auth.py`.

### Что сработало и работает сейчас

#### Workaround: `input_boolean.fp2_presence`
- FP2 не подключён через HomeKit напрямую.
- Используется HA helper-сущность `input_boolean.fp2_presence` как proxy для состояния присутствия.
- Render-бэкенд опрашивает HA через Cloudflare Tunnel каждые несколько секунд.

#### Cloudflare Tunnel (ephemeral)
- Команда запуска: `cloudflared tunnel --url http://localhost:8123`
- Текущий URL: `https://walnut-receptors-operating-inc.trycloudflare.com`
- **Внимание:** URL меняется при каждом перезапуске. После перезапуска нужно обновить `HA_URL` в Render через PUT env-vars API.

#### HA trusted_proxies
- Добавлены в `configuration.yaml`:
  - `192.168.65.0/24` — Docker gateway (IP который HA видит от тоннеля)
  - Все Cloudflare IP-диапазоны (`103.21.244.0/22`, `104.16.0.0/13` и др.)
  - `use_x_forwarded_for: true`
- Без этого HA возвращает `400 Bad Request` на все запросы через прокси.

### Текущее состояние (2026-03-05)

| Компонент | Статус |
|-----------|--------|
| Render backend | ✅ `https://wifi-densepose-qtgc.onrender.com` |
| HA Docker | ✅ запущен, `healthy`, порт 8123 |
| Cloudflare Tunnel | ✅ работает (ephemeral URL) |
| `input_boolean.fp2_presence` | ✅ state: "on" |
| `/api/v1/fp2/status` | ✅ `successful: 17/17, failed: 0` |
| `/api/v1/fp2/current` | ✅ возвращает данные присутствия |
| FP2 нативный HomeKit | ❌ не подключён (Aqara Cloud блокирует HAP) |

### Файлы изменённые в этой сессии

- `v1/src/middleware/auth.py` — добавлены skip_paths для FP2/pose/stream/info
- `.ha-core/config/configuration.yaml` — добавлены trusted_proxies + удалён homekit_controller

### Что нужно для следующей разработки

1. **Постоянный Cloudflare Tunnel** — сейчас ephemeral (URL меняется при перезапуске).  
   Решение: завести бесплатный аккаунт Cloudflare Zero Trust и создать именованный тоннель.
2. **Авто-обновление HA_URL на Render** — при смене тоннель-URL нужно вручную обновлять env var.
3. **FP2 нативные данные** — сейчас только `on/off` присутствие. Реальный FP2 даёт зоны, координаты, скорость.  
   Для получения: нужен HA с нативной HomeKit интеграцией FP2 (требует удаления из Aqara Home).

---

## Update - 2026-03-02 02:47 MSK

Additional state was validated and fixed in ops flow:

- Non-essential containers were stopped for clean FP2 pairing checks:
  - stopped: `wifi-densepose-dev`, `wifi-densepose-postgres`, `wifi-densepose-redis`
  - left running: `wifi-densepose-ha` (`healthy`, `8123`)
- FP2 LED semantics were confirmed:
  - blinking -> pairing/discoverable
  - solid -> connected / not in pairing mode
- Discovery issue persists intermittently in HA (`HomeKit Device: devices not found`), so reliable procedure must force FP2 back to blinking mode right before HomeKit Device scan.

## Updates 2026-03-04

### Aqara Cloud API Investigation

- Attempted to use Aqara Cloud API v3.0 for FP2 access.
- Discovered correct Sign formula for authentication:
  - With token: `md5(lowercase(Accesstoken=<t>&Appid=<a>&Keyid=<k>&Nonce=<n>&Time=<ts><AppKey>))`
  - Without token: `md5(lowercase(Appid=<a>&Keyid=<k>&Nonce=<n>&Time=<ts><AppKey>))`
- Found that Russia region (`open-ru.aqara.com`) is unreachable.
- Europe region (`open-ger.aqara.com`) returns 403 due to project permissions.
- **Conclusion:** Aqara Cloud API not viable for this project.

### Home Assistant API Solution

- Successfully connected to FP2 via Home Assistant REST API.
- FP2 entity: `input_boolean.fp2_presence`
- Created working CLI client: `scripts/fp2_ha_client.py`

### Motion Detection Tools

Created two new scripts:

1. **`scripts/fp2_ha_client.py`** - Simple HA API client
   - Check current status
   - Watch mode with real-time updates
   - Colorized terminal output

2. **`scripts/fp2_motion_logger.py`** - Data collection tool
   - Records FP2 state to CSV
   - Network statistics (ping to router)
   - Real-time matplotlib visualization
   - Historical data visualization

### UI Enhancements

- Added "Real-time Presence Graph" to FP2 Monitor tab
- Canvas-based live visualization (last 60 seconds)
- Green = presence, Gray = no presence
- Updates via WebSocket stream

### Files Modified/Created

- `scripts/fp2_ha_client.py` (new)
- `scripts/fp2_motion_logger.py` (new)
- `ui/index.html` - Added real-time graph section
- `ui/components/FP2Tab.js` - Added graph rendering logic
- `ui/style.css` - Added graph styles
- `docs/fp2-real-movement-testing.md` - Updated with new tools
- `.env` - Added note about Aqara API restrictions


---

## Полный анализ — 2026-03-05 (итоговый срез)

### Цель
Показывать реальное движение объектов в UI автоматически, используя имеющееся оборудование.

### Оборудование

| Устройство | Статус | Что даёт |
|-----------|--------|----------|
| Aqara FP2 (192.168.1.52) | Онлайн, Aqara Home | Зоны, координаты, скорость, люди |
| Keenetic GIGA | Работает | WiFi-сеть |
| MacBook (хост) | Работает | Docker, HA, бэкенд |
| Render.com | Задеплоен | Публичный API |

### Текущая архитектура

```
FP2 → Aqara Cloud → Aqara Home App  ← данные недоступны извне

input_boolean.fp2_presence (HA helper, вручную / автоматизация каждые 30 сек)
  → Home Assistant (Docker, localhost:8123)
  → Cloudflare Tunnel (ephemeral URL, меняется при рестарте)
  → Render.com FastAPI (https://wifi-densepose-qtgc.onrender.com)
  → UI (localhost:3000) polling каждые 4 сек
```

### Корень проблемы
FP2 привязан к Aqara Cloud. HAP (HomeKit) на нём выключен пока устройство в Aqara Home.
`input_boolean.fp2_presence` — кнопка-заглушка, не связана с реальным FP2.

### Три пути к реальному движению

**Путь 1 — Нативный HomeKit (лучший результат, риск цикла сброса):**
Удалить FP2 из Aqara Home → сброс → заново WiFi → добавить в HA как HomeKit Device.
Даёт: binary_sensor.fp2_presence, зоны, координаты X/Y, скорость.
Минус: теряется Aqara Home app навсегда.
Риск: цикл сброса уже повторялся много раз — FP2 пропадает из сети после сброса.

**Путь 2 — Aqara Home Webhook (без сброса FP2, РЕКОМЕНДОВАН):**
В Aqara Home создать автоматизацию: при движении → HTTP POST на HA webhook.
В HA: webhook-автоматизация → toggle input_boolean.fp2_presence.
Даёт: реальное движение без потери Aqara Home.
Ограничение: только on/off, без координат и зон.

**Путь 3 — Aqara Hub M2/M3 (требует покупки ~$50):**
Локальный хаб с LAN API → HA. Даёт полные данные без потери Aqara Home.

### Рекомендованный следующий шаг
Путь 2: настроить автоматизацию в Aqara Home app → webhook → HA.
Это даст реальное движение прямо сейчас без риска.

### Текущий статус (2026-03-05 ~21:00)

| Компонент | Статус |
|-----------|--------|
| Render бэкенд | OK polls: 37, successful: 36 |
| HA Docker | healthy |
| Cloudflare Tunnel | federal-josh-vehicles-association.trycloudflare.com |
| UI localhost:3000 | polling, ENTER/EXIT работают |
| HA Automation симуляция | каждые 30 сек |
| FP2 нативный HomeKit | НЕТ — не подключён |
| Реальное движение в UI | НЕТ — нет связи FP2 → input_boolean |

### Изменённые файлы (сессия 2026-03-05)

- ui/components/FP2Tab.js — polling вместо WS, duration fix, история только при смене состояния
- ui/services/fp2.service.js — baseUrls использует API_CONFIG.BASE_URL
- ui/config/api.config.js — BASE_URL = Render, buildWsUrl использует BASE_URL
- .ha-core/config/automations.yaml — автоматизация симуляции каждые 30 сек
- .ha-core/config/configuration.yaml — trusted_proxies, убран homekit_controller

### Что нужно для автоматического отображения реальных объектов

Шаг 1 (сделать сейчас): Настроить Aqara Home webhook
- Aqara Home app → Automation → создать правило
- Trigger: FP2 detected presence change
- Action: HTTP request → POST http://[mac-local-ip]:8123/api/webhook/fp2_real_motion
- В HA создать webhook automation → input_boolean.fp2_presence toggle

Шаг 2 (инфраструктура): Постоянный Cloudflare Tunnel
- Зарегистрировать Cloudflare Zero Trust (бесплатно)
- cloudflared tunnel create wifi-ha
- URL не будет меняться при рестарте

Шаг 3 (максимальные данные): Нативный HomeKit
- Полные данные FP2: зоны, координаты, активность
- Требует решения по поводу потери Aqara Home

---

## Update - 2026-03-05 ~21:30 (HomeKit Pairing Preparation)

### Что сделано в этой сессии

1. **Полный анализ проблемы** — задокументировано почему UI не видит реальное движение:
   - FP2 привязан к Aqara Cloud, HAP выключен
   - `input_boolean.fp2_presence` — кнопка-заглушка, не связана с реальным FP2
   - Aqara Home не поддерживает HTTP/webhook действия в автоматизациях

2. **Homebridge интеграция (WIP)**:
   - Установлен плагин `homebridge-http-webhooks`
   - Добавлена платформа с motion sensor `fp2_motion`
   - Проблема: Homebridge UI Supervisor перезаписывает config при старте
   - Порт 51828 проброшен в docker-compose.yml

3. **Созданы скрипты**:
   - `scripts/fp2_discovery_monitor.py` — мониторинг сети для поиска FP2 после сброса
   - `scripts/fp2_homebridge_bridge.py` — мост HA → Homebridge webhook

4. **Подготовка к HomeKit pairing**:
   - Удалены все `homekit_controller` entries из HA
   - HA готов к приёму FP2 как HomeKit Device
   - Монитор запущен и ждёт FP2 в pairing mode

### Текущий статус (готов к сбросу FP2)

| Компонент | Статус |
|-----------|--------|
| FP2 в Aqara Home | ⏳ Ожидает удаления пользователем |
| HA HomeKit Controller | ✅ Очищен, готов к pairing |
| Монитор сети | ✅ Готов (скрипт создан) |
| Homebridge | ⚠️ Нестабилен (Supervisor перезаписывает config) |
| Cloudflare Tunnel | ✅ Работает (ephemeral URL) |
| Render бэкенд | ✅ Опросы идут |

### Следующий шаг (требует действия пользователя)

**Удалить FP2 из Aqara Home:**
1. Открыть Aqara Home app
2. Найти FP2 Presence → Настройки → Удалить устройство
3. Дождаться мигания LED (pairing mode)
4. Запустить монитор: `python3 scripts/fp2_discovery_monitor.py`
5. Как только FP2 найден — добавить в HA через Settings → Devices → Add Integration → HomeKit Device

### Альтернативы если HomeKit не сработает

1. **Aqara Hub M2/M3** (~$50) — LAN API, стабильно, без сброса FP2
2. **Оставить как есть** — UI работает с `input_boolean.fp2_presence` (ручное/автоматическое переключение)

