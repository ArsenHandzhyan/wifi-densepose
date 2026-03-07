#!/usr/bin/env python3
"""
Прямой HAP-клиент для Aqara FP2 Presence Sensor.

Подключается к FP2 через HomeKit Accessory Protocol (HAP),
читает данные о присутствии и зонах, передаёт их в бэкенд.

Требования:
  pip install aiohomekit zeroconf aiohttp

Использование:
  # Шаг 1: Удалить FP2 из Aqara Home
  # Шаг 2: Запарить с этим клиентом
  python3 scripts/fp2_hap_client.py pair

  # Шаг 3: Мониторинг в реальном времени
  python3 scripts/fp2_hap_client.py monitor

  # Шаг 4: Мониторинг + отправка в бэкенд
  python3 scripts/fp2_hap_client.py monitor --backend http://localhost:8000
"""

import argparse
import asyncio
import inspect
import json
import logging
import os
import socket
import sys
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

# ── Paths ────────────────────────────────────────────────────
PROJECT_ROOT = Path(__file__).resolve().parent.parent
PAIRING_DATA_FILE = PROJECT_ROOT / ".fp2_pairing.json"

# ── Known FP2 config ────────────────────────────────────────
FP2_IP = os.environ.get("FP2_IP", "192.168.1.52")
FP2_PORT = int(os.environ.get("FP2_PORT", "443"))
FP2_PAIRING_CODE = os.environ.get("FP2_HOMEKIT_CODE", "")
FP2_MAC = os.environ.get("FP2_MAC", "54:EF:44:79:E0:03")
LOCAL_IFACE = os.environ.get("LOCAL_IFACE")
BACKEND_URL = os.environ.get("BACKEND_URL", "http://localhost:8000")

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger("fp2_hap")


# ── HAP Discovery helpers ───────────────────────────────────

def create_characteristic_cache():
    """Create a characteristic cache compatible with old and new aiohomekit layouts."""
    try:
        from aiohomekit.characteristic_cache import CharacteristicCacheMemory
    except ImportError:
        from aiohomekit.model.characteristics import CharacteristicCacheMemory
    return CharacteristicCacheMemory()


async def await_maybe(value):
    """Await coroutine results when needed, otherwise return the value as-is."""
    if inspect.isawaitable(value):
        return await value
    return value


def is_standard_homekit_char(char_type: str, short_code: str) -> bool:
    """Match standard HomeKit characteristic UUIDs by their short code."""
    norm = (char_type or "").upper()
    code = short_code.upper()
    return norm == code or norm.startswith(f"000000{code}-")

def get_local_iface() -> str:
    """Best-effort local interface IP used to reach FP2."""
    if LOCAL_IFACE:
        return LOCAL_IFACE

    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        sock.connect((FP2_IP, FP2_PORT))
        return sock.getsockname()[0]
    finally:
        sock.close()

def build_fp2_service():
    """Build a HomeKitService manually for FP2 (bypasses mDNS)."""
    from aiohomekit.model import Categories
    from aiohomekit.model.feature_flags import FeatureFlags
    from aiohomekit.model.status_flags import StatusFlags
    from aiohomekit.zeroconf import HomeKitService

    return HomeKitService(
        name="Presence-Sensor-FP2-E003",
        id=FP2_MAC,
        model="PS-S02D",
        feature_flags=FeatureFlags(0),
        status_flags=StatusFlags.UNPAIRED,
        config_num=1,
        state_num=1,
        category=Categories.SENSOR,
        protocol_version="1.1",
        type="_hap._tcp.local.",
        address=FP2_IP,
        addresses=[FP2_IP],
        port=FP2_PORT,
    )


