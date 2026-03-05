#!/usr/bin/env python3
"""
FP2 Discovery Monitor

Monitors network for FP2 presence after factory reset.
FP2 in pairing mode:
- Hostname: EP2016 or similar
- mDNS: _hap._tcp
- IP: DHCP assigned
- LED: blinking

Usage:
    sudo python3 scripts/fp2_discovery_monitor.py
"""

import socket
import struct
import sys
import time
import subprocess
from datetime import datetime


def log(msg):
    print(f"[{datetime.now().strftime('%H:%M:%S')}] {msg}", flush=True)


def scan_mdns():
    """Scan for _hap._tcp services (HomeKit devices)."""
    try:
        result = subprocess.run(
            ["dns-sd", "-B", "_hap._tcp", "local."],
            capture_output=True, text=True, timeout=5
        )
        lines = result.stdout.split('\n')
        devices = []
        for line in lines:
            if 'Add' in line and 'hap' in line.lower():
                parts = line.split()
                if len(parts) >= 7:
                    devices.append({
                        'name': parts[3],
                        'type': parts[4],
                        'domain': parts[5]
                    })
        return devices
    except Exception as e:
        return []


def scan_arp():
    """Check ARP table for known FP2 MAC patterns (Aqara)."""
    try:
        result = subprocess.run(["arp", "-a"], capture_output=True, text=True)
        lines = result.stdout.split('\n')
        candidates = []
        for line in lines:
            # Aqara MAC prefixes
            if any(prefix in line.lower() for prefix in ['54:ef', 'cc:4b', '64:69']):
                candidates.append(line.strip())
        return candidates
    except Exception:
        return []


def ping_sweep():
    """Quick ping sweep of local subnet."""
    log("Scanning 192.168.1.0/24...")
    found = []
    for i in range(1, 255):
        ip = f"192.168.1.{i}"
        try:
            result = subprocess.run(
                ["ping", "-c", "1", "-W", "100", ip],
                capture_output=True, timeout=1
            )
            if result.returncode == 0:
                found.append(ip)
        except:
            pass
    return found


def check_fp2_http(ip):
    """Check if device at IP responds like FP2."""
    try:
        import urllib.request
        # FP2 HAP endpoint
        req = urllib.request.Request(
            f"http://{ip}:80",
            method="GET",
            headers={"Host": "EP2016"},
            timeout=2
        )
        try:
            urllib.request.urlopen(req)
        except urllib.error.HTTPError as e:
            # FP2 returns 400 or 405 on root, that's expected
            return True
    except:
        pass
    return False


def main():
    log("=" * 50)
    log("FP2 Discovery Monitor STARTED")
    log("Waiting for FP2 in pairing mode...")
    log("LED should be: BLINKING")
    log("=" * 50)

    known_ips = set()
    iteration = 0

    while True:
        iteration += 1
        log(f"--- Scan #{iteration} ---")

        # Method 1: mDNS discovery
        mdns_devices = scan_mdns()
        for dev in mdns_devices:
            log(f"[mDNS] Found: {dev['name']}.{dev['type']}")
            if 'ep' in dev['name'].lower() or 'fp2' in dev['name'].lower():
                log(f"*** FP2 CANDIDATE: {dev['name']} ***")

        # Method 2: ARP scan
        arp_entries = scan_arp()
        for entry in arp_entries:
            log(f"[ARP] {entry}")

        # Method 3: Ping sweep every 5 iterations
        if iteration % 5 == 0:
            active_ips = ping_sweep()
            for ip in active_ips:
                if ip not in known_ips:
                    log(f"[PING] New device: {ip}")
                    known_ips.add(ip)
                    # Quick check if it's FP2
                    if check_fp2_http(ip):
                        log(f"*** FP2 FOUND at {ip} ***")

        time.sleep(3)


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        log("\nMonitor stopped.")
        sys.exit(0)
