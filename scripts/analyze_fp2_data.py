#!/usr/bin/env python3
"""
Анализ текущих данных FP2
"""

import requests
import json

try:
    response = requests.get("http://127.0.0.1:8000/api/v1/fp2/current", timeout=5)
    data = response.json()
except Exception as e:
    print(f"❌ Ошибка: {e}")
    exit(1)

ra = data['metadata']['raw_attributes']
rv = ra.get('resource_values', {})

print("="*80)
print("📊 ПОЛНЫЙ АНАЛИЗ ДАННЫХ FP2")
print("="*80)
print()

# Основные метрики
print("🎯 ОСНОВНЫЕ МЕТРИКИ:")
print(f"  Присутствие: {ra.get('presence')}")
print(f"  Движение: Code {ra.get('movement_event')}")
print(f"  Падение: Code {ra.get('fall_state')}")
print(f"  Освещённость: {ra.get('light_level')} lux")
print(f"  RSSI: {ra.get('rssi')} dBm")
print(f"  Угол сенсора: {ra.get('sensor_angle')}°")
print(f"  Целей всего: {len(data.get('persons', []))}")
print()

# Координаты
coords = ra.get('coordinates', [])
if coords:
    active = [c for c in coords if c.get('state') == '1' and (c.get('x', 0) != 0 or c.get('y', 0) != 0)]
    if active:
        print("📍 АКТИВНЫЕ ЦЕЛИ:")
        for c in active:
            print(f"  Target {c.get('id')}: ({c.get('x')}, {c.get('y')}) - Dist: {c.get('distance', '?')} cm, Angle: {c.get('angle', '?')}°")
        print()

# Ресурсы
print("📋 ВСЕ RESOURCE ENDPOINTS:")
for rid in sorted(rv.keys()):
    value = rv[rid]
    
    # Определяем тип
    label = ''
    category = '⚪'
    if rid == '3.51.85': 
        label = 'Presence'
        category = '🔴 ВАЖНО'
    elif rid == '13.27.85': 
        label = 'Movement Event'
        category = '🔴 ВАЖНО'
    elif rid == '4.22.700': 
        label = 'Coordinates'
        category = '🔴 ВАЖНО'
    elif rid == '0.4.85': 
        label = 'Light Level'
        category = '⚪'
    elif rid == '8.0.2026': 
        label = 'RSSI'
        category = '⚪'
    elif rid == '8.0.2045': 
        label = 'Online State'
        category = '⚪'
    elif rid == '8.0.2116': 
        label = 'Sensor Angle'
        category = '⚪'
    elif rid == '4.31.85': 
        label = 'Fall State'
        category = '🔴 ВАЖНО'
    elif rid == '13.120.85': 
        label = 'Total Targets'
        category = '⚪'
    elif rid.startswith('3.') and rid.endswith('.85'): 
        zone_num = rid.split('.')[1]
        label = f'Zone {zone_num} Occupancy'
        category = '🟡 ЗОНА'
    elif rid.startswith('13.12') and rid.endswith('.85'): 
        zone_num = rid.split('.')[1].replace('12', '')
        label = f'Zone {zone_num} Count'
        category = '🟡 ЗОНА'
    else:
        label = 'Unknown'
        category = '⚪'
    
    display_value = str(value)[:50] + '...' if len(str(value)) > 50 else str(value)
    print(f"  {category} {rid:15} → {display_value:52} [{label}]")

print()
print("="*80)
print("📈 СТАТИСТИКА:")
print(f"  Всего endpoint'ов: {len(rv)}")
print(f"  Из них важных: {sum(1 for rid in rv if rid in ['3.51.85', '13.27.85', '4.22.700', '4.31.85'])}")
print(f"  Из них зон: {sum(1 for rid in rv if rid.startswith('3.') or rid.startswith('13.12'))}")
print("="*80)
