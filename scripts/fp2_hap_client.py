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
import getpass
import inspect
import json
import logging
import os
import re
import socket
import sys
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

# ── Paths ────────────────────────────────────────────────────
PROJECT_ROOT = Path(__file__).resolve().parent.parent
PAIRING_DATA_FILE = PROJECT_ROOT / ".fp2_pairing.json"
PAIRING_CODE_FILE = Path(
    os.environ.get("FP2_HOMEKIT_CODE_FILE", str(PROJECT_ROOT / ".fp2_homekit_code"))
)

# ── Known FP2 config ────────────────────────────────────────
FP2_IP = os.environ.get("FP2_IP", "192.168.1.52")
FP2_PORT = int(os.environ.get("FP2_PORT", "443"))
FP2_PAIRING_CODE = os.environ.get("FP2_HOMEKIT_CODE", "")
FP2_MAC = os.environ.get("FP2_MAC", "54:EF:44:79:E0:03")
LOCAL_IFACE = os.environ.get("LOCAL_IFACE")
BACKEND_URL = os.environ.get("BACKEND_URL", "http://localhost:8000")
DISCOVERY_TIMEOUT = float(os.environ.get("FP2_DISCOVERY_TIMEOUT", "3.0"))
RECONNECT_DELAY = float(os.environ.get("FP2_RECONNECT_DELAY", "5.0"))
AUTO_REPAIR_ENABLED = os.environ.get("FP2_AUTO_REPAIR", "true").lower() not in {
    "0", "false", "no"
}

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


def get_pairing_code() -> str:
    """Return HomeKit pairing code from env or local ignored file."""
    if FP2_PAIRING_CODE:
        return FP2_PAIRING_CODE.strip()

    if PAIRING_CODE_FILE.exists():
        try:
            return PAIRING_CODE_FILE.read_text(encoding="utf-8").strip()
        except Exception as exc:
            log.warning("Не удалось прочитать файл кода пейринга %s: %s", PAIRING_CODE_FILE, exc)

    return ""


def mask_pairing_code(code: str) -> str:
    """Mask HomeKit code for logs."""
    cleaned = (code or "").strip()
    if len(cleaned) < 4:
        return "***"
    return f"{cleaned[:3]}-**-***"


def normalize_pairing_code(code: str) -> str:
    """Validate and normalize a HomeKit code to XXX-XX-XXX."""
    digits = re.sub(r"\D", "", (code or "").strip())
    if len(digits) != 8:
        raise ValueError("HomeKit код должен содержать 8 цифр")
    return f"{digits[:3]}-{digits[3:5]}-{digits[5:]}"


def save_pairing_code_file(code: str) -> str:
    """Persist HomeKit code with restrictive file permissions."""
    normalized = normalize_pairing_code(code)
    PAIRING_CODE_FILE.write_text(normalized + "\n", encoding="utf-8")
    os.chmod(PAIRING_CODE_FILE, 0o600)
    return normalized


def prompt_and_save_pairing_code() -> None:
    """Securely prompt for the HomeKit code and store it locally."""
    print(f"\nСохранение HomeKit кода в {PAIRING_CODE_FILE}\n")
    first = getpass.getpass("Введите HomeKit код FP2 (например 123-45-678): ").strip()
    second = getpass.getpass("Повторите код: ").strip()

    if first != second:
        raise ValueError("Коды не совпадают")

    normalized = save_pairing_code_file(first)
    print(f"\nКод сохранён: {mask_pairing_code(normalized)}")
    print("Дальше monitor сможет делать auto-repair автоматически.\n")


def get_local_iface(target_ip: Optional[str] = None) -> str:
    """Best-effort local interface IP used to reach FP2."""
    if LOCAL_IFACE:
        return LOCAL_IFACE

    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        connect_ip = target_ip or "1.1.1.1"
        connect_port = FP2_PORT if target_ip else 80
        sock.connect((connect_ip, connect_port))
        return sock.getsockname()[0]
    finally:
        sock.close()


def save_pairing_data(pairing_data: Dict[str, Any]) -> None:
    """Persist pairing data."""
    PAIRING_DATA_FILE.write_text(json.dumps(pairing_data, indent=2), encoding="utf-8")


def service_is_pairable(service) -> bool:
    """Return True when the advertised HomeKit service is currently pairable."""
    try:
        from aiohomekit.model.status_flags import StatusFlags

        return bool(service and getattr(service, "status_flags", 0) & StatusFlags.UNPAIRED)
    except Exception:
        return False


