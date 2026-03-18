#!/bin/bash
# Structured STATIC-focused recording session with voice prompts
# 12 clips: 3 empty, 3 static, 3 breathing, 3 motion (for contrast)
# Voice: macOS Milena (Russian)

VENV="venv/bin/python3"
CAPTURE="scripts/run_atomic_csi_training_capture.py"
PREFIX="structured_static_20260318"
EPOCH="garage_ceiling_v2"
GEO="ceiling_fixed_mount_v2"
VIDEO_URL="rtsp://admin:admin@192.168.1.148:8554/live"

# Use long_capture_daemon for each clip since atomic capture needs backend
CAPTURES_DIR="temp/captures"

record_clip() {
    local LABEL=$1
    local DURATION=$2
    local PC=$3
    local STEP=$4
    local VOICE_MSG=$5

    echo ""
    echo "============================================"
    echo "  CLIP: $LABEL"
    echo "  Duration: ${DURATION}s, Person: $PC, Step: $STEP"
    echo "============================================"

    # Voice prompt
    say -v Milena "$VOICE_MSG" &
    SAYPID=$!
    wait $SAYPID 2>/dev/null

    # Countdown
    say -v Milena "Три" & sleep 1
    say -v Milena "Два" & sleep 1
    say -v Milena "Один" & sleep 1
    say -v Milena "Запись" & sleep 0.5

    # Record CSI + video
    $VENV -c "
import gzip, json, socket, time, subprocess, threading

label = '$LABEL'
duration = $DURATION
pc = $PC
step = '$STEP'

# Start video recording
video_path = 'temp/captures/${LABEL}.teacher.mp4'
video_proc = subprocess.Popen([
    'ffmpeg', '-y', '-i', '$VIDEO_URL',
    '-t', str(duration + 2),
    '-c:v', 'copy', '-c:a', 'copy',
    '-loglevel', 'error',
    video_path
], stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)

# Record CSI
s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
s.bind(('0.0.0.0', 5005))
s.settimeout(1)

import base64
csi_path = 'temp/captures/${LABEL}.ndjson.gz'
f = gzip.open(csi_path, 'wt')
t0 = time.time()
count = 0
sources = set()

while time.time() - t0 < duration:
    try:
        data, addr = s.recvfrom(4096)
        ts = time.time_ns()
        rec = {
            'ts_ns': ts,
            'src_ip': addr[0],
            'src_port': addr[1],
            'payload_b64': base64.b64encode(data).decode()
        }
        f.write(json.dumps(rec) + '\n')
        count += 1
        sources.add(addr[0])
    except socket.timeout:
        continue

f.close()
s.close()
video_proc.terminate()
video_proc.wait()

# Save summary
summary = {
    'label': label,
    'person_count_expected': pc,
    'step_name': step,
    'duration_sec': duration,
    'packet_count': count,
    'source_count': len(sources),
    'dataset_epoch': '$EPOCH',
    'geometry_label': '$GEO',
    'label_source': 'structured_voice_session',
    'space_id': 'garage',
}
with open('temp/captures/${LABEL}.summary.json', 'w') as sf:
    json.dump(summary, sf, indent=2)

print(f'  OK: {count} pkts, {len(sources)} nodes, video={\"OK\" if video_proc.returncode == 0 else \"SAVED\"}')" 2>&1

    # Voice confirmation
    say -v Milena "Готово" &
    sleep 2
}

echo "========================================================"
echo "  STRUCTURED STATIC SESSION"
echo "  12 clips with voice commands"
echo "========================================================"
say -v Milena "Начинаем структурированную сессию записи. Двенадцать клипов. Следуй голосовым командам."
sleep 2

# ── BLOCK 1: EMPTY (3 clips) ──
say -v Milena "Блок первый. Пустая комната. Выйди из гаража и закрой дверь."
echo ""
echo ">>> WAITING: Exit garage and close door <<<"
sleep 15

record_clip "${PREFIX}_clip01_empty_baseline" 20 0 "empty_room" \
    "Клип один. Пустая комната. Базовая линия. Двадцать секунд."

record_clip "${PREFIX}_clip02_empty_settled" 20 0 "empty_room" \
    "Клип два. Пустая комната. Стабильный сигнал. Двадцать секунд."

record_clip "${PREFIX}_clip03_empty_long" 30 0 "empty_room" \
    "Клип три. Пустая комната. Длинная запись. Тридцать секунд."

# ── BLOCK 2: STATIC (3 clips) ──
say -v Milena "Блок второй. Статика. Зайди в гараж и встань неподвижно в центре."
echo ""
echo ">>> WAITING: Enter garage, stand still in center <<<"
sleep 15

record_clip "${PREFIX}_clip04_stand_center" 25 1 "quiet_static" \
    "Клип четыре. Стой неподвижно в центре. Не двигайся. Двадцать пять секунд."

record_clip "${PREFIX}_clip05_stand_near_exit" 25 1 "quiet_static" \
    "Клип пять. Перейди к выходу и стой неподвижно. Двадцать пять секунд."

say -v Milena "Теперь сядь на стул или на корточки в центре."
sleep 8

record_clip "${PREFIX}_clip06_sit_center" 25 1 "sit_down_hold" \
    "Клип шесть. Сиди неподвижно в центре. Двадцать пять секунд."

# ── BLOCK 3: BREATHING (3 clips) ──
say -v Milena "Блок третий. Дыхание. Встань в центре."
sleep 5

record_clip "${PREFIX}_clip07_normal_breath" 25 1 "normal_breath" \
    "Клип семь. Дыши нормально. Стой неподвижно. Двадцать пять секунд."

record_clip "${PREFIX}_clip08_deep_breath" 25 1 "deep_breath" \
    "Клип восемь. Дыши глубоко. Глубокий вдох. Глубокий выдох. Двадцать пять секунд."

say -v Milena "Присядь на корточки и дыши нормально."
sleep 5

record_clip "${PREFIX}_clip09_squat_breath" 25 1 "squat_hold" \
    "Клип девять. Сиди на корточках. Дыши нормально. Двадцать пять секунд."

# ── BLOCK 4: MOTION for contrast (3 clips) ──
say -v Milena "Блок четвёртый. Движение для контраста."
sleep 3

record_clip "${PREFIX}_clip10_walk_slow" 25 1 "slow_walk" \
    "Клип десять. Ходи медленно по гаражу. Двадцать пять секунд."

record_clip "${PREFIX}_clip11_walk_normal" 25 1 "walk_freeform" \
    "Клип одиннадцать. Ходи в нормальном темпе. Двадцать пять секунд."

record_clip "${PREFIX}_clip12_walk_then_stop" 25 1 "walk_freeform" \
    "Клип двенадцать. Ходи десять секунд, потом замри. Двадцать пять секунд."

echo ""
echo "========================================================"
echo "  SESSION COMPLETE!"
echo "========================================================"
say -v Milena "Сессия завершена. Спасибо. Двенадцать клипов записаны."
