#!/usr/bin/env python3
"""
FP2 Motion Logger - записывает движения и сетевую статистику.

Использование:
  python3 fp2_motion_logger.py                    # Запись в CSV
  python3 fp2_motion_logger.py --duration 60      # Запись 60 секунд
  python3 fp2_motion_logger.py --visualize        # Показать график из CSV
  python3 fp2_motion_logger.py --realtime         # Real-time визуализация
"""

import argparse
import csv
import os
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path

import requests

# Configuration
HA_URL = os.getenv("HA_URL", "http://localhost:8123")
HA_TOKEN = os.getenv("HA_TOKEN", "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJpc3MiOiI2NWQ5NjQ1ZmI1NTY0OThiOWEyNjc4ZTg0OTczN2QyNCIsImlhdCI6MTc3MjM3MTQzNCwiZXhwIjoyMDg3NzMxNDM0fQ.qpkDjaOaY4sNzz-lzd5wfVUcJXJnoR5p1ca5wQfF13g")
FP2_ENTITY = os.getenv("FP2_ENTITY", "input_boolean.fp2_presence")
ROUTER_IP = "192.168.1.1"  # Keenetic GIGA
LOG_FILE = Path(__file__).parent.parent / "data" / "fp2_motion_log.csv"


def get_fp2_state():
    """Получает состояние FP2 из Home Assistant."""
    try:
        r = requests.get(
            f"{HA_URL}/api/states/{FP2_ENTITY}",
            headers={"Authorization": f"Bearer {HA_TOKEN}"},
            timeout=5
        )
        data = r.json()
        return data.get("state", "unknown")
    except Exception as e:
        return f"error: {e}"


def get_network_stats():
    """Собирает сетевую статистику."""
    stats = {
        "ping_ms": None,
        "packet_loss": None,
    }
    
    # Ping до роутера
    try:
        result = subprocess.run(
            ["ping", "-c", "1", "-W", "1", ROUTER_IP],
            capture_output=True,
            text=True,
            timeout=2
        )
        if result.returncode == 0:
            # Parse ping time
            for line in result.stdout.split("\n"):
                if "time=" in line:
                    time_part = line.split("time=")[1].split()[0]
                    stats["ping_ms"] = float(time_part.replace("ms", ""))
                    stats["packet_loss"] = 0
                    break
        else:
            stats["packet_loss"] = 100
    except Exception:
        stats["packet_loss"] = 100
    
    return stats


def log_event(writer, timestamp, fp2_state, net_stats, event_type=""):
    """Записывает событие в CSV."""
    row = {
        "timestamp": timestamp,
        "fp2_state": fp2_state,
        "ping_ms": net_stats.get("ping_ms", ""),
        "packet_loss": net_stats.get("packet_loss", ""),
        "event": event_type
    }
    writer.writerow(row)
    return row


def record_mode(duration=None, interval=0.5):
    """Режим записи данных."""
    # Создаём директорию если нужно
    LOG_FILE.parent.mkdir(parents=True, exist_ok=True)
    
    # Открываем файл для записи
    file_exists = LOG_FILE.exists()
    f = open(LOG_FILE, "a", newline="")
    writer = csv.DictWriter(f, fieldnames=["timestamp", "fp2_state", "ping_ms", "packet_loss", "event"])
    
    if not file_exists:
        writer.writeheader()
    
    print(f"📝 Запись в {LOG_FILE}")
    print(f"⏱️  Интервал: {interval} сек")
    if duration:
        print(f"⏳ Длительность: {duration} сек")
    print("\nНажмите Ctrl+C для остановки\n")
    
    last_state = None
    start_time = time.time()
    
    try:
        while True:
            # Проверяем длительность
            if duration and (time.time() - start_time) >= duration:
                print(f"\n✅ Запись завершена ({duration} сек)")
                break
            
            # Собираем данные
            timestamp = datetime.now().isoformat()
            fp2_state = get_fp2_state()
            net_stats = get_network_stats()
            
            # Определяем событие
            event = ""
            if fp2_state != last_state:
                if fp2_state == "on":
                    event = "MOTION_START"
                    print(f"🚶 [{timestamp}] Движение обнаружено!")
                elif fp2_state == "off":
                    event = "MOTION_END"
                    print(f"👻 [{timestamp}] Движение прекратилось")
                last_state = fp2_state
            
            # Записываем
            log_event(writer, timestamp, fp2_state, net_stats, event)
            f.flush()
            
            time.sleep(interval)
            
    except KeyboardInterrupt:
        print("\n\n⏹️ Запись остановлена пользователем")
    finally:
        f.close()
        print(f"\n💾 Данные сохранены в: {LOG_FILE}")


