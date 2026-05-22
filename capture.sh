#!/bin/bash

INBOX=/Users/rui/Projects/SciLink37/inbox.md
touch "$INBOX"

EDITOR_CMD="${EDITOR:-nano}"

TMPFILE=$(mktemp -t scilink_capture.XXXXXX.md)
trap 'rm -f "$TMPFILE"' EXIT

cat > "$TMPFILE" <<'EOF'
# 在这里写下你的研究碎片（保存退出后自动追加到 inbox.md）
# 以 # 开头的行会被忽略

EOF

echo "📝 正在用 $EDITOR_CMD 打开编辑器，写完保存退出即可..."
"$EDITOR_CMD" "$TMPFILE"

INPUT=$(grep -v '^#' "$TMPFILE" | sed -e 's/[[:space:]]*$//' )
INPUT=$(printf '%s' "$INPUT" | awk 'NF {p=1} p')

if [ -z "$INPUT" ]; then
  echo "❌ 没有输入，已取消。"
  exit 0
fi

TIMESTAMP=$(date "+%Y-%m-%d %H:%M")
{
  echo ""
  echo "[$TIMESTAMP]"
  echo "$INPUT"
} >> "$INBOX"

echo "✅ 已记录到 inbox。"
