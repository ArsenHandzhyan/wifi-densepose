#!/usr/bin/env python3
"""
Сбор статистики и логирование событий FP2

Что делает:
1. Логирует все изменения endpoint'ов
2. Считает статистику (среднее, мин, макс)
3. Экспортирует в CSV/JSON
4. Анализирует паттерны движения
"""

import requests
import json
import time
import csv
from datetime import datetime
from pathlib import Path

BACKEND_URL = "http://127.0.0.1:8000"
LOG_DIR = Path("/tmp/fp2_stats")
LOG_DIR.mkdir(exist_ok=True)

class FP2StatisticsCollector:
    def __init__(self):
        self.events = []
        self.stats = {
            'movement_events': {},
            'light_levels': [],
            'rssi_values': [],
            'target_counts': [],
            'zone_changes': []
        }
        
    def get_fp2_data(self):
        """Получить текущие данные FP2."""
        try:
            response = requests.get(f"{BACKEND_URL}/api/v1/fp2/current", timeout=5)
            response.raise_for_status()
            return response.json()
        except Exception as e:
            return None
    
    def log_event(self, event_type: str, data: dict):
        """Логировать событие."""
        timestamp = datetime.now().isoformat()
        event = {
            'timestamp': timestamp,
            'type': event_type,
            'data': data
        }
        self.events.append(event)
        
        # Сохранить в файл
        with open(LOG_DIR / "events.log", "a") as f:
            f.write(json.dumps(event) + "\n")
    
    def update_stats(self, data: dict):
        """Обновить статистику."""
        if not data:
            return
        
        ra = data['metadata']['raw_attributes']
        
        # Movement events
        movement = ra.get('movement_event')
        if movement is not None:
            self.stats['movement_events'][str(movement)] = \
                self.stats['movement_events'].get(str(movement), 0) + 1
        
        # Light levels
        light = ra.get('light_level')
        if light is not None:
            self.stats['light_levels'].append(light)
        
        # RSSI
        rssi = ra.get('rssi')
        if rssi is not None:
            self.stats['rssi_values'].append(rssi)
        
        # Target count
        persons = len(data.get('persons', []))
        self.stats['target_counts'].append(persons)
    
    def export_csv(self, filename: str):
        """Экспорт статистики в CSV."""
        filepath = LOG_DIR / filename
        
        with open(filepath, 'w', newline='') as f:
            writer = csv.writer(f)
            
            # Заголовок
            writer.writerow(['Metric', 'Value', 'Min', 'Max', 'Avg'])
            
            # Movement events distribution
            for code, count in sorted(self.stats['movement_events'].items()):
                writer.writerow(['Movement Event', code, '-', '-', count])
            
            # Light statistics
            if self.stats['light_levels']:
                lights = self.stats['light_levels']
                writer.writerow(['Light Level', 'current', min(lights), max(lights), 
                               round(sum(lights)/len(lights), 1)])
            
            # RSSI statistics
            if self.stats['rssi_values']:
                rssi = self.stats['rssi_values']
                writer.writerow(['RSSI', 'current', min(rssi), max(rssi),
                               round(sum(rssi)/len(rssi), 1)])
            
            # Target count statistics
            if self.stats['target_counts']:
                counts = self.stats['target_counts']
                writer.writerow(['Target Count', 'current', min(counts), max(counts),
                               round(sum(counts)/len(counts), 1)])
        
        print(f"✅ Статистика экспортирована: {filepath}")
    
    def export_json(self, filename: str):
        """Экспорт полной статистики в JSON."""
        filepath = LOG_DIR / filename
        
        report = {
            'generated_at': datetime.now().isoformat(),
            'total_events': len(self.events),
            'statistics': {
                'movement_events': self.stats['movement_events'],
                'light_level': {
                    'min': min(self.stats['light_levels']) if self.stats['light_levels'] else None,
                    'max': max(self.stats['light_levels']) if self.stats['light_levels'] else None,
                    'avg': round(sum(self.stats['light_levels'])/len(self.stats['light_levels']), 1) if self.stats['light_levels'] else None
                },
                'rssi': {
                    'min': min(self.stats['rssi_values']) if self.stats['rssi_values'] else None,
                    'max': max(self.stats['rssi_values']) if self.stats['rssi_values'] else None,
                    'avg': round(sum(self.stats['rssi_values'])/len(self.stats['rssi_values']), 1) if self.stats['rssi_values'] else None
                },
                'target_count': {
                    'min': min(self.stats['target_counts']) if self.stats['target_counts'] else None,
                    'max': max(self.stats['target_counts']) if self.stats['target_counts'] else None,
                    'avg': round(sum(self.stats['target_counts'])/len(self.stats['target_counts']), 1) if self.stats['target_counts'] else None
                }
            },
            'recent_events': self.events[-50:]  # Последние 50 событий
        }
        
        with open(filepath, 'w') as f:
            json.dump(report, f, indent=2)
        
        print(f"✅ Статистика экспортирована: {filepath}")
    
    def print_summary(self):
        """Вывести сводку статистики."""
        print("="*80)
        print("📊 СТАТИСТИКА FP2")
        print("="*80)
        print()
        
        print(f"📈 Событий записано: {len(self.events)}")
        print()
        
        # Movement events distribution
        if self.stats['movement_events']:
            print("🎯 Распределение Movement Events:")
            total = sum(self.stats['movement_events'].values())
            for code in sorted(self.stats['movement_events'].keys()):
                count = self.stats['movement_events'][code]
                pct = round(count / total * 100, 1)
                print(f"   Code {code}: {count} ({pct}%)")
            print()
        
        # Light statistics
        if self.stats['light_levels']:
            lights = self.stats['light_levels']
            print("💡 Освещённость (lux):")
            print(f"   Min: {min(lights)}")
            print(f"   Max: {max(lights)}")
            print(f"   Avg: {round(sum(lights)/len(lights), 1)}")
            print()
        
        # RSSI statistics
        if self.stats['rssi_values']:
            rssi = self.stats['rssi_values']
            print("📶 RSSI (dBm):")
            print(f"   Min: {min(rssi)}")
            print(f"   Max: {max(rssi)}")
            print(f"   Avg: {round(sum(rssi)/len(rssi), 1)}")
            print()
        
        # Target count
        if self.stats['target_counts']:
            counts = self.stats['target_counts']
            print("👥 Количество целей:")
            print(f"   Min: {min(counts)}")
            print(f"   Max: {max(counts)}")
            print(f"   Avg: {round(sum(counts)/len(counts), 1)}")
            print()
        
        print("="*80)