def service_is_wifi_unconfigured(service) -> bool:
    """Return True when the service reports incomplete Wi-Fi setup."""
    try:
        from aiohomekit.model.status_flags import StatusFlags

        return bool(service and getattr(service, "status_flags", 0) & StatusFlags.WIFI_UNCONFIGURED)
    except Exception:
        return False


def sync_pairing_endpoint(pairing_data: dict, service) -> bool:
    """Refresh stored accessory IP/port from live mDNS discovery."""
    changed = False

    if service is None:
        return False

    if getattr(service, "id", None):
        existing_id = pairing_data.get("AccessoryPairingID")
        if existing_id and existing_id != service.id:
            log.warning(
                "mDNS service id %s does not match pairing id %s; keeping saved pairing id",
                service.id,
                existing_id,
            )
        else:
            pairing_data["AccessoryPairingID"] = service.id

    address = getattr(service, "address", None)
    if address and pairing_data.get("AccessoryIP") != address:
        pairing_data["AccessoryIP"] = address
        pairing_data["AccessoryIPs"] = [address]
        changed = True

    port = getattr(service, "port", None)
    if port and pairing_data.get("AccessoryPort") != port:
        pairing_data["AccessoryPort"] = port
        changed = True

    return changed


def pairing_data_matches_service(pairing_data: Dict[str, Any], service) -> bool:
    """Check whether saved pairing metadata still matches the currently advertised service."""
    if service is None:
        return True

    saved_pairing_id = pairing_data.get("AccessoryPairingID")
    advertised_pairing_id = getattr(service, "id", None)
    if saved_pairing_id and advertised_pairing_id and saved_pairing_id != advertised_pairing_id:
        return False

    return True


async def load_pairing_data(auto_repair: bool = AUTO_REPAIR_ENABLED):
    """Load pairing data and optionally auto-repair when the service changed."""
    service = await discover_fp2_service(timeout=DISCOVERY_TIMEOUT)
    pairing_code = get_pairing_code()

    if service is not None:
        log.info(
            "Обнаружен FP2: %s:%s pairable=%s wifi_unconfigured=%s",
            service.address,
            service.port,
            "yes" if service_is_pairable(service) else "no",
            "yes" if service_is_wifi_unconfigured(service) else "no",
        )

    if not PAIRING_DATA_FILE.exists():
        if service and service_is_pairable(service) and auto_repair and pairing_code:
            log.info("Пейринга нет; выполняю автоматический пейринг FP2.")
            if await pair_fp2(force=True, service=service, pairing_code=pairing_code):
                return json.loads(PAIRING_DATA_FILE.read_text(encoding="utf-8")), service

        return None, service, (
            "Нет локального pairing state. Укажите FP2_HOMEKIT_CODE или файл .fp2_homekit_code "
            "для автоматического пейринга."
        )

    pairing_data = json.loads(PAIRING_DATA_FILE.read_text(encoding="utf-8"))

    if service is not None and sync_pairing_endpoint(pairing_data, service):
        save_pairing_data(pairing_data)
        log.info(
            "Обновлён endpoint FP2 из mDNS: %s:%s",
            pairing_data.get("AccessoryIP"),
            pairing_data.get("AccessoryPort"),
        )

    if service is not None:
        needs_repair = service_is_pairable(service) or not pairing_data_matches_service(pairing_data, service)
        if needs_repair:
            if auto_repair and pairing_code:
                log.warning("Сохранённый pairing устарел; выполняю автоматический re-pair.")
                if await pair_fp2(force=True, service=service, pairing_code=pairing_code):
                    return json.loads(PAIRING_DATA_FILE.read_text(encoding="utf-8")), service
                return None, service, "Автоматический re-pair не удался."

            return None, service, (
                "FP2 снова в pairable-состоянии или сменил HomeKit identity. "
                "Нужен FP2_HOMEKIT_CODE для автоматического re-pair."
            )

    return pairing_data, service, None

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

    if sys.platform == "darwin":
        service = await discover_fp2_service_via_dns_sd(timeout=timeout)
        if service is not None:
            return service

    return None


async def _run_for_duration(*args: str, duration: float = 5.0) -> str:
    """Run a subprocess briefly and capture its output."""
    proc = await asyncio.create_subprocess_exec(
        *args,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.STDOUT,
    )
    try:
        await asyncio.sleep(duration)
    finally:
        if proc.returncode is None:
            proc.terminate()
            try:
                await asyncio.wait_for(proc.wait(), timeout=2.0)
            except asyncio.TimeoutError:
                proc.kill()
                await proc.wait()

    output = await proc.stdout.read()
    return output.decode("utf-8", errors="ignore")


