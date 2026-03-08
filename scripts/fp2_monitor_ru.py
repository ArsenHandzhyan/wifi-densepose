#!/usr/bin/env python3
"""
FP2 Все Endpoint'ы - Монитор в Реальном Времени

Этот скрипт показывает ВСЕ resource endpoint'ы устройства FP2
и подсвечивает какие обновляются когда вы двигаетесь.
"""

from __future__ import annotations

import argparse
from dataclasses import dataclass
import importlib.util
import json
from pathlib import Path
import sys
import time
from datetime import datetime

ROOT_DIR = Path(__file__).resolve().parents[1]
AQARA_PROBE_PATH = ROOT_DIR / "scripts" / "aqara_api_probe.py"


def load_probe_module():
    spec = importlib.util.spec_from_file_location("aqara_api_probe", AQARA_PROBE_PATH)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Не удалось загрузить {AQARA_PROBE_PATH}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


probe = load_probe_module()


# Известные ресурс ID FP2
KNOWN_RESOURCES = {
    "3.51.85": "Присутствие (0/1)",
    "0.4.85": "Освещённость (люкс)",
    "8.0.2026": "RSSI (dBm)",
    "8.0.2045": "Статус Online (0/1)",
    "13.27.85": "Код события движения",
    "4.31.85": "Код падения",
    "8.0.2116": "Угол сенсора (градусы)",
    "13.120.85": "Всего целей",
    "4.22.700": "Координаты (JSON)",
}


@dataclass
class Settings:
    env_path: Path
    access_token: str
    refresh_token: str
    open_id: str
    api_domain: str
    device_id: str
    app_id: str
    key_id: str
    app_key: str
    model: str = "lumi.motion.agl001"


def load_settings(env_path: Path) -> Settings:
    """Load settings from .env file."""
    import re
    
    env_vars = probe.load_dotenv(env_path)
    
    return Settings(
        env_path=env_path,
        access_token=env_vars.get("AQARA_ACCESS_TOKEN", ""),
        refresh_token=env_vars.get("AQARA_REFRESH_TOKEN", ""),
        open_id=env_vars.get("AQARA_OPEN_ID", ""),
        api_domain=env_vars.get("AQARA_API_DOMAIN", "open-ger.aqara.com"),
        device_id=env_vars.get("AQARA_DEVICE_ID", ""),
        app_id=env_vars.get("AQARA_APP_ID", "1328946657"),
        key_id=env_vars.get("AQARA_KEY_ID", "aqara-api-key-1"),
        app_key=env_vars.get("AQARA_APP_KEY", "bZyEzwnhLkMQWLFBfNqbZDfRwqnGQcXu"),
        model=env_vars.get("AQARA_DEVICE_MODEL", "lumi.motion.agl001"),
    )


def resolve_fp2_device(settings: Settings) -> tuple[str, str]:
    """
    Resolve FP2 device DID and model.
    Returns (did, model) tuple.
    """
    # If device_id is provided in env, use it directly
    if settings.device_id:
        print(f"✅ Используем устройство из .env: {settings.device_id}")
        return settings.device_id, settings.model
    
    # Otherwise, query the API to find devices
    print("🔍 Поиск устройств в аккаунте Aqara...")
    
    body = api_query(
        settings,
        "query.device.list",
        {"limit": 50, "homeIds": []},
    )
    
    result = body.get("result") or {}
    devices = result.get("devices", [])
    
    if not devices:
        raise RuntimeError("Устройства не найдены в аккаунте Aqara")
    
    # Look for FP2 device (model contains 'agl001' or name contains 'FP2')
    fp2_devices = []
    for dev in devices:
        model = dev.get("model", "")
        name = dev.get("name", "")
        did = dev.get("did", "")
        
        if "agl001" in model.lower() or "fp2" in name.lower():
            fp2_devices.append((did, model, name))
    
    if not fp2_devices:
        # If no FP2 found, list all devices
        print("\n⚠️  FP2 не найден. Доступные устройства:")
        for dev in devices[:10]:
            print(f"  - {dev.get('name')} ({dev.get('model')}) DID: {dev.get('did')}")
        raise RuntimeError("Aqara FP2 не найден в списке устройств")
    
    # Use first FP2 device
    did, model, name = fp2_devices[0]
    print(f"✅ Найдено: {name} ({model}) DID: {did}")
    
    return did, model


def refresh_access_token(settings: Settings) -> None:
    http_status, body = probe.api_call(
        settings,
        "config.auth.refreshToken",
        {"refreshToken": settings.refresh_token},
    )
    if http_status != 200 or body.get("code") != 0:
        raise RuntimeError(f"refreshToken failed: {http_status} {body}")

    result = body.get("result") or {}
    settings.access_token = result.get("accessToken", settings.access_token)
    settings.refresh_token = result.get("refreshToken", settings.refresh_token)
    settings.open_id = result.get("openId", settings.open_id)

    probe.write_env_updates(
        settings.env_path,
        {
            "AQARA_ACCESS_TOKEN": settings.access_token,
            "AQARA_REFRESH_TOKEN": settings.refresh_token,
            "AQARA_OPEN_ID": settings.open_id,
        },
    )
    print("✅ Токен доступа обновлён")


def api_query(settings: Settings, intent: str, data: dict[str, Any]) -> dict[str, Any]:
    http_status, body = probe.api_call(
        settings,
        intent,
        data,
        access_token=settings.access_token,
    )
    
    if http_status == 200 and body.get("code") == 0:
        return body
    
    if http_status == 200 and body.get("code") == 108:
        refresh_access_token(settings)
        return api_query(settings, intent, data)
    
    raise RuntimeError(f"{intent} failed: {http_status} {body}")