async def discover_fp2_service(timeout: float = 5.0):
    """Discover and return the real FP2 HomeKit service from mDNS."""
    from aiohomekit.zeroconf import HomeKitService
    from zeroconf.asyncio import AsyncZeroconf, AsyncServiceBrowser, AsyncServiceInfo

    found = []

    class Listener:
        def add_service(self, zc, stype, name):
            log.info("  Найден: %s", name)
            found.append(name)
        def remove_service(self, zc, stype, name):
            pass
        def update_service(self, zc, stype, name):
            pass

    azc = AsyncZeroconf(interfaces=[get_local_iface()])
    browser = AsyncServiceBrowser(azc.zeroconf, "_hap._tcp.local.", Listener())
    try:
        await asyncio.sleep(timeout)

        for name in found:
            info = AsyncServiceInfo("_hap._tcp.local.", name)
            ok = await info.async_request(azc.zeroconf, int(timeout * 1000))
            if not ok:
                continue

            props = {str(k).lower(): str(v) for k, v in info.decoded_properties.items() if v is not None}
            model = props.get("md", "")
            if "FP2" not in name and "Presence" not in name and model != "PS-S02D":
                continue

            service = HomeKitService.from_service_info(info)
            log.info(
                "FP2 service: name=%s id=%s address=%s port=%s model=%s",
                service.name,
                service.id,
                service.address,
                service.port,
                service.model,
            )
            return service
    finally:
        await browser.async_cancel()
        await azc.async_close()

    return None


async def discover_fp2(timeout: float = 10.0) -> bool:
    """Try to discover FP2 via mDNS (works when FP2 is in pairing mode)."""
    log.info("Поиск FP2 через mDNS (%s сек)...", timeout)
    service = await discover_fp2_service(timeout=timeout)
    fp2_found = service is not None
    if fp2_found:
        log.info("FP2 найден через mDNS!")
    else:
        log.warning("FP2 не найден через mDNS.")
    return fp2_found


async def check_fp2_reachable() -> bool:
    """Check if FP2 is reachable on the network."""
    try:
        reader, writer = await asyncio.wait_for(
            asyncio.open_connection(FP2_IP, FP2_PORT), timeout=3.0
        )
        writer.close()
        await writer.wait_closed()
        log.info("FP2 доступен: %s:%d", FP2_IP, FP2_PORT)
        return True
    except Exception as e:
        log.error("FP2 недоступен (%s:%d): %s", FP2_IP, FP2_PORT, e)
        return False


# ── Pairing ──────────────────────────────────────────────────

async def pair_fp2():
    """Pair with FP2 using HomeKit protocol."""
    from aiohomekit.controller.ip import IpController
    from aiohomekit.controller.ip.discovery import IpDiscovery
    from zeroconf.asyncio import AsyncZeroconf

    if PAIRING_DATA_FILE.exists():
        log.warning("Файл пейринга уже существует: %s", PAIRING_DATA_FILE)
        log.warning("Удалите его для повторного пейринга: rm %s", PAIRING_DATA_FILE)
        return False

    if not FP2_PAIRING_CODE:
        log.error("Не задан FP2_HOMEKIT_CODE. Укажите HomeKit код через переменную окружения.")
        return False

    service = await discover_fp2_service(timeout=5.0)
    if service is None:
        log.warning("Не удалось получить реальный HAP service через mDNS, пробую fallback.")
        if not await check_fp2_reachable():
            log.error("FP2 недоступен. Убедитесь что датчик включен и в сети.")
            return False
        service = build_fp2_service()

    log.info("Начинаю пейринг с FP2...")
    log.info("  HAP service: %s", service.name)
    log.info("  HAP id: %s", service.id)
    log.info("  IP: %s:%d", service.address, service.port)
    log.info("  Код: %s", FP2_PAIRING_CODE)

    azc = AsyncZeroconf(interfaces=[get_local_iface()])
    controller = None

    try:
        char_cache = create_characteristic_cache()
        controller = IpController(char_cache=char_cache, zeroconf_instance=azc)

        discovery = IpDiscovery(controller, service)

        log.info("Отправляю запрос на пейринг...")
        finish_pairing = await discovery.async_start_pairing("fp2_sensor")

        log.info("Ввожу код пейринга: %s", FP2_PAIRING_CODE)
        pairing = await finish_pairing(FP2_PAIRING_CODE)

        pairing_data = pairing.pairing_data
        PAIRING_DATA_FILE.write_text(json.dumps(pairing_data, indent=2))
        log.info("Пейринг УСПЕШЕН! Данные сохранены: %s", PAIRING_DATA_FILE)

        accessories = await await_maybe(pairing.list_accessories_and_characteristics())
        log.info("Аксессуары FP2:")
        for acc in accessories:
            for svc in acc.get("services", []):
                stype = svc.get("type", "")
                log.info("  Сервис: %s (iid=%d)", stype, svc.get("iid", 0))
                for char in svc.get("characteristics", []):
                    ctype = char.get("type", "")
                    value = char.get("value")
                    log.info("    %s = %s", ctype, value)

        await await_maybe(pairing.close())
        return True

    except Exception as e:
        log.error("Ошибка пейринга: %s", e)
        log.error("Убедитесь что FP2 доступен для HomeKit-пейринга и код указан верно.")
        return False
    finally:
        await azc.async_close()