def _parse_dns_sd_props(line: str) -> Dict[str, str]:
    """Parse key=value TXT props from dns-sd output."""
    props: Dict[str, str] = {}
    for token in line.strip().split():
        if "=" not in token:
            continue
        key, value = token.split("=", 1)
        props[key.strip()] = value.strip()
    return props


async def discover_fp2_service_via_dns_sd(timeout: float = 5.0):
    """Fallback FP2 discovery using macOS dns-sd."""
    from aiohomekit.model import Categories
    from aiohomekit.model.feature_flags import FeatureFlags
    from aiohomekit.model.status_flags import StatusFlags
    from aiohomekit.zeroconf import HomeKitService

    browse_output = await _run_for_duration("dns-sd", "-B", "_hap._tcp", "local.", duration=max(timeout, 3.0))
    candidates = []
    for line in browse_output.splitlines():
        match = re.search(r"_hap\._tcp\.\s+(?P<name>.+)$", line)
        if not match:
            continue
        name = match.group("name").strip()
        if "FP2" in name or "Presence" in name:
            candidates.append(name)

    for name in candidates:
        lookup_output = await _run_for_duration("dns-sd", "-L", name, "_hap._tcp", "local.", duration=3.0)
        host = None
        port = None
        props: Dict[str, str] = {}

        for line in lookup_output.splitlines():
            reached = re.search(r"can be reached at\s+(?P<host>[^:]+):(?P<port>\d+)", line)
            if reached:
                host = reached.group("host").strip()
                port = int(reached.group("port"))
                continue

            parsed_props = _parse_dns_sd_props(line)
            if parsed_props:
                props.update(parsed_props)

        if not host or not port:
            continue

        address_output = await _run_for_duration("dns-sd", "-G", "v4", host, duration=3.0)
        address = None
        for line in address_output.splitlines():
            match = re.search(rf"{re.escape(host)}\s+(?P<address>\d+\.\d+\.\d+\.\d+)", line)
            if match:
                address = match.group("address")
                break

        if not address:
            continue

        try:
            service = HomeKitService(
                name=name,
                id=props.get("id", FP2_MAC),
                model=props.get("md", "PS-S02D"),
                feature_flags=FeatureFlags(int(props.get("ff", "0"))),
                status_flags=StatusFlags(int(props.get("sf", "0"))),
                config_num=int(props.get("c#", props.get("s#", "1"))),
                state_num=int(props.get("s#", "1")),
                category=Categories(int(props.get("ci", "10"))),
                protocol_version=props.get("pv", "1.1"),
                type="_hap._tcp.local.",
                address=address,
                addresses=[address],
                port=port,
            )
            log.info(
                "FP2 service (dns-sd fallback): name=%s id=%s address=%s port=%s model=%s",
                service.name,
                service.id,
                service.address,
                service.port,
                service.model,
            )
            return service
        except Exception as exc:
            log.warning("dns-sd fallback parse failed for %s: %s", name, exc)

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

