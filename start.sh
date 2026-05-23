#!/bin/bash

echo "🚀 启动 Gemma 服务器..."

if curl -s http://localhost:8080/v1/models >/dev/null 2>&1; then
  echo "✅ Gemma 已在运行（http://localhost:8080）"
  exit 0
fi

nohup ~/start_secretary.sh >/tmp/secretary.log 2>&1 &

echo "⏳ 等待 Gemma 就绪（最多 60s）..."
for i in {1..60}; do
  if curl -s http://localhost:8080/v1/models >/dev/null 2>&1; then
    echo "✅ Gemma 已就绪（http://localhost:8080）"
    exit 0
  fi
  sleep 1
done

echo "❌ Gemma 启动超时，请检查 /tmp/secretary.log"
exit 1
