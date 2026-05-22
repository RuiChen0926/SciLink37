#!/bin/bash

INBOX=/Users/rui/Projects/SciLink37/inbox.md
API="http://localhost:8080/v1/chat/completions"

if [ ! -f "$INBOX" ] || [ ! -s "$INBOX" ]; then
  echo "❌ inbox 是空的，先用 capture.sh 记录一些想法。"
  exit 0
fi

echo "🔄 正在整理 inbox..."
echo ""

RESPONSE=$(python3 /Users/rui/Projects/SciLink37/digest_helper.py "$INBOX" "$API")

if [ -z "$RESPONSE" ]; then
  echo "❌ 本地 AI 没有响应，确认服务器是否启动。"
  exit 1
fi

echo "$RESPONSE"
echo ""

read -p "🗑️  是否清空 inbox？(y/n): " CLEAR
if [ "$CLEAR" = "y" ]; then
  > "$INBOX"
  echo "✅ inbox 已清空。"
fi
