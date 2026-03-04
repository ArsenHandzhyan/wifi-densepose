#!/bin/bash
# Скрипт мониторинга — ждёт когда FP2 появится в сети
# Запуск: bash scripts/watch_fp2.sh

echo "=== Ожидаю появления Aqara FP2 в сети ==="
echo "Сканирую каждые 5 секунд..."
echo "Нажмите Ctrl+C для остановки"
echo ""

KNOWN_MAC="54:ef:44"  # Aqara/Lumi OUI prefix

while true; do
    # Quick ARP ping sweep (background, fast)
    for i in $(seq 1 254); do
        ping -c 1 -W 1 192.168.1.$i > /dev/null 2>&1 &
    done
    wait

    # Check ARP table for Aqara devices
    FOUND=$(arp -a 2>/dev/null | grep -i "$KNOWN_MAC")

    if [ -n "$FOUND" ]; then
        IP=$(echo "$FOUND" | head -1 | awk -F'[()]' '{print $2}')
        echo ""
        echo "========================================"
        echo "  FP2 НАЙДЕН! IP: $IP"
        echo "  $(date)"
        echo "========================================"
        echo ""
        echo "Проверяю порты..."
        for port in 80 443 8443 21064 5353; do
            nc -z -w1 "$IP" $port 2>/dev/null && echo "  Порт $port: ОТКРЫТ" || echo "  Порт $port: закрыт"
        done
        echo ""
        echo "FP2 в сети! Теперь можно добавить его в Home Assistant."
        echo "Откройте: http://localhost:8123 → Настройки → Устройства → Добавить интеграцию → HomeKit Device"
        exit 0
    fi

    # Also check for any NEW devices on the network
    NEW_DEVICES=$(arp -a 2>/dev/null | grep -v incomplete | grep -v "224.0.0" | grep -v "192.168.1.1)" | grep -v "192.168.1.2)" | grep -v "192.168.1.62)")
    if [ -n "$NEW_DEVICES" ]; then
        echo "[$(date +%H:%M:%S)] Новое устройство: $NEW_DEVICES"
    else
        printf "."
    fi

    sleep 5
done
