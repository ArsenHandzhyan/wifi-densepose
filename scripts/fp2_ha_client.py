#!/usr/bin/env python3
"""
FP2 клиент через Home Assistant API.

Этот скрипт получает данные с FP2 (Presence Sensor) через Home Assistant,
так как Aqara Cloud API недоступен для России (open-ru.aqara.com не работает).

Требования:
  - Home Assistant запущен на localhost:8123
  - FP2 добавлен в Home Assistant через интеграцию
  - Сущность input_boolean.fp2_presence существует

Использование:
  python3 fp2_ha_client.py           # Получить текущий статус
  python3 fp2_ha_client.py --watch   # Следить за изменениями в реальном времени
"""

import argparse
import json
import os
import sys
import time
from datetime import datetime

import requests

# === Configuration ===
HA_URL = os.getenv("HA_URL", "http://localhost:8123")
HA_TOKEN = os.getenv("HA_TOKEN", "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJpc3MiOiI2NWQ5NjQ1ZmI1NTY0OThiOWEyNjc4ZTg0OTczN2QyNCIsImlhdCI6MTc3MjM3MTQzNCwiZXhwIjoyMDg3NzMxNDM0fQ.qpkDjaOaY4sNzz-lzd5wfVUcJXJnoR5p1ca5wQfF13g")
FP2_ENTITY = os.getenv("FP2_ENTITY", "input_boolean.fp2_presence")

# Цвета для терминала
GREEN = "\033[92m"
RED = "\033[91m"
YELLOW = "\033[93m"
RESET = "\033[0m"


def get_headers():
    """Возвращает заголовки для запросов к HA."""
    return {
        "Authorization": f"Bearer {HA_TOKEN}",
        "Content-Type": "application/json"
    }


def check_ha_connection():
    """Проверяет доступность Home Assistant."""
    try:
        r = requests.get(f"{HA_URL}/api/", headers=get_headers(), timeout=5)
        return r.status_code == 200
    except requests.exceptions.ConnectionError:
        return False


def get_fp2_state():
    """Получает текущее состояние FP2."""
    r = requests.get(f"{HA_URL}/api/states/{FP2_ENTITY}", headers=get_headers(), timeout=10)
    r.raise_for_status()
    return r.json()


def format_state(state_data):
    """Форматирует состояние для вывода."""
    state = state_data.get('state', 'unknown')
    entity_id = state_data.get('entity_id', 'N/A')
    last_updated = state_data.get('last_updated', 'N/A')
    
    # Цветной статус
    if state.lower() == 'on':
        state_colored = f"{GREEN}🟢 ПРИСУТСТВИЕ ОБНАРУЖЕНО{RESET}"
    elif state.lower() == 'off':
        state_colored = f"{RED}🔴 НЕТ ПРИСУТСТВИЯ{RESET}"
    else:
        state_colored = f"{YELLOW}⚠️ {state.upper()}{RESET}"
    
    return {
        'entity_id': entity_id,
        'state': state,
        'state_colored': state_colored,
        'last_updated': last_updated
    }


def print_state(state_data):
    """Выводит состояние FP2."""
    formatted = format_state(state_data)
    
    print("\n" + "=" * 60)
    print(f"  📡 FP2 СТАТУС")
    print("=" * 60)
    print(f"\n   Entity:     {formatted['entity_id']}")
    print(f"   Состояние:  {formatted['state_colored']}")
    print(f"   Обновлено:  {formatted['last_updated']}")
    
    attrs = state_data.get('attributes', {})
    if attrs:
        print(f"\n   Дополнительно:")
        for k, v in attrs.items():
            print(f"     • {k}: {v}")
    print()


def watch_mode(interval=1.0):
    """Режим наблюдения за изменениями."""
    print(f"\n{YELLOW}👁️ Режим наблюдения (Ctrl+C для выхода){RESET}\n")
    
    last_state = None
    try:
        while True:
            state_data = get_fp2_state()
            current_state = state_data.get('state')
            
            if current_state != last_state:
                timestamp = datetime.now().strftime("%H:%M:%S")
                formatted = format_state(state_data)
                
                if current_state.lower() == 'on':
                    icon = "🚶"
                    msg = "Человек обнаружен"
                else:
                    icon = "👻"
                    msg = "Зона пуста"
                
                print(f"[{timestamp}] {icon} {msg}")
                last_state = current_state
            
            time.sleep(interval)
            
    except KeyboardInterrupt:
        print(f"\n\n{YELLOW}⏹️ Наблюдение остановлено{RESET}")


def main():
    parser = argparse.ArgumentParser(
        description='FP2 клиент через Home Assistant API',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Примеры:
  %(prog)s                    # Получить текущий статус
  %(prog)s --watch            # Следить за изменениями
  %(prog)s --watch -i 0.5     # Следить с интервалом 0.5 сек
        """
    )
    parser.add_argument('--watch', '-w', action='store_true', help='Режим наблюдения')
    parser.add_argument('--interval', '-i', type=float, default=1.0, help='Интервал опроса (сек)')
    args = parser.parse_args()
    
    # Проверка соединения
    if not check_ha_connection():
        print(f"{RED}❌ Ошибка: Home Assistant недоступен по {HA_URL}{RESET}")
        print("\nПроверьте:")
        print("  1. Запущен ли Home Assistant")
        print("  2. Правильность URL и токена")
        sys.exit(1)
    
    try:
        if args.watch:
            watch_mode(args.interval)
        else:
            state = get_fp2_state()
            print_state(state)
            
    except requests.exceptions.HTTPError as e:
        if e.response.status_code == 404:
            print(f"{RED}❌ Сущность {FP2_ENTITY} не найдена{RESET}")
            print("\nПроверьте:")
            print("  1. Добавлен ли FP2 в Home Assistant")
            print("  2. Правильность имени сущности")
        else:
            print(f"{RED}❌ HTTP ошибка: {e}{RESET}")
    except Exception as e:
        print(f"{RED}❌ Ошибка: {e}{RESET}")


if __name__ == "__main__":
    main()
