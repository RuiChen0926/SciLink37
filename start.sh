#!/bin/bash

echo "🚀 启动 SciLink37..."

nohup python3 /Users/rui/Projects/SciLink37/floater.py >/tmp/floater.log 2>&1 &

echo "✅ SciLink37 已启动（floater 常驻；Gemma 在 digest 时按需启动）"
