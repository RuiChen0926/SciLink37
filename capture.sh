#!/bin/bash

INBOX=/Users/rui/Projects/SciLink37/inbox.md
touch "$INBOX"

echo "📝 说出你的想法（输入完按 Enter，然后 Ctrl+D 结束）："
INPUT=$(cat)

if [ -z "$INPUT" ]; then
  echo "❌ 没有输入，已取消。"
  exit 0
fi

TIMESTAMP=$(date "+%Y-%m-%d %H:%M")
echo "" >> "$INBOX"
echo "[$TIMESTAMP]" >> "$INBOX"
echo "$INPUT" >> "$INBOX"

echo "✅ 已记录到 inbox。"
