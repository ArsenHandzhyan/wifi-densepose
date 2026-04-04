# Настройка Homebridge и интеграция с Home Assistant

> Archival FP2/Aqara note (2026-03-29):
> this document belongs to an earlier FP2/Home Assistant integration line and
> is preserved only as historical reference for that thread.
> Any setup flow, status wording, endpoint examples, or device metadata below
> should be read as archival context rather than current repo truth.
> For the current canonical repo state and active entrypoints, use
> `/Users/arsen/Desktop/wifi-densepose/docs/CURRENT_DOCS_ENTRYPOINT_20260329.md`
> and `/Users/arsen/Desktop/wifi-densepose/docs/CURRENT_PROJECT_STATE_20260329.md`.

## Дата добавления: 2026-03-05

## Обзор

В данном документе описан полный процесс настройки Homebridge для интеграции устройств HomeKit (в частности Aqara FP2) с Home Assistant через протокол HomeKit Controller.

---

## 1. Текущая конфигурация

### Homebridge мост
- **Имя**: Homebridge B96B
- **Полное имя**: Homebridge B96B 542A (Bridge)
- **Расположение**: Гостиная
- **Username**: `<redacted-homebridge-username>`
- **Port**: `51972`
- **PIN код**: `<redacted-homebridge-pin>`
- **Serial Number**: `<redacted-homebridge-serial>`
- **Software Version**: 1.11.2
- **Website**: homebridge.io

### Файл конфигурации
Путь: `/Users/arsen/Desktop/wifi-densepose/homebridge/config.json`

```json
{
    "bridge": {
        "name": "Homebridge B96B",
        "username": "<redacted-homebridge-username>",
        "port": 51972,
        "pin": "<redacted-homebridge-pin>",
        "advertiser": "bonjour-hap"
    },
    "accessories": [],
    "platforms": [
        {
            "name": "Config",
            "port": 8581,
            "platform": "config"
        }
    ]
}
```

### Веб-интерфейс управления
- **URL**: `http://localhost:8581`
- **Плагин управления**: Homebridge Config UI X

---

## 2. Проблема Docker на macOS

### Описание проблемы
Home Assistant запущен в Docker на macOS, что создает ограничения для обнаружения устройств HomeKit:

**⚠️ Docker на macOS блокирует mDNS/Broadcast трафик**

Это означает, что устройства HomeKit не могут быть автоматически обнаружены через стандартный механизм Bonjour/mDNS.

### Решение
Для интеграции устройств HomeKit необходимо использовать **ручную настройку** с указанием статического IP-адреса устройства.

### Затронутые компоненты
- Home Assistant Core (Docker container)
- macOS host system
- Keenetic GIGA router
- Устройства HomeKit (FP2 и другие)

---

## 3. Процесс добавления Homebridge в Home Assistant

### Шаг 1: Подготовка
1. Убедитесь, что Homebridge запущен и доступен в сети
2. Проверьте, что порт 51972 открыт для подключений
3. Подготовьте PIN код: `<redacted-homebridge-pin>`

### Шаг 2: Добавление интеграции HomeKit Controller

#### Найденное устройство FP2
- **IP-адрес**: `192.168.1.52`
- **MAC-адрес**: `54:ef:44:79:e0:3`
- **Состояние**: Режим сопряжения (мигающий LED)

1. Откройте Home Assistant
   - URL: `http://localhost:8123` (или ваш настроенный URL)

2. Перейдите в раздел:
   - **Настройки** → **Устройства и службы**

3. Нажмите кнопку **"Добавить интеграцию"**

4. В поиске введите: **"HomeKit Controller"**
   - ⚠️ Важно: Выберите именно "HomeKit Controller", а не "HomeKit Bridge"
   - HomeKit Controller позволяет Home Assistant управлять устройствами HomeKit
   - HomeKit Bridge позволяет Home Assistant отдавать устройства в Apple Home

