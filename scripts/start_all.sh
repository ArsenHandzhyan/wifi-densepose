#!/bin/bash
# Автоматический запуск всей системы FP2 Monitoring

echo "🚀 ЗАПУСК СИСТЕМЫ FP2 MONITORING"
echo "================================"
echo ""

cd /Users/arsen/Desktop/wifi-densepose

# Очистка
echo "📡 Остановка старых процессов..."
lsof -ti:8000 | xargs kill -9 2>/dev/null || true
lsof -ti:3000 | xargs kill -9 2>/dev/null || true
pkill -f fp2_aqara_cloud_monitor 2>/dev/null || true
echo "✅ Остановлено"
echo ""

# Backend
echo "🔧 Запуск Backend (порт 8000)..."
nohup python3 -m uvicorn v1.src.app:app --host 0.0.0.0 --port 8000 > /tmp/backend.log 2>&1 &
echo "✅ Backend запущен"
sleep 3

# Cloud Monitor
echo "☁️  Запуск Cloud Monitor..."
nohup python3 scripts/fp2_aqara_cloud_monitor.py > /tmp/cloud-monitor.log 2>&1 &
echo "✅ Cloud Monitor запущен"
sleep 2

# UI
echo "🎨 Запуск UI Server (порт 3000)..."
cd ui
nohup python3 -m http.server 3000 > /tmp/ui.log 2>&1 &
echo "✅ UI Server запущен"
sleep 2

# Проверка
echo ""
echo "📊 ПРОВЕРКА..."
echo ""

if curl -sf http://127.0.0.1:8000/health/live > /dev/null 2>&1; then
    echo "✅ Backend: РАБОТАЕТ"
else
    echo "⚠️  Backend: Загружается..."
fi

if ps aux | grep fp2_aqara_cloud_monitor | grep -v grep > /dev/null; then
    echo "✅ Cloud Monitor: РАБОТАЕТ"
else
    echo "⚠️  Cloud Monitor: Не запущен"
fi

if curl -sf http://127.0.0.1:3000 > /dev/null 2>&1; then
    echo "✅ UI Server: РАБОТАЕТ"
else
    echo "⚠️  UI Server: Загружается..."
fi

echo ""
echo "================================"
echo "✅ ВСЁ ЗАПУЩЕНО!"
echo "================================"
echo ""
echo "🌐 ОТКРОЙТЕ В БРАУЗЕРЕ:"
echo "   http://127.0.0.1:3000"
echo ""
echo "📝 ЛОГИ:"
echo "   tail -f /tmp/backend.log"
echo "   tail -f /tmp/cloud-monitor.log"
echo "   tail -f /tmp/ui.log"
echo ""
echo "⌨️  ДЛЯ ОСТАНОВКИ:"
echo "   killall -9 python3"
echo ""
