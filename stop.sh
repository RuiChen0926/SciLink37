#!/bin/bash

echo "🛑 关闭 Gemma 服务器..."

pkill -f "mlx_lm.server" 2>/dev/null && echo "  · mlx_lm.server 已关闭" || echo "  · mlx_lm.server 未运行"

echo "✅ Gemma 已关闭（floater 由 LaunchAgent 管理，未受影响）"
