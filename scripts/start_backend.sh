#!/bin/bash
# Запуск backend сервера FP2 Monitor

echo "🚀 Запуск backend сервера..."
echo ""

cd /Users/arsen/Desktop/wifi-densepose

# Check if venv is activated
if [ -z "$VIRTUAL_ENV" ]; then
    echo "⚠️  Virtualenv не активирован. Активирую..."
    source venv/bin/activate
fi

# Run the server
python3 v1/src/main.py
