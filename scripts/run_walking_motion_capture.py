#!/usr/bin/env python3
"""
Walking Motion Capture — guided recording with video + ElevenLabs voice.

Uses /api/v1/csi/record/start and /stop endpoints directly.
14 clips × 30 sec = 7 min total walking data across center, passage, door zones.
"""

import json
import os
import sys
import time
import urllib.request
import urllib.error
from pathlib import Path
from datetime import datetime

# TTS setup
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from v1.src.services.tts_service import TTSService

WALKING_CLIPS = [
    # CENTER zone
    {"label": "walk_center_slow_1", "duration": 30,
     "prompt": "Иди в центр гаража. Ходи туда-сюда по центру в спокойном темпе. Не останавливайся."},
    {"label": "walk_center_slow_2", "duration": 30,
     "prompt": "Продолжай ходить по центру туда-сюда. Спокойный шаг, не торопись."},
    {"label": "walk_center_normal", "duration": 30,
     "prompt": "Ходи по центру в обычном темпе. Естественная походка туда-сюда."},
    {"label": "walk_center_turns", "duration": 30,
     "prompt": "Ходи по центру с поворотами. Меняй направление каждые несколько шагов."},
    {"label": "walk_center_circle", "duration": 30,
     "prompt": "Ходи по центру по кругу или по восьмёрке. Не останавливайся."},
    # PASSAGE zone
    {"label": "walk_passage_slow_1", "duration": 30,
     "prompt": "Перейди в проход. Ходи по проходу вперёд-назад в спокойном темпе."},
    {"label": "walk_passage_slow_2", "duration": 30,
     "prompt": "Продолжай ходить по проходу. Спокойный шаг туда-сюда."},
    {"label": "walk_passage_normal", "duration": 30,
     "prompt": "Ходи по проходу в обычном темпе. Естественная походка."},
    {"label": "walk_passage_fast", "duration": 30,
     "prompt": "Ходи по проходу чуть быстрее обычного. Энергичный шаг."},
    # DOOR zone
    {"label": "walk_door_slow_1", "duration": 30,
     "prompt": "Перейди к двери. Ходи возле двери туда-сюда в спокойном темпе. Не выходи наружу."},
    {"label": "walk_door_slow_2", "duration": 30,
     "prompt": "Продолжай ходить возле двери. Спокойный шаг, не выходи."},
    {"label": "walk_door_normal", "duration": 30,
     "prompt": "Ходи у двери в обычном темпе. Вперёд-назад вдоль двери."},
    # TRANSITIONS
    {"label": "walk_transition_door_center", "duration": 30,
     "prompt": "Ходи от двери к центру и обратно. Полный маршрут туда-сюда без остановок."},
    {"label": "walk_transition_full_route", "duration": 30,
     "prompt": "Ходи по всему гаражу: дверь — проход — центр — проход — дверь. По кругу без остановок."},
]

API_BASE = "http://127.0.0.1:8000/api/v1"
CAMERA_NAME = "Камера MacBook\u00a0Pro"


def post_json(url: str, data: dict, timeout: float = 60.0) -> dict:
    body = json.dumps(data).encode()
    req = urllib.request.Request(url, data=body, headers={"Content-Type": "application/json"}, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return json.loads(resp.read())
    except urllib.error.HTTPError as e:
        return {"ok": False, "error": f"HTTP {e.code}: {e.read().decode()[:300]}"}
    except Exception as e:
        return {"ok": False, "error": str(e)}


def get_json(url: str, timeout: float = 10.0) -> dict:
    try:
        with urllib.request.urlopen(url, timeout=timeout) as resp:
            return json.loads(resp.read())
    except Exception as e:
        return {"error": str(e)}


def main():
    tts = TTSService()
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    prefix = f"walking_v44_{ts}"

    # Check CSI status
    status = get_json(f"{API_BASE}/csi/status")
    if not status.get("running"):
        print("ERROR: CSI listener not running!", flush=True)
        return 1

    nodes_online = status.get("nodes_online", 0)
    print(f"CSI: running, {nodes_online} nodes online", flush=True)

    tts.speak(f"Начинаем запись ходьбы. Всего {len(WALKING_CLIPS)} клипов по 30 секунд. Семь минут.")
    time.sleep(2)

    results = []
    for i, clip in enumerate(WALKING_CLIPS, 1):
        label = f"{prefix}_{clip['label']}"
        print(f"\n{'='*50}", flush=True)
        print(f"CLIP {i}/{len(WALKING_CLIPS)}: {clip['label']}", flush=True)
        print(f"{'='*50}", flush=True)

        # Voice instruction BEFORE recording
        tts.speak(f"Клип {i} из {len(WALKING_CLIPS)}. {clip['prompt']}")
        time.sleep(1)

        # Countdown
        tts.speak("Старт через 5 секунд.")
        for sec in range(5, 0, -1):
            print(f"  {sec}...", flush=True)
            time.sleep(1)

        # Start recording with video
        tts.speak("Старт.")
        print(f"  Recording {clip['duration']}s with video...", flush=True)

        resp = post_json(f"{API_BASE}/csi/record/start", {
            "label": label,
            "duration_seconds": clip["duration"],
            "chunk_sec": 60,
            "with_video": True,
            "teacher_source_kind": "mac_camera_terminal",
            "teacher_device": "0",
            "teacher_device_name": CAMERA_NAME,
        }, timeout=clip["duration"] + 30)

        if not resp.get("ok"):
            print(f"  WARNING: record/start error: {resp}", flush=True)
            tts.speak("Ошибка запуска записи. Пробую без видео.")
            resp = post_json(f"{API_BASE}/csi/record/start", {
                "label": label,
                "duration_seconds": clip["duration"],
                "chunk_sec": 60,
                "with_video": False,
            }, timeout=clip["duration"] + 30)

        if resp.get("ok"):
            print(f"  Recording started: {label}", flush=True)
            # Wait for recording duration
            time.sleep(clip["duration"])
            # Stop
            stop_resp = post_json(f"{API_BASE}/csi/record/stop", {})
            packets = stop_resp.get("total_packets", 0)
            duration = stop_resp.get("duration_sec", 0)
            print(f"  Stopped: {duration:.1f}s, {packets} packets", flush=True)
            results.append({"label": label, "ok": True, "packets": packets, "duration": duration})
        else:
            print(f"  FAILED: {resp}", flush=True)
            results.append({"label": label, "ok": False, "error": str(resp)})

        # Brief pause between clips
        if i < len(WALKING_CLIPS):
            tts.speak("Пауза 3 секунды.")
            time.sleep(3)

    # Summary
    tts.speak("Запись завершена! Все клипы записаны.")
    print(f"\n{'='*50}", flush=True)
    print("SUMMARY", flush=True)
    print(f"{'='*50}", flush=True)
    ok_count = sum(1 for r in results if r.get("ok"))
    total_packets = sum(r.get("packets", 0) for r in results)
    print(f"  OK: {ok_count}/{len(results)}", flush=True)
    print(f"  Total packets: {total_packets}", flush=True)
    for r in results:
        status_str = "OK" if r.get("ok") else "FAIL"
        print(f"  [{status_str}] {r['label']}: {r.get('packets', 0)} pkts, {r.get('duration', 0):.1f}s", flush=True)

    # Save summary
    summary_path = Path(f"/Users/arsen/Desktop/wifi-densepose/temp/captures/{prefix}_summary.json")
    with open(summary_path, "w") as f:
        json.dump({"prefix": prefix, "clips": results, "total_ok": ok_count, "total_packets": total_packets}, f, indent=2)
    print(f"\nSummary: {summary_path}", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