async def pair_fp2(force: bool = False, service=None, pairing_code: Optional[str] = None):
    """Pair with FP2 using HomeKit protocol."""
    from aiohomekit.controller.ip import IpController
    from aiohomekit.controller.ip.discovery import IpDiscovery
    from zeroconf.asyncio import AsyncZeroconf

    effective_pairing_code = (pairing_code or get_pairing_code()).strip()

    if PAIRING_DATA_FILE.exists() and not force:
        log.warning("Файл пейринга уже существует: %s", PAIRING_DATA_FILE)
        log.warning("Удалите его для повторного пейринга: rm %s", PAIRING_DATA_FILE)
        return False

    if not effective_pairing_code:
        log.error(
            "Не задан FP2_HOMEKIT_CODE. Укажите HomeKit код через переменную окружения "
            "или сохраните его в %s.",
            PAIRING_CODE_FILE,
        )
        return False

    service = service or await discover_fp2_service(timeout=5.0)
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
    log.info("  Код: %s", mask_pairing_code(effective_pairing_code))

    azc = AsyncZeroconf(interfaces=[get_local_iface(service.address)])
    controller = None

    try:
        char_cache = create_characteristic_cache()
        controller = IpController(char_cache=char_cache, zeroconf_instance=azc)

        discovery = IpDiscovery(controller, service)

        log.info("Отправляю запрос на пейринг...")
        finish_pairing = await discovery.async_start_pairing("fp2_sensor")

        log.info("Ввожу код пейринга: %s", mask_pairing_code(effective_pairing_code))
        pairing = await finish_pairing(effective_pairing_code)

        pairing_data = pairing.pairing_data
        sync_pairing_endpoint(pairing_data, service)
        save_pairing_data(pairing_data)
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
    from aiohomekit.exceptions import AccessoryDisconnectedError
    from zeroconf.asyncio import AsyncZeroconf

    http_session = None
    if backend_url:
        import aiohttp
        http_session = aiohttp.ClientSession()

    log.info("")
    log.info("=" * 60)
    log.info("  МОНИТОРИНГ FP2 В РЕАЛЬНОМ ВРЕМЕНИ")
    log.info("  Автовосстановление включено: %s", "да" if AUTO_REPAIR_ENABLED else "нет")
    log.info("  Нажмите Ctrl+C для остановки")
    log.info("=" * 60)
    log.info("")

    poll_count = 0

    try:
        while True:
            azc = None
            controller = None
            pairing = None
            try:
                pairing_data, service, reason = await load_pairing_data(auto_repair=AUTO_REPAIR_ENABLED)
                if not pairing_data:
                    log.warning("%s", reason)
                    await asyncio.sleep(RECONNECT_DELAY)
                    continue

                target_ip = pairing_data.get("AccessoryIP")
                azc = AsyncZeroconf(interfaces=[get_local_iface(target_ip)])
                char_cache = create_characteristic_cache()
                controller = IpController(char_cache=char_cache, zeroconf_instance=azc)

                pairing = await await_maybe(controller.load_pairing("fp2_sensor", pairing_data))
                if pairing is None:
                    log.warning("Не удалось восстановить pairing из файла. Пробую заново.")
                    await asyncio.sleep(RECONNECT_DELAY)
                    continue

                log.info(
                    "Подключение к FP2 восстановлено (%s:%s)",
                    pairing_data.get("AccessoryIP"),
                    pairing_data.get("AccessoryPort"),
                )

                accessories = await await_maybe(pairing.list_accessories_and_characteristics())

                occupancy_chars = []
                light_chars = []

                for acc in accessories:
                    for svc in acc.get("services", []):
                        for char in svc.get("characteristics", []):
                            ctype = char.get("type", "").upper()
                            aid = acc.get("aid", 1)
                            iid = char.get("iid", 0)

                            if is_standard_homekit_char(ctype, "71"):
                                occupancy_chars.append({
                                    "aid": aid, "iid": iid,
                                    "name": f"occupancy_{svc.get('iid',0)}",
                                    "service_iid": svc.get("iid", 0),
                                })
                            elif is_standard_homekit_char(ctype, "6B"):
                                light_chars.append({
                                    "aid": aid, "iid": iid,
                                    "name": f"light_{svc.get('iid',0)}",
                                })

                log.info(
                    "Найдено %d датчиков присутствия, %d датчиков освещения",
                    len(occupancy_chars),
                    len(light_chars),
                )

                if not occupancy_chars:
                    log.warning("Датчики присутствия не найдены. Переподключаюсь.")
                    await asyncio.sleep(RECONNECT_DELAY)
                    continue

                chars_to_read = [(c["aid"], c["iid"]) for c in occupancy_chars + light_chars]

                while True:
                    try:
                        values = await await_maybe(pairing.get_characteristics(chars_to_read)) if chars_to_read else {}

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
                        status = "ПРИСУТСТВИЕ" if presence else "Пусто"
                        zone_str = ", ".join(
                            f"{z['zone_id']}={'ДА' if z['occupied'] else 'нет'}" for z in zones
                        )
                        light_str = f" | Свет: {light_level:.0f} lux" if light_level is not None else ""

                        poll_count += 1
                        log.info("[%d] %s | Зоны: %s%s", poll_count, status, zone_str, light_str)

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
                            except Exception as exc:
                                log.debug("Backend недоступен: %s", exc)

                    except (AccessoryDisconnectedError, TimeoutError, asyncio.TimeoutError) as exc:
                        log.warning("Связь с FP2 потеряна: %s", exc)
                        break
                    except Exception as exc:
                        log.warning("Ошибка чтения FP2: %s", exc)
                        break

                    await asyncio.sleep(interval)

            except KeyboardInterrupt:
                raise
            except Exception as exc:
                log.error("Ошибка monitor loop: %s", exc)
            finally:
                if pairing is not None:
                    try:
                        await await_maybe(pairing.close())
                    except Exception:
                        pass
                if controller is not None:
                    try:
                        await await_maybe(controller.async_shutdown())
                    except Exception:
                        pass
                if azc is not None:
                    await azc.async_close()

            log.info("Повторная попытка через %.1f сек...", RECONNECT_DELAY)
            await asyncio.sleep(RECONNECT_DELAY)

    except KeyboardInterrupt:
        log.info("Мониторинг остановлен")
    finally:
        if http_session and not http_session.closed:
            await http_session.close()


