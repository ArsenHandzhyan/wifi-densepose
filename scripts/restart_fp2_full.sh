#!/bin/bash
# Полный перезапуск стека FP2 Monitoring

echo "🚀 ПЕРЕЗАПУСК СИСТЕМЫ FP2 MONITORING"
echo "======================================"
echo ""

cd /Users/arsen/Desktop/wifi-densepose

# Шаг 1: Остановка всех сервисов
echo "📡 Остановка существующих процессов..."
lsof -ti:8000 | xargs kill -9 2>/dev/null || true
lsof -ti:3000 | xargs kill -9 2>/dev/null || true
pkill -f "uvicorn v1.src.app:app" 2>/dev/null || true
pkill -f "uvicorn src.app:app" 2>/dev/null || true
pkill -f "fp2_aqara_cloud_monitor" 2>/dev/null || true
pkill -f "http.server" 2>/dev/null || true
sleep 2
echo "✅ Все процессы остановлены"
echo ""

# Шаг 2: Запуск Backend
echo "🔧 Запуск Backend API (порт 8000)..."
PYTHONPATH=/Users/arsen/Desktop/wifi-densepose/v1:$PYTHONPATH python3 -m uvicorn v1.src.app:app --host 0.0.0.0 --port 8000 > /tmp/backend.log 2>&1 &
BACKEND_PID=$!
sleep 3

if curl -sf http://127.0.0.1:8000/health/live > /dev/null 2>&1; then
    echo "✅ Backend запущен (PID: $BACKEND_PID)"
else
    echo "⚠️  Backend запускается..."
fi
echo ""

# Шаг 3: Запуск Cloud Monitor
echo "☁️  Запуск Aqara Cloud Monitor..."
python3 scripts/fp2_aqara_cloud_monitor.py > /tmp/cloud-monitor.log 2>&1 &
CLOUD_PID=$!
sleep 2

if ps -p $CLOUD_PID > /dev/null 2>&1; then
    echo "✅ Cloud Monitor запущен (PID: $CLOUD_PID)"
else
    echo "⚠️  Cloud Monitor не запустился"
fi
echo ""

# Шаг 4: Ожидание сбора данных
echo "⏳ Ожидание сбора данных (5 секунд)..."
sleep 5
echo ""

# Шаг 5: Проверка данных
echo "📊 Проверка данных FP2..."
DATA=$(curl -s http://127.0.0.1:8000/api/v1/fp2/current 2>/dev/null)

if [ -n "$DATA" ]; then
    PRESENCE=$(echo "$DATA" | python3 -c "import sys,json; d=json.load(sys.stdin); print('✅ Есть' if d['metadata']['raw_attributes'].get('presence') else '⚪ Нет')" 2>/dev/null || echo "?")
    MOVEMENT=$(echo "$DATA" | python3 -c "import sys,json; d=json.load(sys.stdin); code=d['metadata']['raw_attributes'].get('movement_event', '?'); codes={0:'No event',1:'Static',2:'Micro',3:'Significant',7:'Moving'}; print(f'{code} ({codes.get(code, \"Unknown\")})')" 2>/dev/null || echo "?")
    TARGETS=$(echo "$DATA" | python3 -c "import sys,json; d=json.load(sys.stdin); print(len(d.get('persons', [])))" 2>/dev/null || echo "?")
    
    echo "✅ Данные получены:"
    echo "   - Присутствие: $PRESENCE"
    echo "   - Движение: Code $MOVEMENT"
    echo "   - Целей: $TARGETS"
else
    echo "⚠️  Данные ещё не поступили"
fi
echo ""

# Шаг 6: Запуск UI Server
echo "🎨 Запуск UI Server (порт 3000)..."
cd /Users/arsen/Desktop/wifi-densepose/ui
python3 -m http.server 3000 > /tmp/ui.log 2>&1 &
UI_PID=$!
sleep 2

if curl -sf http://127.0.0.1:3000 > /dev/null 2>&1; then
    echo "✅ UI Server запущен (PID: $UI_PID)"
else
    echo "⚠️  UI Server запускается..."
fi
echo ""

# Финальная информация
echo "======================================"
echo "✅ ВСЕ СЕРВИСЫ ЗАПУЩЕНЫ!"
echo "======================================"
echo ""
echo "🌐 ОТКРОЙТЕ В БРАУЗЕРЕ:"
echo "   http://127.0.0.1:3000"
echo ""
echo "📊 ТЕЛЕМЕТРИЯ:"
echo "   Backend: http://127.0.0.1:8000/api/v1/fp2/current"
echo ""
echo "⌨️  PID ПРОЦЕССОВ:"
echo "   Backend: $BACKEND_PID"
echo "   Cloud: $CLOUD_PID"
echo "   UI: $UI_PID"
echo ""
echo "📝 ЛОГИ:"
echo "   Backend: /tmp/backend.log"
echo "   Cloud: /tmp/cloud-monitor.log"
echo "   UI: /tmp/ui.log"
echo ""
echo "⌨️  ДЛЯ ОСТАНОВКИ:"
echo "   killall -9 python3"
echo "   или"
echo "   kill $BACKEND_PID $CLOUD_PID $UI_PID"
echo ""
