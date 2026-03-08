#!/usr/bin/env python3
"""
Простой монитор всех endpoint'ов FP2 (упрощённая версия)

Использует уже настроенный fp2_aqara_cloud_monitor для получения данных.
"""

import json
import sys
import time
from datetime import datetime
from pathlib import Path

# Add project root to path
ROOT_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT_DIR))

try:
    import requests
except ImportError:
    print("❌ Установите requests: pip3 install requests")
    sys.exit(1)

BACKEND_URL = "http://127.0.0.1:8000"

# Известные ресурсы FP2
KNOWN_RESOURCES = {
    "3.51.85": "Присутствие (0/1)",
    "0.4.85": "Освещённость (люкс)",
    "8.0.2026": "RSSI (dBm)",
    "8.0.2045": "Online (0/1)",
    "13.27.85": "Движение (код)",
    "4.31.85": "Падение (код)",
    "8.0.2116": "Угол (градусы)",
    "13.120.85": "Всего целей",
    "4.22.700": "Координаты",
}


def fetch_fp2_data():
    """Получить данные от backend API."""
    try:
        response = requests.get(f"{BACKEND_URL}/api/v1/fp2/current", timeout=5)
        response.raise_for_status()
        return response.json()
    except Exception as e:
        return None


def format_resource_value(resource_id: str, value):
    """Форматировать значение ресурса."""
    if resource_id == "4.22.700":  # Координаты
        try:
            coords = json.loads(value) if isinstance(value, str) else value
            active = [c for c in coords if c.get("state") == "1" and (c.get("x", 0) != 0 or c.get("y", 0) != 0)]
            if active:
                return f"{len(active)} цель(ей): {[(t['x'], t['y']) for t in active]}"
            return "0 активных целей"
        except:
            return str(value)[:80]
    
    elif resource_id.startswith("3.") and resource_id.endswith(".85"):
        zone_num = resource_id.split(".")[1]
        status = "ЗАНЯТА" if value == "1" else "СВОБОДНА"
        return f"Зона {zone_num}: {status}"
    
    elif resource_id.startswith("13.12") and resource_id.endswith(".85"):
        zone_num = resource_id.split(".")[1].replace("12", "")
        return f"Зона {zone_num}: {value} цель(ей)"
    
    else:
        label = KNOWN_RESOURCES.get(resource_id, "")
        return f"{value} ({label})"


def monitor(interval: float = 1.5):
    """Мониторить изменения ресурсов."""
    print("\n" + "="*80)
    print("🔍 МОНИТОР ВСЕХ ENDPOINT'ОВ FP2 (через backend)")
    print("="*80)
    print(f"Backend: {BACKEND_URL}")
    print(f"Интервал: {interval}s")
    print("\n📋 ИНСТРУКЦИЯ:")
    print("  1. Пройдитесь перед датчиком FP2")
    print("  2. Помашите руками")
    print("  3. Наблюдайте какие endpoint'ы меняются!")
    print("\n⌨️  Ctrl+C для остановки")
    print("="*80 + "\n")
    
    previous_resources = {}
    sample_count = 0
    
    try:
        while True:
            sample_count += 1
            timestamp = datetime.now().strftime("%H:%M:%S.%f")[:-3]
            
            data = fetch_fp2_data()
            if not data:
                print(f"[{timestamp}] ⚠️  Backend недоступен")
                time.sleep(interval)
                continue
            
            # Extract resource values
            metadata = data.get('metadata', {})
            raw_attrs = metadata.get('raw_attributes', {})
            resource_values = raw_attrs.get('resource_values', {})
            
            changed_resources = []
            
            # Check for changes
            for rid, value in resource_values.items():
                if rid in previous_resources and previous_resources[rid] != value:
                    changed_resources.append((rid, value, previous_resources[rid]))
                previous_resources[rid] = value
            
            # Print status
            print(f"\n{'='*80}")
            print(f"📊 Замер #{sample_count} @ {timestamp}")
            print(f"{'='*80}")
            
            if changed_resources:
                print(f"\n⚡ ИЗМЕНИЛИСЬ РЕСУРСЫ ({len(changed_resources)}):")
                for rid, curr, prev in sorted(changed_resources, key=lambda x: x[0]):
                    formatted = format_resource_value(rid, curr)
                    
                    if rid in ["13.27.85", "3.51.85", "4.22.700"]:
                        marker = "🔴 ВАЖНО"
                    elif rid.startswith("3.") or rid.startswith("13.12"):
                        marker = "🟡 ЗОНА"
                    else:
                        marker = "⚪"
                    
                    print(f"  {marker} {rid}: {formatted}")
                    
                    if rid == "4.22.700":
                        try:
                            coords = json.loads(curr) if isinstance(curr, str) else curr
                            active = [c for c in coords if c.get("state") == "1"]
                            print(f"      Сырые: {json.dumps(active, indent=2)[:200]}")
                        except:
                            pass
            
            else:
                print(f"\n⏸️  Нет изменений")
            
            # Print all resources every 10 samples
            if sample_count % 10 == 0:
                print(f"\n📋 ВСЕ РЕСУРСЫ ({len(resource_values)}):")
                for rid in sorted(resource_values.keys()):
                    value = resource_values[rid]
                    formatted = format_resource_value(rid, value)
                    label = KNOWN_RESOURCES.get(rid, "")
                    print(f"  {rid:15} → {formatted:50} {label}")
            
            time.sleep(interval)
            
    except KeyboardInterrupt:
        print(f"\n\n⏹️  Остановлено после {sample_count} замеров")


if __name__ == "__main__":
    import argparse
    
    parser = argparse.ArgumentParser(description="Монитор всех endpoint'ов FP2")
    parser.add_argument("--interval", type=float, default=1.5, help="Интервал в секундах")
    args = parser.parse_args()
    
    # Check if backend is running
    print("🔍 Проверка backend...")
    test_data = fetch_fp2_data()
    if not test_data:
        print(f"❌ Backend {BACKEND_URL} недоступен!")
        print("\nЗапустите backend:")
        print("  cd /Users/arsen/Desktop/wifi-densepose")
        print("  python3 -m v1.src.app --reload")
        sys.exit(1)
    
    print("✅ Backend доступен")
    monitor(interval=args.interval)
