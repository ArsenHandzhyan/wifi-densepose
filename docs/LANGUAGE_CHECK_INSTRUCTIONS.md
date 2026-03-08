# 🧪 ПРОВЕРКА ПЕРЕКЛЮЧЕНИЯ ЯЗЫКА

## ✅ БЫСТРАЯ ПРОВЕРКА

### Вариант 1: Тестовая страница

**Откройте:** http://127.0.0.1:3000/test_language.html

Нажмите кнопки:
1. **Тестировать window.t()** - Проверит функцию перевода
2. **Проверить getCurrentLang()** - Покажет текущий язык
3. **Переключить RU ↔ EN** - Переключит язык
4. **Тестировать все переводы** - Покажет все словари

---

### Вариант 2: В основном UI

**Откройте:** http://127.0.0.1:3000

**Проверьте:**

#### 1. Кнопка переключения
В верхнем правом углу должна быть кнопка:
```
🇷🇺 RU  (или 🇬🇧 EN)
```

#### 2. Нажмите на кнопку
Должно переключиться:
- 🇷🇺 RU → 🇬🇧 EN
- 🇬🇧 EN → 🇷🇺 RU

#### 3. Проверьте тексты

**На русском (🇷🇺 RU):**
```
Панель управления
Монитор FP2
Присутствие: ЕСТЬ
Движение: Движение (7)
Падение: Нет падения (0)
Зона: ЗАНЯТО
```

**На английском (🇬🇧 EN):**
```
Dashboard
FP2 Monitor
Presence: PRESENT
Movement: Moving (7)
Fall: No fall detected (0)
Zone: OCCUPIED
```

---

## 🔍 ДИАГНОСТИКА

### Если переключение НЕ работает:

#### 1. Проверьте консоль браузера

**Откройте DevTools** (F12 или Cmd+Option+I на Mac)  
**Перейдите во вкладку Console**

Ищите ошибки:
```
❌ "window.t is not defined"
❌ "getCurrentLang is not defined"
❌ "applyLanguage is not a function"
```

#### 2. Очистите кэш

**Mac:** Cmd+Shift+R  
**Windows:** Ctrl+Shift+R

Или:
- Откройте DevTools
- Правой кнопкой на кнопке Refresh
- Выберите "Empty Cache and Hard Reload"

#### 3. Проверьте версию CSS

В `index.html` должно быть:
```html
<link rel="stylesheet" href="style.css?v=20260308-v5">
```

Если версия старая (v4 или ниже) → очистите кэш!

---

## 📊 ТЕХНИЧЕСКАЯ ПРОВЕРКА

### Через браузерную консоль:

**Откройте консоль (F12) и выполните:**

```javascript
// 1. Проверка функции перевода
console.log('window.t:', typeof window.t);
console.log('present (RU):', window.t('present'));

// 2. Текущий язык
console.log('Current lang:', window.getCurrentLang());

// 3. Словари
console.log('i18n available:', typeof window.i18n);
console.log('EN present:', window.i18n.en.present);
console.log('RU present:', window.i18n.ru.present);

// 4. Переключение языка
window.wifiDensePoseApp.applyLanguage('en');
console.log('After switch to EN:', window.t('present'));

window.wifiDensePoseApp.applyLanguage('ru');
console.log('After switch to RU:', window.t('present'));
```

**Ожидаемые результаты:**
```
window.t: function
present (RU): ЕСТЬ
Current lang: ru
i18n available: object
EN present: PRESENT
RU present: ЕСТЬ
After switch to EN: PRESENT
After switch to RU: ЕСТЬ
```

---

## ✅ ВСЁ РАБОТАЕТ ЕСЛИ:

- [x] Кнопка 🇷🇺 RU / 🇬🇧 EN видима
- [x] При клике язык меняется
- [x] Тексты переводятся
- [x] localStorage сохраняется
- [x] После перезагрузки страницы язык сохраняется

---

## 🐛 ВОЗМОЖНЫЕ ПРОБЛЕМЫ

### 1. "Кнопки нет"

**Решение:**
- Убедитесь что используете свежую версию
- Очистите кэш браузера
- Проверьте index.html

### 2. "Кнопка есть, но не работает"

**Решение:**
- Проверьте консоль на ошибки
- Убедитесь что app.js загрузился
- Перезагрузите страницу (Cmd+Shift+R)

### 3. "Переводится не всё"

**Решение:**
- Некоторые тексты могут быть захардкожены в компонентах
- Проверьте DashboardTab.js и FP2Tab.js
- Все тексты должны использовать window.t()

### 4. "Сохраняется старый язык"

**Решение:**
```javascript
// В консоли выполните:
localStorage.removeItem('fp2_lang');
location.reload();
// По умолчанию будет русский
```

---

## 📝 ФАЙЛЫ ДЛЯ ПРОВЕРКИ

**Основные файлы:**
- `ui/index.html` - Кнопка переключения
- `ui/app.js` - i18n система и словари
- `ui/components/DashboardTab.js` - Использует window.t()
- `ui/components/FP2Tab.js` - Использует window.t()

**Тестовая страница:**
- `ui/test_language.html` - Автоматические тесты

---

## 🚀 АВТОМАТИЧЕСКИЙ ТЕСТ

**Откройте в браузере:**
```
http://127.0.0.1:3000/test_language.html
```

**Автоматически проверит:**
- ✅ window.t() функция доступна
- ✅ getCurrentLang() работает
- ✅ Словари загружены
- ✅ Переводы корректны

**Результаты отобразятся на странице!**

---

**ГОТОВО!** 🎉

Если тесты прошли успешно → переключение языка работает!