def visualize_mode():
    """Режим визуализации данных."""
    if not LOG_FILE.exists():
        print(f"❌ Файл не найден: {LOG_FILE}")
        print("Сначала запустите запись: python3 fp2_motion_logger.py")
        return
    
    try:
        import matplotlib.pyplot as plt
    except ImportError:
        print("Установите matplotlib: pip install matplotlib")
        return
    
    # Читаем данные
    timestamps = []
    fp2_states = []
    pings = []
    
    with open(LOG_FILE, "r") as f:
        reader = csv.DictReader(f)
        for row in reader:
            timestamps.append(datetime.fromisoformat(row["timestamp"]))
            fp2_states.append(1 if row["fp2_state"] == "on" else 0)
            ping = row.get("ping_ms", "")
            pings.append(float(ping) if ping else None)
    
    if not timestamps:
        print("❌ Нет данных для визуализации")
        return
    
    # Строим график
    fig, (ax1, ax2) = plt.subplots(2, 1, figsize=(12, 8), sharex=True)
    
    # FP2 состояние
    ax1.fill_between(timestamps, fp2_states, alpha=0.3, color="green", label="FP2 Presence")
    ax1.set_ylabel("Presence (1=on, 0=off)")
    ax1.set_title("FP2 Motion Detection Log")
    ax1.legend()
    ax1.grid(True, alpha=0.3)
    
    # Ping
    valid_pings = [(t, p) for t, p in zip(timestamps, pings) if p is not None]
    if valid_pings:
        t, p = zip(*valid_pings)
        ax2.plot(t, p, "b-", label="Ping to router", alpha=0.7)
        ax2.set_ylabel("Ping (ms)")
        ax2.set_xlabel("Time")
        ax2.legend()
        ax2.grid(True, alpha=0.3)
    
    plt.tight_layout()
    plt.show()


def realtime_mode(interval=0.5, window=100):
    """Режим real-time визуализации."""
    try:
        import matplotlib.pyplot as plt
        from matplotlib.animation import FuncAnimation
    except ImportError:
        print("Установите matplotlib: pip install matplotlib")
        return
    
    print("🎬 Real-time режим (Ctrl+C для остановки)\n")
    
    # Данные для графика
    timestamps = []
    fp2_states = []
    
    # Создаём фигуру
    fig, ax = plt.subplots(figsize=(12, 4))
    line, = ax.plot([], [], "g-", linewidth=2, label="FP2 Presence")
    ax.set_ylim(-0.1, 1.2)
    ax.set_ylabel("Presence (1=on, 0=off)")
    ax.set_title("FP2 Real-time Motion Detection")
    ax.legend(loc="upper right")
    ax.grid(True, alpha=0.3)
    
    # Текстовый индикатор
    status_text = ax.text(0.02, 0.95, "Ожидание...", transform=ax.transAxes,
                          fontsize=14, verticalalignment="top",
                          bbox=dict(boxstyle="round", facecolor="wheat", alpha=0.5))
    
    def update(frame):
        # Получаем данные
        fp2_state = get_fp2_state()
        now = datetime.now()
        
        # Добавляем в буфер
        timestamps.append(now)
        fp2_states.append(1 if fp2_state == "on" else 0)
        
        # Ограничиваем размер окна
        if len(timestamps) > window:
            timestamps.pop(0)
            fp2_states.pop(0)
        
        # Обновляем график
        if timestamps:
            line.set_data(range(len(timestamps)), fp2_states)
            ax.set_xlim(0, len(timestamps))
            
            # Обновляем статус
            if fp2_state == "on":
                status_text.set_text("🚶 ДВИЖЕНИЕ ОБНАРУЖЕНО")
                status_text.set_color("green")
            elif fp2_state == "off":
                status_text.set_text("👻 Нет движения")
                status_text.set_color("gray")
            else:
                status_text.set_text(f"⚠️ {fp2_state}")
                status_text.set_color("red")
        
        return line, status_text
    
    # Запускаем анимацию
    ani = FuncAnimation(fig, update, interval=int(interval * 1000), blit=False, cache_frame_data=False)
    
    try:
        plt.tight_layout()
        plt.show()
    except KeyboardInterrupt:
        print("\n⏹️ Остановлено")
    finally:
        plt.close()


def main():
    parser = argparse.ArgumentParser(description="FP2 Motion Logger")
    parser.add_argument("--duration", "-d", type=int, help="Длительность записи (сек)")
    parser.add_argument("--interval", "-i", type=float, default=0.5, help="Интервал опроса (сек)")
    parser.add_argument("--visualize", "-v", action="store_true", help="Показать график из CSV")
    parser.add_argument("--realtime", "-r", action="store_true", help="Real-time визуализация")
    args = parser.parse_args()
    
    if args.realtime:
        realtime_mode(args.interval)
    elif args.visualize:
        visualize_mode()
    else:
        record_mode(args.duration, args.interval)


if __name__ == "__main__":
    main()
