#!/bin/bash

echo "🛑 关闭 SciLink37..."

pkill -f "floater.py" 2>/dev/null && echo "  · floater.py 已关闭" || echo "  · floater.py 未运行"

pkill -f "mlx_lm.server" 2>/dev/null && echo "  · mlx_lm.server 已关闭" || echo "  · mlx_lm.server 未运行"

echo "✅ SciLink37 已关闭"
