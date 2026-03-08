#!/bin/bash
# Автоматический запуск полного стека FP2 Monitor

echo "🚀 АВТОМАТИЧЕСКИЙ ЗАПУСК FP2 MONITOR"
echo "======================================"
echo ""

cd /Users/arsen/Desktop/wifi-densepose

# Шаг 1: Очистка порта 8000
echo "📡 Освобождение порта 8000..."
lsof -ti:8000 | xargs kill -9 2>/dev/null || true
sleep 1

# Шаг 2: Запуск backend
echo "🔧 Запуск backend сервера..."
PYTHONPATH=/Users/arsen/Desktop/wifi-densepose/v1:$PYTHONPATH python3 -m uvicorn v1.src.app:app --host 0.0.0.0 --port 8000 --reload > /tmp/backend.log 2>&1 &
BACKEND_PID=$!
sleep 3

# Проверка backend
if curl -sf http://127.0.0.1:8000/health/live >/dev/null 2>&1; then
    echo "✅ Backend запущен (PID: $BACKEND_PID)"
else
    echo "⚠️  Backend запускается..."
fi

# Шаг 3: Запуск cloud monitor
echo "☁️  Запуск Aqara Cloud Monitor..."
python3 scripts/fp2_aqara_cloud_monitor.py > /tmp/cloud-monitor.log 2>&1 &
CLOUD_PID=$!
sleep 2

# Проверка cloud monitor
if ps -p $CLOUD_PID > /dev/null 2>&1; then
    echo "✅ Cloud Monitor запущен (PID: $CLOUD_PID)"
else
    echo "❌ Cloud Monitor не запустился"
fi

# Шаг 4: Пауза для сбора данных
echo ""
echo "⏳ Ожидание сбора данных (5 секунд)..."
sleep 5

# Шаг 5: Проверка данных
echo ""
echo "📊 Проверка данных FP2..."
DATA=$(curl -s http://127.0.0.1:8000/api/v1/fp2/current 2>/dev/null)

if [ -n "$DATA" ]; then
    PRESENCE=$(echo "$DATA" | python3 -c "import sys,json; d=json.load(sys.stdin); print('Есть' if d['metadata']['raw_attributes'].get('presence') else 'Нет')" 2>/dev/null || echo "?")
    MOVEMENT=$(echo "$DATA" | python3 -c "import sys,json; d=json.load(sys.stdin); print(d['metadata']['raw_attributes'].get('movement_event', '?'))" 2>/dev/null || echo "?")
    TARGETS=$(echo "$DATA" | python3 -c "import sys,json; d=json.load(sys.stdin); print(len(d.get('persons', [])))" 2>/dev/null || echo "?")
    
    echo "✅ Данные получены:"
    echo "   - Присутствие: $PRESENCE"
    echo "   - Движение: Code $MOVEMENT"
    echo "   - Целей: $TARGETS"
else
    echo "⚠️  Данные ещё не поступили"
fi

# Шаг 6: Запуск монитора
echo ""
echo "🔍 Запуск монитора всех endpoint'ов..."
echo "======================================"
echo ""
echo "Нажмите Ctrl+C чтобы остановить монитор"
echo ""

python3 scripts/fp2_monitor_simple.py --interval 1.5

# Cleanup function
cleanup() {
    echo ""
    echo "⏹️  Остановка сервисов..."
    kill $BACKEND_PID 2>/dev/null || true
    kill $CLOUD_PID 2>/dev/null || true
    echo "✅ Все сервисы остановлены"
}

trap cleanup EXIT