# ── Monitoring ───────────────────────────────────────────────

async def monitor_fp2(backend_url: Optional[str] = None, interval: float = 1.0):
    """Connect to paired FP2 and monitor presence data in real-time."""
    from aiohomekit.controller.ip import IpController
    from zeroconf.asyncio import AsyncZeroconf

    if not PAIRING_DATA_FILE.exists():
        log.error("Файл пейринга не найден: %s", PAIRING_DATA_FILE)
        log.error("Сначала выполните: python3 %s pair", __file__)
        return

    pairing_data = json.loads(PAIRING_DATA_FILE.read_text())
    log.info("Загружены данные пейринга")

    # Setup
    azc = AsyncZeroconf(interfaces=[get_local_iface()])

    http_session = None
    if backend_url:
        import aiohttp
        http_session = aiohttp.ClientSession()

    controller = None
    try:
        char_cache = create_characteristic_cache()
        controller = IpController(char_cache=char_cache, zeroconf_instance=azc)

        pairing = await await_maybe(controller.load_pairing("fp2_sensor", pairing_data))
        if pairing is None:
            log.error("Не удалось восстановить pairing из файла.")
            return
        log.info("Подключение к FP2 восстановлено")

        accessories = await await_maybe(pairing.list_accessories_and_characteristics())

        # Parse services to find occupancy sensors
        occupancy_chars = []
        light_chars = []

        for acc in accessories:
            for svc in acc.get("services", []):
                stype = svc.get("type", "").upper()
                for char in svc.get("characteristics", []):
                    ctype = char.get("type", "").upper()
                    aid = acc.get("aid", 1)
                    iid = char.get("iid", 0)

                    # Occupancy Detected (0x71 = 113)
                    if is_standard_homekit_char(ctype, "71"):
                        occupancy_chars.append({
                            "aid": aid, "iid": iid,
                            "name": f"occupancy_{svc.get('iid',0)}",
                            "service_iid": svc.get("iid", 0),
                        })
                    # Current Ambient Light Level (0x6B = 107)
                    elif is_standard_homekit_char(ctype, "6B"):
                        light_chars.append({
                            "aid": aid, "iid": iid,
                            "name": f"light_{svc.get('iid',0)}",
                        })

        log.info("Найдено %d датчиков присутствия, %d датчиков освещения",
                 len(occupancy_chars), len(light_chars))

        if not occupancy_chars:
            log.warning("Датчики присутствия не найдены! Показываю все характеристики:")
            for acc in accessories:
                for svc in acc.get("services", []):
                    log.info("  Service type=%s iid=%d", svc.get("type",""), svc.get("iid",0))
                    for char in svc.get("characteristics", []):
                        log.info("    Char type=%s iid=%d value=%s",
                                char.get("type",""), char.get("iid",0), char.get("value"))

        # Subscribe to changes via polling
        log.info("")
        log.info("=" * 60)
        log.info("  МОНИТОРИНГ FP2 В РЕАЛЬНОМ ВРЕМЕНИ")
        log.info("  Нажмите Ctrl+C для остановки")
        log.info("=" * 60)
        log.info("")

        # Build list of characteristics to read
        chars_to_read = [(c["aid"], c["iid"]) for c in occupancy_chars + light_chars]

        poll_count = 0
        while True:
            try:
                # Read all relevant characteristics
                if chars_to_read:
                    values = await await_maybe(pairing.get_characteristics(chars_to_read))
                else:
                    values = {}

                # Build snapshot
                timestamp = time.time()
                zones = []
                light_level = None

                for oc in occupancy_chars:
                    key = (oc["aid"], oc["iid"])
                    val = values.get(key, {}).get("value", 0)
                    occupied = bool(val)
                    zones.append({
                        "zone_id": oc["name"],
                        "service_iid": oc["service_iid"],
                        "occupied": occupied,
                    })

                for lc in light_chars:
                    key = (lc["aid"], lc["iid"])
                    val = values.get(key, {}).get("value")
                    if val is not None:
                        try:
                            light_level = float(val)
                        except (TypeError, ValueError):
                            continue

                presence = any(z["occupied"] for z in zones)

                # Display
                status = "ПРИСУТСТВИЕ" if presence else "Пусто"
                zone_str = ", ".join(
                    f"{z['zone_id']}={'ДА' if z['occupied'] else 'нет'}" for z in zones
                )
                light_str = f" | Свет: {light_level:.0f} lux" if light_level is not None else ""

                poll_count += 1
                log.info("[%d] %s | Зоны: %s%s", poll_count, status, zone_str, light_str)

                # Send to backend
                if backend_url and http_session:
                    payload = {
                        "timestamp": timestamp,
                        "presence": presence,
                        "zones": zones,
                        "light_level": light_level,
                        "source": "hap_direct",
                    }
                    try:
                        async with http_session.post(
                            f"{backend_url}/api/v1/fp2/push",
                            json=payload,
                            timeout=aiohttp.ClientTimeout(total=3),
                        ) as resp:
                            if resp.status != 200:
                                log.warning("Backend ответил: %d", resp.status)
                    except Exception as e:
                        log.debug("Backend недоступен: %s", e)

            except Exception as e:
                log.error("Ошибка чтения: %s", e)

            await asyncio.sleep(interval)

    except KeyboardInterrupt:
        log.info("Мониторинг остановлен")
    except Exception as e:
        log.error("Ошибка: %s", e)
    finally:
        if http_session and not http_session.closed:
            await http_session.close()
        await azc.async_close()