def main():
    import argparse
    
    parser = argparse.ArgumentParser(description="Сбор статистики FP2")
    parser.add_argument("--duration", type=int, default=60, help="Длительность сбора (сек)")
    parser.add_argument("--interval", type=float, default=1.0, help="Интервал опроса (сек)")
    parser.add_argument("--export", action="store_true", help="Экспортировать статистику")
    args = parser.parse_args()
    
    collector = FP2StatisticsCollector()
    
    print("="*80)
    print("📊 СБОР СТАТИСТИКИ FP2")
    print("="*80)
    print(f"Длительность: {args.duration}s")
    print(f"Интервал: {args.interval}s")
    print("Нажмите Ctrl+C для досрочной остановки")
    print()
    
    start_time = time.time()
    
    try:
        while time.time() - start_time < args.duration:
            elapsed = int(time.time() - start_time)
            
            # Получить данные
            data = collector.get_fp2_data()
            if data:
                collector.update_stats(data)
                
                # Логировать изменения
                ra = data['metadata']['raw_attributes']
                
                # Проверка presence change
                presence = ra.get('presence')
                if presence:
                    last_presence = collector.events[-1]['data'].get('presence') if collector.events else None
                    if presence != last_presence:
                        collector.log_event('presence_change', {'presence': presence})
                
                # Проверка movement event change
                movement = ra.get('movement_event')
                if movement is not None:
                    last_movement = collector.events[-1]['data'].get('movement_event') if collector.events else None
                    if movement != last_movement:
                        collector.log_event('movement_event', {'code': movement})
            
            # Обновлять каждые N секунд
            time.sleep(args.interval)
    
    except KeyboardInterrupt:
        print("\n\n⏹️  Остановлено пользователем")
    
    # Вывод сводки
    collector.print_summary()
    
    # Экспорт
    if args.export:
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        collector.export_csv(f"fp2_stats_{timestamp}.csv")
        collector.export_json(f"fp2_full_{timestamp}.json")
    
    print()
    print(f"📁 Папка с данными: {LOG_DIR}")

if __name__ == "__main__":
    main()
