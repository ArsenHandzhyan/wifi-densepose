#!/usr/bin/env bash
set -euo pipefail

# Usage:
#   ./scripts/migrate_ha_to_linux.sh user@host [ssh_port]
#
# What it does:
# 1) Takes latest local HA backup from backups/homeassistant/config-*
# 2) Creates a compressed archive
# 3) Uploads to remote Linux host over SSH/SCP
# 4) Installs Docker (apt-based distro) if needed
# 5) Deploys Home Assistant Container with host networking
# 6) Restores /config and restarts HA
#
# Requirements:
# - SSH access to remote host
# - sudo privileges on remote host
# - apt-based Linux target (Ubuntu/Debian)

if [[ $# -lt 1 ]]; then
  echo "Usage: $0 user@host [ssh_port]"
  exit 1
fi

TARGET="$1"
SSH_PORT="${2:-22}"
ROOT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
BACKUP_DIR="$ROOT_DIR/backups/homeassistant"

LATEST_BACKUP="$(ls -1dt "$BACKUP_DIR"/config-* 2>/dev/null | head -n 1 || true)"
if [[ -z "${LATEST_BACKUP}" ]]; then
  echo "No HA backup found in $BACKUP_DIR"
  echo "Create one first:"
  echo "  docker cp wifi-densepose-ha:/config backups/homeassistant/config-\$(date +%Y%m%d-%H%M%S)"
  exit 1
fi

TMP_TAR="$ROOT_DIR/backups/homeassistant/ha-config-latest.tar.gz"
echo "Using backup: $LATEST_BACKUP"
tar -C "$LATEST_BACKUP" -czf "$TMP_TAR" .
echo "Archive created: $TMP_TAR"

echo "Uploading archive to $TARGET ..."
scp -P "$SSH_PORT" "$TMP_TAR" "$TARGET:/tmp/ha-config-latest.tar.gz"

echo "Deploying Home Assistant on remote host ..."
ssh -p "$SSH_PORT" "$TARGET" 'bash -s' <<'REMOTE'
set -euo pipefail

if ! command -v docker >/dev/null 2>&1; then
  sudo apt-get update
  sudo apt-get install -y docker.io
  sudo systemctl enable --now docker
fi

sudo mkdir -p /opt/homeassistant/config
sudo rm -rf /opt/homeassistant/config/*
sudo tar -xzf /tmp/ha-config-latest.tar.gz -C /opt/homeassistant/config

if sudo docker ps -a --format "{{.Names}}" | grep -q "^homeassistant$"; then
  sudo docker rm -f homeassistant
fi

sudo docker run -d \
  --name homeassistant \
  --restart=unless-stopped \
  --network=host \
  -e TZ=Europe/Moscow \
  -v /opt/homeassistant/config:/config \
  ghcr.io/home-assistant/home-assistant:stable

echo "Home Assistant deployed."
echo "Open: http://$(hostname -I | awk "{print \$1}"):8123"
REMOTE

echo "Done."
echo "Next:"
echo "1) Open remote HA UI and verify login."
echo "2) Add HomeKit Device and pair FP2."
echo "3) Update local .env HA_URL and HA_TOKEN to remote HA."
