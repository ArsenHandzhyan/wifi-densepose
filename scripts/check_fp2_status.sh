#!/bin/bash
# Проверка статуса всех сервисов FP2

echo "📊 СТАТУС СЕРВИСОВ FP2"
echo "="*60
echo ""

# Backend
echo "🔧 Backend (порт 8000):"
if curl -sf http://127.0.0.1:8000/health/live > /dev/null 2>&1; then
    echo "   ✅ Работает"
    echo "   URL: http://127.0.0.1:8000"
    echo "   API: http://127.0.0.1:8000/api/v1/fp2/current"
else
    echo "   ⚠️  Не отвечает"
fi
echo ""

# Cloud Monitor
echo "☁️  Aqara Cloud Monitor:"
if ps aux | grep fp2_aqara_cloud_monitor | grep -v grep > /dev/null; then
    echo "   ✅ Работает"
    echo "   Лог: /tmp/cloud-monitor.log"
else
    echo "   ⚠️  Не запущен"
fi
echo ""

# UI Server
echo "🎨 UI Server (порт 3000):"
if curl -sf http://127.0.0.1:3000 > /dev/null 2>&1; then
    echo "   ✅ Работает"
    echo "   URL: http://127.0.0.1:3000"
else
    echo "   ⚠️  Не отвечает"
fi
echo ""

# Получение данных FP2
echo "📡 Данные FP2:"
DATA=$(curl -s http://127.0.0.1:8000/api/v1/fp2/current 2>/dev/null)
if [ -n "$DATA" ]; then
    PRESENCE=$(echo "$DATA" | python3 -c "import sys,json; d=json.load(sys.stdin); print('✅ Есть' if d['metadata']['raw_attributes'].get('presence') else '⚪ Нет')" 2>/dev/null || echo "?")
    MOVEMENT=$(echo "$DATA" | python3 -c "import sys,json; d=json.load(sys.stdin); code=d['metadata']['raw_attributes'].get('movement_event', '?'); codes={0:'No event',1:'Static',2:'Micro',3:'Significant',7:'Moving'}; print(f'{code} ({codes.get(code, \"Unknown\")})')" 2>/dev/null || echo "?")
    TARGETS=$(echo "$DATA" | python3 -c "import sys,json; d=json.load(sys.stdin); print(len(d.get('persons', [])))" 2>/dev/null || echo "?")
    
    echo "   Присутствие: $PRESENCE"
    echo "   Движение: Code $MOVEMENT"
    echo "   Целей: $TARGETS"
else
    echo "   ⚠️  Данные недоступны"
fi
echo ""

echo "="*60
echo ""
echo "🌐 ОТКРОЙТЕ В БРАУЗЕРЕ:"
echo "   http://127.0.0.1:3000"
echo ""
echo "⌨️  КОМАНДЫ:"
echo "   Остановить всё: killall -9 python3"
echo "   Посмотреть логи: tail -f /tmp/backend.log"
echo "                    tail -f /tmp/cloud-monitor.log"
echo "                    tail -f /tmp/ui.log"
echo ""
