#!/bin/bash

PLIST=~/Library/LaunchAgents/com.scilink37.floater.plist

echo "🧨 彻底禁用 floater..."

if [ -f "$PLIST" ]; then
  launchctl unload "$PLIST" 2>/dev/null && echo "  · LaunchAgent 已 unload" || echo "  · LaunchAgent 未加载"
  rm -f "$PLIST" && echo "  · plist 已删除：$PLIST"
else
  echo "  · plist 不存在，跳过"
fi

pkill -f "floater.py" 2>/dev/null && echo "  · floater.py 已 kill" || echo "  · floater.py 未运行"

echo "✅ floater 已彻底禁用（重启系统也不会再起来）"
