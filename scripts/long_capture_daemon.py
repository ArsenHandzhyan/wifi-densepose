#!/usr/bin/env python3
"""
Long-running CSI + Video capture daemon.
Runs for up to MAX_DURATION_SEC (default 2h), splits into CHUNK_SEC clips.
Self-monitors node health and video stream. Auto-recovers on failures.

Usage:
    python3 scripts/long_capture_daemon.py          # 2 hours
    python3 scripts/long_capture_daemon.py --hours 4  # 4 hours

Stop gracefully: touch /tmp/csi_capture_stop
Or: kill -SIGINT <pid>
"""
import socket, time, gzip, json, base64, subprocess, os, sys, signal, argparse
from pathlib import Path
from datetime import datetime

# ── Config ────────────────────────────────────────────────────────────────────
CHUNK_SEC = 300          # 5-minute chunks
RTSP_URL = "rtsp://admin:admin@192.168.1.148:8554/live"
UDP_PORT = 5005
EXPECTED_NODES = 4
MIN_NODES = 2
MIN_PPS_PER_NODE = 10
HEALTH_CHECK_INTERVAL = 30
STOP_FILE = "/tmp/csi_capture_stop"

PROJECT_ROOT = Path(__file__).resolve().parents[1]
CAPTURE_DIR = PROJECT_ROOT / "temp" / "captures"
LOG_FILE = PROJECT_ROOT / "temp" / "long_capture.log"

# ── Globals ───────────────────────────────────────────────────────────────────
running = True
current_ffmpeg = None

def signal_handler(sig, frame):
    global running
    running = False
    log("SIGINT received, finishing current chunk...")

signal.signal(signal.SIGINT, signal_handler)
signal.signal(signal.SIGTERM, signal_handler)

def log(msg):
    ts = datetime.now().strftime("%H:%M:%S")
    line = f"[{ts}] {msg}"
    print(line, flush=True)
    try:
        with open(LOG_FILE, "a") as f:
            f.write(line + "\n")
    except:
        pass

def check_stop_file():
    if os.path.exists(STOP_FILE):
        os.remove(STOP_FILE)
        return True
    return False