# ── Info ─────────────────────────────────────────────────────

async def info_fp2():
    """Show info about paired FP2."""
    from aiohomekit.controller.ip import IpController
    from zeroconf.asyncio import AsyncZeroconf

    pairing_data, service, reason = await load_pairing_data(auto_repair=AUTO_REPAIR_ENABLED)
    if pairing_data is None:
        log.error("%s", reason)
        return

    azc = AsyncZeroconf(interfaces=[get_local_iface(pairing_data.get("AccessoryIP"))])

    controller = None
    pairing = None
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

    finally:
        if pairing is not None:
            try:
                await await_maybe(pairing.close())
            except Exception:
                pass
        if controller is not None:
            try:
                await await_maybe(controller.async_shutdown())
            except Exception:
                pass
        await azc.async_close()


# ── Status check ─────────────────────────────────────────────

async def status():
    """Quick status check."""
    print("\n=== FP2 HAP Client Status ===\n")

    service = await discover_fp2_service(timeout=DISCOVERY_TIMEOUT)
    if service:
        print(
            f"  mDNS: Виден ({service.address}:{service.port}) "
            f"pairable={'ДА' if service_is_pairable(service) else 'нет'}"
        )
    else:
        print("  mDNS: Не виден")

    # Pairing check
    paired = PAIRING_DATA_FILE.exists()
    print(f"  Пейринг: {'ЕСТЬ' if paired else 'НЕТ'} ({PAIRING_DATA_FILE})")
    print(f"  Авто-repair: {'ВКЛ' if AUTO_REPAIR_ENABLED else 'ВЫКЛ'}")
    print(f"  Код пейринга: {'ЕСТЬ' if bool(get_pairing_code()) else 'НЕТ'} ({PAIRING_CODE_FILE})")

    print()
    if service is None:
        print("  FP2 сейчас не виден через mDNS. Monitor будет ждать его появления и пробовать переподключиться.")
    elif service and service_is_pairable(service) and not get_pairing_code():
        print("  FP2 доступен для pairing, но HomeKit код не задан.")
        print(f"  Выполните '{Path(sys.argv[0]).name} set-code' или сохраните код в {PAIRING_CODE_FILE}.")
    elif service and service_is_pairable(service) and get_pairing_code():
        print("  FP2 доступен для pairing. monitor выполнит auto-repair сам.")
    elif not paired:
        print("  Нет pairing state. monitor сможет сделать auto-pair, если задан FP2_HOMEKIT_CODE.")
    else:
        print("  Всё готово. monitor сам переживает смену IP/порта и переподключается.")
    print()


# ── Main ─────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(
        description="Прямой HAP-клиент для Aqara FP2",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Примеры:
  %(prog)s status              # Проверить статус
  %(prog)s set-code            # Сохранить HomeKit код локально
  %(prog)s pair                # Спарить с FP2
  %(prog)s repair              # Принудительно пересоздать pairing
  %(prog)s info                # Показать информацию о спаренном FP2
  %(prog)s monitor             # Мониторинг + автоrecovery
  %(prog)s monitor --backend http://localhost:8000  # + отправка в бэкенд

Переменные окружения:
  FP2_HOMEKIT_CODE       Код пейринга для auto-pair / auto-repair
  FP2_HOMEKIT_CODE_FILE  Локальный файл с кодом (по умолчанию: .fp2_homekit_code)
  FP2_AUTO_REPAIR        true/false, автоперепривязка при сбросе pairing
  FP2_RECONNECT_DELAY    Задержка повторного подключения
  LOCAL_IFACE            IP локального интерфейса (по умолчанию: автоопределение)
        """
    )

    sub = parser.add_subparsers(dest="command", help="Команда")

    sub.add_parser("status", help="Проверить статус FP2")
    sub.add_parser("set-code", help="Сохранить HomeKit код FP2 локально")
    sub.add_parser("pair", help="Спарить с FP2")
    sub.add_parser("repair", help="Пересоздать pairing для FP2")
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
    elif args.command == "set-code":
        prompt_and_save_pairing_code()
    elif args.command == "pair":
        asyncio.run(pair_fp2())
    elif args.command == "repair":
        asyncio.run(pair_fp2(force=True))
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