5. **Если FP2 не отображается в списке автоматически:**
   - Прокрутите вниз до конца списка
   - Нажмите **"Устройство не найдено? Добавьте вручную"** или аналогичную ссылку
   - Введите IP адрес: **192.168.1.52**
   - Порт: **80** (по умолчанию для HomeKit)

6. Если устройство найдено автоматически:
   - Выберите из списка: **EP2016** или **Aqara FP2**

7. Введите код сопряжения:
   - Format: `XXX-XX-XXX`
   - Код находится на коробке от FP2 или на самом устройстве
   - Ищите наклейку со штрих-кодом HomeKit и маленьким домиком

### Шаг 3: Завершение настройки

После успешного ввода кода:
1. ✅ Home Assistant установит безопасное зашифрованное соединение с Homebridge
2. ✅ Homebridge будет отображаться как устройство в Home Assistant
3. 🔄 Все устройства, добавленные в Homebridge, появятся в Home Assistant

### Шаг 4: Проверка интеграции

После добавления проверьте:
1. **Настройки** → **Устройства и службы** → **Интеграции**
2. Найдите **"Homebridge B96B"**
3. Проверьте количество связанных устройств
4. Проверьте доступные объекты (entities)

---

## 4. Добавление Aqara FP2 через Homebridge

### Вариант A: Использование плагина homebridge-aqara (Рекомендуется)

#### Установка плагина

1. Откройте веб-интерфейс Homebridge: `http://localhost:8581`

2. Перейдите в раздел **Plugins**

3. Найдите плагин: **homebridge-aqara**

4. Нажмите **Install**

#### Конфигурация плагина

После установки добавьте конфигурацию в `config.json`:

```json
{
    "platforms": [
        {
            "name": "Config",
            "port": 8581,
            "platform": "config"
        },
        {
            "platform": "Aqara",
            "name": "Aqara",
            "username": "your_email_or_phone",
            "password": "your_password",
            "region": "europe"
        }
    ]
}
```

#### Параметры конфигурации

- **username**: Email или номер телефона от аккаунта Aqara Home
- **password**: Пароль от аккаунта Aqara Home
- **region**: Регион аккаунта
  - `europe` - для европейских аккаунтов (Германия)
  - `china` - для китайских аккаунтов
  - `russia` - для российских аккаунтов (open-ru.aqara.com)

#### После настройки

1. Перезапустите Homebridge через веб-интерфейс
2. Дождитесь синхронизации с серверами Aqara
3. Проверьте, что FP2 появился в списке устройств Homebridge
4. Устройство автоматически появится в Home Assistant

### Вариант B: Прямое подключение FP2 к Home Assistant

Если не хотите использовать Homebridge как промежуточный слой:

1. Узнайте IP-адрес FP2 в роутере Keenetic GIGA
   - Обычно: `192.168.1.52`
   
2. В Home Assistant:
   - Настройки → Устройства и службы
   - Добавить интеграцию → HomeKit Controller
   
3. Введите вручную:
   - IP адрес: `192.168.1.XXX`
   - Код сопряжения с устройства FP2 (не от Homebridge!)

---

## 5. Диагностика и устранение проблем

### Проблема: Homebridge не обнаруживается

**Причина**: Блокировка mDNS в Docker

**Решение**:
- Используйте ручное добавление по IP адресу
- Убедитесь, что Homebridge и Home Assistant в одной подсети
- Проверьте firewall на macOS

### Проблема: Устройства не появляются после добавления моста

**Причина**: Устройства не добавлены в Homebridge

**Решение**:
- Установите соответствующие плагины в Homebridge
- Настройте плагины с учетными данными
- Перезапустите Homebridge

### Проблема: Ошибка кода сопряжения

**Причина**: Неверный формат или код

**Решение**:
- Используйте формат XXX-XX-XXX
- Проверьте код в файле config.json
- Убедитесь, что устройство еще не сопряжено с другим контроллером

### Проверка статуса Homebridge

Через веб-интерфейс (`http://localhost:8581`):
1. Проверьте статус на главной странице
2. Посмотрите логи в разделе **Logs**
3. Проверьте установленные плагины в **Plugins**

