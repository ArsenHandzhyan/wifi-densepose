# 🎯 ФИНАЛЬНАЯ ИНСТРУКЦИЯ - Получение токена Aqara

> Archival FP2/Aqara note (2026-03-29):
> this document belongs to an earlier FP2/Home Assistant integration line and
> is preserved only as historical reference for that thread.
> Any setup flow, status wording, endpoint examples, or device metadata below
> should be read as archival context rather than current repo truth.
> For the current canonical repo state and active entrypoints, use
> `/Users/arsen/Desktop/wifi-densepose/docs/CURRENT_DOCS_ENTRYPOINT_20260329.md`
> and `/Users/arsen/Desktop/wifi-densepose/docs/CURRENT_PROJECT_STATE_20260329.md`.

## 📊 Текущая ситуация

✅ **SIGN generation** - ИСПРАВЛЕН (алгоритм работает правильно)  
✅ **Virtual account** - СОЗДАН (токен есть, но нет доступа к устройству)  
❌ **Main account login** - БЛОКИРОВАН (rate limit + 403 error)  

---

## 🔑 ПРОБЛЕМА

API Aqara блокирует попытки логина через `account.loginByPassword` с ошибкой **403 Forbidden**.

**Причина**: Для безопасности Aqara требует сначала войти через мобильное приложение, чтобы активировать сессию.

---

## ✅ РЕШЕНИЕ (2 варианта)

### Вариант 1: Войти через Aqara Home App (БЫСТРЫЙ)

1. **Откройте приложение Aqara Home на телефоне**
2. **Войдите с credentials**:
   - Email: `<your_aqara_email>`
   - Password: `<your_aqara_password>`
3. **Убедитесь что устройство FP2 видно в приложении**
4. **Подождите 2-3 минуты**
5. **Запустите скрипт**:
   ```bash
   python3 scripts/get_aqara_token.py
   ```

**Ожидаемый результат**: Успешный логин + получение access token

---

### Вариант 2: Ждать снятия rate limit (ДОЛГИЙ)

1. **Подождите 10-15 минут** (полное снятие rate limits)
2. **Попробуйте снова**:
   ```bash
   python3 scripts/login_direct.py
   ```

**Шанс успеха**: ~50% (может все равно требовать вход через app)

---

## 🎫 Альтернатива: Virtual Account

У нас есть рабочий токен виртуального аккаунта:
```
Access Token: <redacted_access_token>
Valid: 30 дней
```

**Проблема**: Виртуальный аккаунт не имеет доступа к вашему FP2 устройству.

**Решение**: Нужно предоставить доступ через приложение Aqara Home:
1. Открыть настройки дома
2. Добавить пользователя (виртуальный аккаунт)
3. Дать права на устройство FP2

Но это сложнее чем просто войти в основной аккаунт.

---

## 📝 Команды для тестирования

```bash
# Проверить текущий токен
python3 scripts/test_new_token.py

# Получить токен через main account (после входа в app)
python3 scripts/get_aqara_token.py

# Или прямой логин
python3 scripts/login_direct.py

# Обновить токены в HA
python3 scripts/refresh_aqara_tokens.py

# Перезапустить Home Assistant
docker restart wifi-densepose-ha

# Проверить логи
docker logs wifi-densepose-ha | grep aqara
```

---

## 🎯 Рекомендация

**СЕЙЧАС**: Откройте Aqara Home app на телефоне и войдите в аккаунт.

**ЧЕРЕЗ 2 МИНУТЫ**: Запустите `python3 scripts/get_aqara_token.py`

**ПОСЛЕ УСПЕХА**: 
1. Скрипт автоматически обновит `.env`
2. Restart Home Assistant: `docker restart wifi-densepose-ha`
3. Проверьте интеграцию в UI

---

## 📞 Контакты

Если все еще проблемы:
1. Проверьте что регион в приложении установлен **Germany/Europe**
2. Убедитесь что email/password верные
3. Попробуйте сбросить пароль в приложении

---

**Last Updated**: 2026-03-06 01:45 UTC  
**Status**: Waiting for user to login via Aqara Home app ⏳
