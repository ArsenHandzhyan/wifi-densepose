#!/usr/bin/env python3
"""
Настройка и мониторинг зон FP2 (Zone Occupancy Monitoring)

Что делает:
1. Проверяет текущие настройки зон
2. Показывает все zone occupancy endpoints
3. Мониторит занятость зон в реальном времени
4. Предлагает рекомендации по настройке
"""

import requests
import json
from datetime import datetime

BACKEND_URL = "http://127.0.0.1:8000"

def get_fp2_data():
    """Получить текущие данные FP2."""
    try:
        response = requests.get(f"{BACKEND_URL}/api/v1/fp2/current", timeout=5)
        response.raise_for_status()
        return response.json()
    except Exception as e:
        print(f"❌ Ошибка: {e}")
        return None

def analyze_zones():
    """Анализ текущей конфигурации зон."""
    print("="*80)
    print("🏠 АНАЛИЗ ЗОН FP2")
    print("="*80)
    print()
    
    data = get_fp2_data()
    if not data:
        print("❌ Backend недоступен")
        return
    
    ra = data['metadata']['raw_attributes']
    rv = ra.get('resource_values', {})
    
    # Поиск zone occupancy endpoints
    zone_occupancy = {}
    zone_count = {}
    
    for rid, value in rv.items():
        # Zone occupancy: 3.{N}.85
        if rid.startswith('3.') and rid.endswith('.85') and rid != '3.51.85':
            zone_num = rid.split('.')[1]
            zone_occupancy[zone_num] = (rid, value)
        
        # Zone target count: 13.12{N}.85
        elif rid.startswith('13.12') and rid.endswith('.85') and rid != '13.120.85':
            zone_num = rid.split('.')[1].replace('12', '')
            zone_count[zone_num] = (rid, value)
    
    print(f"📊 ОБНАРУЖЕНО ЗОН:")
    print(f"   Zone Occupancy: {len(zone_occupancy)}")
    print(f"   Zone Target Count: {len(zone_count)}")
    print()
    
    if not zone_occupancy and not zone_count:
        print("⚠️  ЗОНЫ НЕ НАСТРОЕНЫ!")
        print()
        print("Возможные причины:")
        print("  1. Зоны не настроены в Aqara Home app")
        print("  2. Устройство работает в режиме без зонирования")
        print("  3. Aqara Cloud API не отдаёт зонные данные (EU регион)")
        print()
        print("Рекомендации:")
        print("  1. Откройте Aqara Home app")
        print("  2. Найдите FP2 устройство")
        print("  3. Настройте зоны (Detection Areas)")
        print("  4. Сохраните конфигурацию")
        print()
    else:
        print("✅ ЗОНЫ НАСТРОЕНЫ!")
        print()
        
        # Показать все зоны
        all_zone_nums = set(zone_occupancy.keys()) | set(zone_count.keys())
        
        for zone_num in sorted(all_zone_nums):
            occ_rid, occ_val = zone_occupancy.get(zone_num, ('?', '?'))
            cnt_rid, cnt_val = zone_count.get(zone_num, ('?', '?'))
            
            occ_status = "ЗАНЯТА" if occ_val == "1" else "СВОБОДНА"
            occ_icon = "🟢" if occ_val == "1" else "⚪"
            
            print(f"  {occ_icon} Зона {zone_num}:")
            print(f"     Occupancy: {occ_rid} → {occ_status}")
            print(f"     Count: {cnt_rid} → {cnt_val} целей")
            print()
    
    # Показать общие statistics
    total_targets = rv.get('13.120.85', '0')
    presence = rv.get('3.51.85', '0')
    
    print("📈 ОБЩАЯ СТАТИСТИКА:")
    print(f"   Присутствие: {'✅ Есть' if presence == '1' else '⚪ Нет'}")
    print(f"   Всего целей: {total_targets}")
    print()
    
    print("="*80)

def monitor_zones(interval=1.5):
    """Непрерывный мониторинг зон."""
    print("\n🔍 МОНИТОРИНГ ЗОН В РЕАЛЬНОМ ВРЕМЕНИ...")
    print(f"Интервал опроса: {interval}s")
    print("Нажмите Ctrl+C для остановки")
    print()
    
    last_zone_state = {}
    
    try:
        while True:
            data = get_fp2_data()
            if not data:
                print(f"[{datetime.now().strftime('%H:%M:%S')}] ⚠️  Backend недоступен")
                time.sleep(interval)
                continue
            
            ra = data['metadata']['raw_attributes']
            rv = ra.get('resource_values', {})
            
            changes_detected = False
            
            # Проверка изменений зон
            for rid, value in rv.items():
                if rid.startswith('3.') and rid.endswith('.85') and rid != '3.51.85':
                    zone_num = rid.split('.')[1]
                    
                    if rid not in last_zone_state or last_zone_state[rid] != value:
                        timestamp = datetime.now().strftime("%H:%M:%S")
                        status = "ЗАНЯТА" if value == "1" else "СВОБОДНА"
                        icon = "🟢" if value == "1" else "⚪"
                        
                        print(f"[{timestamp}] {icon} Зона {zone_num}: {status}")
                        
                        # Логирование
                        with open("/tmp/zone_events.log", "a") as f:
                            f.write(f"[{timestamp}] Zone {zone_num}: {status}\n")
                        
                        last_zone_state[rid] = value
                        changes_detected = True
            
            if not changes_detected:
                # Показать статус раз в 10 секунд
                if int(datetime.now().timestamp()) % 10 < 2:
                    occupied_count = sum(1 for rid, val in rv.items() 
                                       if rid.startswith('3.') and rid.endswith('.85') 
                                       and rid != '3.51.85' and val == "1")
                    print(f"[{datetime.now().strftime('%H:%M:%S')}] 📊 Занято зон: {occupied_count}")
            
            time.sleep(interval)
    
    except KeyboardInterrupt:
        print(f"\n\n⏹️  Остановлено пользователем")
        print(f"Лог событий: /tmp/zone_events.log")

if __name__ == "__main__":
    import argparse
    import time
    
    parser = argparse.ArgumentParser(description="Настройка и мониторинг зон FP2")
    parser.add_argument("--monitor", action="store_true", help="Непрерывный мониторинг")
    parser.add_argument("--interval", type=float, default=1.5, help="Интервал опроса (сек)")
    args = parser.parse_args()
    
    if args.monitor:
        monitor_zones(args.interval)
    else:
        analyze_zones()
