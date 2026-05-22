#!/bin/bash

echo "🚀 启动 SciLink37..."

nohup ~/start_secretary.sh >/tmp/secretary.log 2>&1 &

echo "⏳ 等待本地 Gemma 服务就绪..."
for i in {1..30}; do
    if curl -s http://localhost:8080/v1/models >/dev/null 2>&1; then
        echo "✅ Gemma 服务已就绪 (${i}s)"
        break
    fi
    if [ "$i" -eq 30 ]; then
        echo "❌ Gemma 服务启动超时（30s），请检查 /tmp/secretary.log"
        exit 1
    fi
    sleep 1
done

nohup python3 /Users/rui/Projects/SciLink37/floater.py >/tmp/floater.log 2>&1 &

echo "✅ SciLink37 已启动"