def fetch_all_resources(settings: Settings, did: str) -> dict[str, Any]:
    """Получить все значения ресурсов устройства."""
    body = api_query(
        settings,
        "query.resource.value",
        {"resources": [{"subjectId": did}]},
    )
    
    result = body.get("result") or []
    if not isinstance(result, list):
        raise RuntimeError("query.resource.value вернул неожиданные данные")
    
    resources_dict = {}
    for item in result:
        resource_id = str(item.get("resourceId"))
        if resource_id:
            resources_dict[resource_id] = item
    
    return resources_dict


def format_resource_value(resource_id: str, item: dict[str, Any]) -> str:
    """Форматировать значение ресурса для отображения."""
    value = item.get("value")
    
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


def monitor_resources(settings: Settings, did: str, interval: float = 1.0):
    """Мониторить все ресурсы в реальном времени."""
    print("\n" + "="*80)
    print("🔍 МОНИТОР ВСЕХ ENDPOINT'ОВ FP2")
    print("="*80)
    print(f"Устройство: {did}")
    print(f"Модель: {settings.model}")
    print(f"Интервал обновления: {interval}s")
    print("\n📋 ИНСТРУКЦИЯ:")
    print("  1. Пройдитесь перед датчиком FP2")
    print("  2. Помашите руками")
    print("  3. Подышите глубоко")
    print("  4. Наблюдайте какие endpoint'ы меняются!")
    print("\n⌨️  УПРАВЛЕНИЕ:")
    print("  - Ctrl+C для остановки")
    print("="*80)
    print()
    
    previous_resources = None
    sample_count = 0
    
    try:
        while True:
            sample_count += 1
            timestamp = datetime.now().strftime("%H:%M:%S.%f")[:-3]
            
            current_resources = fetch_all_resources(settings, did)
            
            changed_resources = []
            new_resources = []
            
            if previous_resources:
                for rid, curr_item in current_resources.items():
                    curr_value = curr_item.get("value")
                    curr_time = curr_item.get("timeStamp")
                    
                    if rid not in previous_resources:
                        new_resources.append((rid, curr_item))
                    else:
                        prev_item = previous_resources[rid]
                        prev_value = prev_item.get("value")
                        prev_time = prev_item.get("timeStamp")
                        
                        if curr_value != prev_value or curr_time != prev_time:
                            changed_resources.append((rid, curr_item, prev_item))
            
            print(f"\n{'='*80}")
            print(f"📊 Замер #{sample_count} @ {timestamp}")
            print(f"{'='*80}")
            
            if changed_resources:
                print(f"\n⚡ ИЗМЕНИЛИСЬ РЕСУРСЫ ({len(changed_resources)}):")
                for rid, curr_item, prev_item in sorted(changed_resources, key=lambda x: x[0]):
                    curr_value = curr_item.get("value")
                    formatted = format_resource_value(rid, curr_item)
                    
                    if rid in ["13.27.85", "3.51.85", "4.22.700"]:
                        marker = "🔴 ВАЖНО"
                    elif rid.startswith("3.") or rid.startswith("13.12"):
                        marker = "🟡 ЗОНА"
                    else:
                        marker = "⚪"
                    
                    print(f"  {marker} {rid}: {formatted}")
                    
                    if rid == "4.22.700":
                        try:
                            coords = json.loads(curr_value) if isinstance(curr_value, str) else curr_value
                            active = [c for c in coords if c.get("state") == "1"]
                            print(f"      Сырые: {json.dumps(active, indent=2)[:200]}")
                        except:
                            pass
            
            elif new_resources:
                print(f"\n➕ НОВЫЕ РЕСУРСЫ ({len(new_resources)}):")
                for rid, item in sorted(new_resources, key=lambda x: x[0]):
                    formatted = format_resource_value(rid, item)
                    print(f"  {rid}: {formatted}")
            
            else:
                print(f"\n⏸️  Нет изменений")
            
            if sample_count % 10 == 0:
                print(f"\n📋 ВСЕ РЕСУРСЫ ({len(current_resources)}):")
                for rid in sorted(current_resources.keys()):
                    item = current_resources[rid]
                    formatted = format_resource_value(rid, item)
                    label = KNOWN_RESOURCES.get(rid, "")
                    print(f"  {rid:15} → {formatted:50} {label}")
            
            previous_resources = current_resources
            time.sleep(interval)
            
    except KeyboardInterrupt:
        print(f"\n\n⏹️  Остановлено пользователем после {sample_count} замеров")


def main():
    parser = argparse.ArgumentParser(description="Монитор всех endpoint'ов FP2")
    parser.add_argument(
        "--env-file",
        type=Path,
        default=ROOT_DIR / ".env",
        help="Путь к .env файлу",
    )
    parser.add_argument(
        "--interval",
        type=float,
        default=1.5,
        help="Интервал в секундах (по умолчанию: 1.5)",
    )
    args = parser.parse_args()
    
    settings = load_settings(args.env_file)
    
    # Resolve device DID and model
    did, model = resolve_fp2_device(settings)
    
    # Update settings with resolved values
    settings.device_id = did
    settings.model = model
    
    monitor_resources(settings, did, interval=args.interval)


if __name__ == "__main__":
    main()