# ── Info ─────────────────────────────────────────────────────

async def info_fp2():
    """Show info about paired FP2."""
    from aiohomekit.controller.ip import IpController
    from zeroconf.asyncio import AsyncZeroconf

    if not PAIRING_DATA_FILE.exists():
        log.error("FP2 не спарен. Сначала: python3 %s pair", __file__)
        return

    pairing_data = json.loads(PAIRING_DATA_FILE.read_text())

    azc = AsyncZeroconf(interfaces=[get_local_iface()])

    controller = None
    try:
        char_cache = create_characteristic_cache()
        controller = IpController(char_cache=char_cache, zeroconf_instance=azc)
        pairing = await await_maybe(controller.load_pairing("fp2_sensor", pairing_data))
        if pairing is None:
            log.error("Не удалось восстановить pairing из файла.")
            return

        accessories = await await_maybe(pairing.list_accessories_and_characteristics())

        print("\n" + "=" * 60)
        print("  AQARA FP2 — ИНФОРМАЦИЯ ОБ УСТРОЙСТВЕ")
        print("=" * 60)

        for acc in accessories:
            print(f"\nАксессуар (aid={acc.get('aid', 1)}):")
            for svc in acc.get("services", []):
                stype = svc.get("type", "unknown")
                print(f"\n  Сервис: {stype} (iid={svc.get('iid', 0)})")
                for char in svc.get("characteristics", []):
                    ctype = char.get("type", "unknown")
                    value = char.get("value", "N/A")
                    perms = char.get("perms", [])
                    fmt = char.get("format", "")
                    print(f"    {ctype:40s} = {str(value):20s} [{fmt}] perms={perms}")

        await await_maybe(pairing.close())

    finally:
        await azc.async_close()