### Просмотр логов Homebridge

```bash
# Через веб-интерфейс
http://localhost:8581/logs

# Или через терминал (если Homebridge запущен напрямую)
journalctl -u homebridge -f
```

---

## 6. Автоматизации и сценарии

### Текущее состояние
- **Автоматизации**: Отсутствуют
- **Сцены**: Отсутствуют
- **Скрипты**: Отсутствуют

### Рекомендации по созданию автоматизаций

После добавления FP2 можно создать:

1. **Обнаружение присутствия**
   - Триггер: FP2 обнаружил движение
   - Действие: Включить свет в комнате

2. **Мониторинг активности**
   - Триггер: Отсутствие движения N минут
   - Действие: Отправить уведомление

3. **Ночной режим**
   - Триггер: Время + отсутствие движения
   - Действие: Выключить весь свет, включить сигнализацию

---

## 7. Сетевая конфигурация

### Требуемые порты

| Порт | Протокол | Назначение |
|------|----------|------------|
| 51972 | TCP | Homebridge HAP сервер |
| 8581 | TCP | Homebridge Config UI X |
| 5353 | UDP | mDNS/Bonjour (блокируется Docker) |

### Сетевые требования

- Все устройства должны быть в одной подсети
- Multicast DNS должен быть разрешен между VLAN (если используются)
- Firewall не должен блокировать локальный трафик

### Статические IP адреса

Рекомендуется назначить статические IP адреса:
- Homebridge server
- Home Assistant
- FP2 device (через DHCP reservation в роутере)

---

## 8. Безопасность

### Шифрование
- HomeKit использует безопасное зашифрованное соединение
- Ключи шифрования хранятся в Home Assistant
- iCloud не требуется для локальной работы

### Доступ к веб-интерфейсу Homebridge
- По умолчанию доступен только локально
- Для удаленного доступа используйте VPN или Cloudflare Tunnel
- Рекомендуется сменить пароль по умолчанию

### Рекомендуемые практики
1. Регулярно обновляйте Homebridge и плагины
2. Используйте сложные пароли для плагинов
3. Ограничьте доступ к веб-интерфейсу
4. Делайте резервные копии конфигурации

---

## 9. Резервное копирование

### Файлы для备份

```bash
# Основная конфигурация
/Users/arsen/Desktop/wifi-densepose/homebridge/config.json

# Данные Persist (ключи шифрования)
/Users/arsen/Desktop/wifi-densepose/homebridge/persist/

# Резервные копии
/Users/arsen/Desktop/wifi-densepose/homebridge/backups/
```

### Создание резервной копии

```bash
# Создать резервную копию конфигурации
cp /Users/arsen/Desktop/wifi-densepose/homebridge/config.json \
   /Users/arsen/Desktop/wifi-densepose/homebridge/backups/config-backup-$(date +%Y%m%d).json
```

---

## 10. История изменений

### 2026-03-05
- ✅ Добавлена документация по настройке Homebridge
- ✅ Задокументирована текущая конфигурация Homebridge B96B
- ✅ Описан процесс интеграции с Home Assistant
- ✅ Добавлены инструкции по установке плагинов Aqara
- ✅ Задокументированы ограничения Docker на macOS
- ✅ Добавлены разделы по диагностике и безопасности

---

## 11. Полезные ссылки

- Официальная документация Homebridge: https://homebridge.io/
- Плагин homebridge-aqara: https://github.com/homebridge-plugins/homebridge-aqara
- Документация Home Assistant HomeKit Controller: https://www.home-assistant.io/integrations/homekit_controller/
- Список совместимых устройств: https://homebridge.github.io/homebridge-aqara/

---

## 12. Контакты и поддержка

При возникновении проблем:
1. Проверьте логи Homebridge через веб-интерфейс
2. Посетите форум Homebridge: https://github.com/homebridge/homebridge/discussions
3. Проверьте issues на GitHub соответствующего плагина
