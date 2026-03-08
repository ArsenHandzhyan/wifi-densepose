#!/usr/bin/env python3
"""
Тестирование Fall Detection (обнаружение падения)

Проверяет:
1. Текущий статус fall detection
2. Коди fall state (0=нет, 1=возможно, 2=обнаружено)
3. Формирует alert при обнаружении падения
"""

import requests
import json
import time
from datetime import datetime

BACKEND_URL = "http://127.0.0.1:8000"

def get_fp2_data():
    """Получить текущие данные FP2."""
    try:
        response = requests.get(f"{BACKEND_URL}/api/v1/fp2/current", timeout=5)
        response.raise_for_status()
        return response.json()
    except Exception as e:
        print(f"❌ Ошибка получения данных: {e}")
        return None

def check_fall_detection():
    """Проверить статус fall detection."""
    print("="*80)
    print("🚨 ТЕСТИРОВАНИЕ FALL DETECTION")
    print("="*80)
    print()
    
    data = get_fp2_data()
    if not data:
        print("❌ Backend недоступен")
        return
    
    ra = data['metadata']['raw_attributes']
    fall_state = ra.get('fall_state')
    
    # Расшифровка кодов
    fall_labels = {
        0: "✅ Нет падения (норма)",
        1: "⚠️  ВОЗМОЖНО ПАДЕНИЕ! (тревога)",
        2: "🔴 ОБНАРУЖЕНО ПАДЕНИЕ! (SOS)"
    }
    
    print(f"📊 Текущий статус:")
    print(f"   Fall State Code: {fall_state}")
    print(f"   Статус: {fall_labels.get(fall_state, 'Неизвестно')}")
    print()
    
    # Проверка alert
    if fall_state in [1, 2]:
        print("🚨 ТРЕВОГА! СРАБОТАЛ FALL DETECTION!")
        print()
        print("Рекомендуемые действия:")
        print("  1. Проверить человека")
        print("  2. При необходимости вызвать помощь")
        print("  3. Зафиксировать время события")
        print()
        
        # Логирование события
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        with open("/tmp/fall_alerts.log", "a") as f:
            f.write(f"[{timestamp}] FALL ALERT: Code {fall_state}\n")
        print(f"📝 Событие записано в /tmp/fall_alerts.log")
    else:
        print("✅ Fall detection не активен")
        print("   Человек в нормальном состоянии")
    
    print()
    print("="*80)

def monitor_fall_continuous(interval=2.0):
    """Непрерывный мониторинг fall detection."""
    print("\n🔍 НЕПРЕРЫВНЫЙ МОНИТОРИNG FALL DETECTION...")
    print(f"Интервал опроса: {interval}s")
    print("Нажмите Ctrl+C для остановки")
    print()
    
    last_fall_state = None
    alert_count = 0
    
    try:
        while True:
            data = get_fp2_data()
            if not data:
                print(f"[{datetime.now().strftime('%H:%M:%S')}] ⚠️  Backend недоступен")
                time.sleep(interval)
                continue
            
            ra = data['metadata']['raw_attributes']
            fall_state = ra.get('fall_state')
            
            # Детектирование изменений
            if fall_state != last_fall_state:
                timestamp = datetime.now().strftime("%H:%M:%S")
                
                if fall_state == 0:
                    print(f"[{timestamp}] ✅ Нормальное состояние")
                elif fall_state == 1:
                    print(f"[{timestamp}] ⚠️  ВОЗМОЖНО ПАДЕНИЕ!")
                    alert_count += 1
                elif fall_state == 2:
                    print(f"[{timestamp}] 🔴 ОБНАРУЖЕНО ПАДЕНИЕ!")
                    alert_count += 1
                
                # Логирование
                with open("/tmp/fall_events.log", "a") as f:
                    f.write(f"[{timestamp}] Fall State: {fall_state}\n")
                
                last_fall_state = fall_state
            
            time.sleep(interval)
    
    except KeyboardInterrupt:
        print(f"\n\n⏹️  Остановлено пользователем")
        print(f"Всего событий: {alert_count}")
        print(f"Лог сохранён: /tmp/fall_events.log")

if __name__ == "__main__":
    import argparse
    
    parser = argparse.ArgumentParser(description="Тестирование Fall Detection")
    parser.add_argument("--monitor", action="store_true", help="Непрерывный мониторинг")
    parser.add_argument("--interval", type=float, default=2.0, help="Интервал опроса (сек)")
    args = parser.parse_args()
    
    if args.monitor:
        monitor_fall_continuous(args.interval)
    else:
        check_fall_detection()
