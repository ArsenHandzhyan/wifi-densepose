#!/bin/bash
# Запуск монитора всех endpoint'ов FP2

echo "🚀 Запуск монитора всех endpoint'ов FP2..."
echo ""
cd /Users/arsen/Desktop/wifi-densepose
python3 scripts/fp2_monitor_ru.py --interval 1.5