def start_video(path, duration):
    """Start ffmpeg RTSP capture, return Popen or None."""
    try:
        proc = subprocess.Popen([
            "ffmpeg", "-y", "-rtsp_transport", "tcp",
            "-i", RTSP_URL,
            "-t", str(duration + 5),
            "-c:v", "copy", "-an",
            str(path)
        ], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        return proc
    except Exception as e:
        log(f"  VIDEO FAIL: {e}")
        return None

def stop_video(proc):
    """Gracefully stop ffmpeg."""
    if proc is None:
        return
    try:
        proc.terminate()
        proc.wait(timeout=5)
    except:
        try:
            proc.kill()
        except:
            pass

def capture_chunk(chunk_idx, duration):
    """Record one chunk of CSI + video. Returns summary dict."""
    global current_ffmpeg, running

    stamp = time.strftime("%Y%m%d_%H%M%S")
    label = f"longcap_chunk{chunk_idx:04d}_{stamp}"

    csi_path = CAPTURE_DIR / f"{label}.ndjson.gz"
    video_path = CAPTURE_DIR / f"{label}.teacher.mp4"
    summary_path = CAPTURE_DIR / f"{label}.summary.json"
    clip_path = CAPTURE_DIR / f"{label}.clip.json"

    log(f"CHUNK {chunk_idx}: {label} ({duration}s)")

    # Start video
    current_ffmpeg = start_video(video_path, duration)

    # CSI capture
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    sock.settimeout(1)
    sock.bind(("0.0.0.0", UDP_PORT))

    nodes = {}
    packet_count = 0
    start = time.time()
    start_ns = time.time_ns()
    last_health = start
    health_ok = True
    health_warnings = []

    with gzip.open(str(csi_path), "wt") as f:
        while time.time() - start < duration and running:
            # Check stop file
            if check_stop_file():
                log("  Stop file detected!")
                running = False
                break

            try:
                data, addr = sock.recvfrom(4096)
                ip = addr[0]
                nodes[ip] = nodes.get(ip, 0) + 1
                packet_count += 1
                f.write(json.dumps({
                    "ts_ns": time.time_ns(),
                    "src_ip": ip,
                    "src_port": addr[1],
                    "payload_b64": base64.b64encode(data).decode()
                }) + "\n")
            except socket.timeout:
                continue

            # Periodic health check
            now = time.time()
            if now - last_health >= HEALTH_CHECK_INTERVAL:
                elapsed = now - start
                pps = packet_count / elapsed if elapsed > 0 else 0
                node_count = len(nodes)

                status = "OK" if node_count >= MIN_NODES and pps > MIN_PPS_PER_NODE * MIN_NODES else "DEGRADED"
                log(f"  [{int(elapsed)}s] {packet_count} pkts ({pps:.0f}/s) | {node_count} nodes | {status}")

                if node_count < MIN_NODES:
                    health_warnings.append(f"t={int(elapsed)}s: only {node_count} nodes")
                    health_ok = False

                # Check video process
                if current_ffmpeg and current_ffmpeg.poll() is not None:
                    log(f"  VIDEO DIED (rc={current_ffmpeg.returncode}), restarting...")
                    remaining = duration - elapsed
                    if remaining > 5:
                        current_ffmpeg = start_video(video_path, remaining)

                last_health = now

    sock.close()
    elapsed = time.time() - start

    # Stop video
    stop_video(current_ffmpeg)
    current_ffmpeg = None

    video_ok = video_path.exists() and video_path.stat().st_size > 1000
    video_size = video_path.stat().st_size if video_ok else 0
    csi_size = csi_path.stat().st_size

    # Write manifests
    summary = {
        "label": label,
        "capture_label": label,
        "step_name": "long_capture_freeform",
        "person_count_expected": -1,
        "dataset_epoch": "garage_ceiling_v2",
        "geometry_label": "ceiling_fixed_mount_v2",
        "space_id": "garage",
        "feature_schema_version": "2026-03-12-phase-room-v1",
        "training_eligible": True,
        "duration_sec": round(elapsed, 1),
        "total_packets": packet_count,
        "packets_per_sec": round(packet_count / max(elapsed, 0.1), 1),
        "sources": {ip: cnt for ip, cnt in sorted(nodes.items())},
        "source_count": len(nodes),
        "video_ok": video_ok,
        "csi_bytes": csi_size,
        "video_bytes": video_size,
        "health_ok": health_ok,
        "health_warnings": health_warnings,
        "chunk_index": chunk_idx,
        "notes": "Long capture daemon chunk. Annotate from video post-hoc.",
    }

    clip = {
        "capture_label": label,
        "step_name": "long_capture_freeform",
        "label_name": "long_capture_freeform",
        "label_prefix": "longcap",
        "person_count_expected": -1,
        "dataset_epoch": "garage_ceiling_v2",
        "geometry_label": "ceiling_fixed_mount_v2",
        "space_id": "garage",
        "feature_schema_version": "2026-03-12-phase-room-v1",
        "duration_requested_sec": duration,
        "duration_actual_sec": round(elapsed, 1),
        "csi_health_snapshot": {"all_ok": health_ok, "source_count": len(nodes)},
        "files": {
            "csi_ndjson": str(csi_path),
            "video_mp4": str(video_path) if video_ok else None,
            "summary": str(summary_path),
        },
        "started_at_ns": start_ns,
    }

    for path, content in [(summary_path, summary), (clip_path, clip)]:
        with open(path, "w") as f:
            json.dump(content, f, indent=2)

    log(f"  Done: {packet_count} pkts | {len(nodes)} nodes | CSI {csi_size//1024}KB | Video {'OK' if video_ok else 'FAIL'} {video_size//1024}KB")
    return summary


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--hours", type=float, default=2.0)
    parser.add_argument("--chunk-sec", type=int, default=CHUNK_SEC)
    args = parser.parse_args()

    max_duration = args.hours * 3600
    chunk_sec = args.chunk_sec

    CAPTURE_DIR.mkdir(parents=True, exist_ok=True)

    # Remove old stop file
    if os.path.exists(STOP_FILE):
        os.remove(STOP_FILE)

    log("=" * 60)
    log(f"LONG CAPTURE DAEMON STARTED")
    log(f"  Max duration: {args.hours}h ({int(max_duration)}s)")
    log(f"  Chunk size: {chunk_sec}s ({chunk_sec//60}min)")
    log(f"  RTSP: {RTSP_URL}")
    log(f"  UDP port: {UDP_PORT}")
    log(f"  PID: {os.getpid()}")
    log(f"  Stop: touch {STOP_FILE}")
    log("=" * 60)

    # Write PID file
    pid_file = PROJECT_ROOT / "temp" / "long_capture.pid"
    with open(pid_file, "w") as f:
        f.write(str(os.getpid()))

    global_start = time.time()
    chunk_idx = 0
    total_packets = 0
    total_chunks = 0

    while running:
        elapsed = time.time() - global_start
        remaining = max_duration - elapsed

        if remaining <= 0:
            log("Max duration reached.")
            break

        chunk_duration = min(chunk_sec, remaining)
        if chunk_duration < 10:
            break

        chunk_idx += 1
        try:
            summary = capture_chunk(chunk_idx, int(chunk_duration))
            total_packets += summary["total_packets"]
            total_chunks += 1
        except Exception as e:
            log(f"CHUNK ERROR: {e}")
            time.sleep(5)
            continue

        # Brief pause between chunks to let ffmpeg clean up
        if running:
            time.sleep(2)

    total_elapsed = time.time() - global_start
    log("=" * 60)
    log(f"CAPTURE DAEMON STOPPED")
    log(f"  Total time: {total_elapsed/60:.1f} min")
    log(f"  Chunks: {total_chunks}")
    log(f"  Total packets: {total_packets}")
    log(f"  Avg rate: {total_packets/max(total_elapsed,1):.0f} pkt/s")
    log("=" * 60)

    # Cleanup
    if pid_file.exists():
        pid_file.unlink()


if __name__ == "__main__":
    main()
