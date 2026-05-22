#!/bin/bash

echo "🛑 关闭 SciLink37..."

pkill -f "floater.py" 2>/dev/null && echo "  · floater.py 已关闭" || echo "  · floater.py 未运行"

echo "✅ SciLink37 已关闭"