# ── Status check ─────────────────────────────────────────────

async def status():
    """Quick status check."""
    print("\n=== FP2 HAP Client Status ===\n")

    # Network check
    reachable = await check_fp2_reachable()
    print(f"  Сеть: {'OK' if reachable else 'НЕДОСТУПЕН'} ({FP2_IP}:{FP2_PORT})")

    # Pairing check
    paired = PAIRING_DATA_FILE.exists()
    print(f"  Пейринг: {'ЕСТЬ' if paired else 'НЕТ'} ({PAIRING_DATA_FILE})")

    # mDNS check
    if reachable:
        mdns_found = await discover_fp2(timeout=5.0)
        print(f"  mDNS: {'Виден' if mdns_found else 'Не виден (спарен с другим контроллером)'}")

    print()
    if not paired:
        print("  Для пейринга:")
        print("  1. Удалите FP2 из приложения Aqara Home")
        print("  2. Запустите: python3 scripts/fp2_hap_client.py pair")
    elif not reachable:
        print("  FP2 не в сети. Проверьте питание датчика.")
    else:
        print("  Всё готово! Запустите мониторинг:")
        print("  python3 scripts/fp2_hap_client.py monitor")
    print()


# ── Main ─────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(
        description="Прямой HAP-клиент для Aqara FP2",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Примеры:
  %(prog)s status              # Проверить статус
  %(prog)s pair                # Спарить с FP2
  %(prog)s info                # Показать информацию о спаренном FP2
  %(prog)s monitor             # Мониторинг в реальном времени
  %(prog)s monitor --backend http://localhost:8000  # + отправка в бэкенд

Переменные окружения:
  FP2_IP           IP-адрес FP2 (по умолчанию: 192.168.1.52)
  FP2_PORT         Порт FP2 (по умолчанию: 443)
  FP2_HOMEKIT_CODE Код пейринга (обязателен для команды pair)
  LOCAL_IFACE      IP локального интерфейса (по умолчанию: автоопределение)
        """
    )

    sub = parser.add_subparsers(dest="command", help="Команда")

    sub.add_parser("status", help="Проверить статус FP2")
    sub.add_parser("pair", help="Спарить с FP2")
    sub.add_parser("info", help="Показать информацию об устройстве")

    mon = sub.add_parser("monitor", help="Мониторинг в реальном времени")
    mon.add_argument("--backend", type=str, default=None,
                     help="URL бэкенда для отправки данных")
    mon.add_argument("--interval", type=float, default=1.0,
                     help="Интервал опроса в секундах")

    sub.add_parser("discover", help="Поиск FP2 через mDNS")

    args = parser.parse_args()

    if not args.command:
        parser.print_help()
        return

    if args.command == "status":
        asyncio.run(status())
    elif args.command == "pair":
        asyncio.run(pair_fp2())
    elif args.command == "info":
        asyncio.run(info_fp2())
    elif args.command == "monitor":
        asyncio.run(monitor_fp2(
            backend_url=args.backend,
            interval=args.interval,
        ))
    elif args.command == "discover":
        asyncio.run(discover_fp2(timeout=15.0))


if __name__ == "__main__":
    main()
