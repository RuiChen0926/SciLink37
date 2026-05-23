#!/bin/bash

INBOX_DIR=/Users/rui/Projects/SciLink37/inbox
TODAY=$(date "+%Y-%m-%d")
DAY_DIR="$INBOX_DIR/$TODAY"
INBOX="$DAY_DIR/nature.md"
INBOX_REL="inbox/$TODAY/nature.md"
COLLECT="$DAY_DIR/collect.md"
COLLECT_REL="inbox/$TODAY/collect.md"
API="http://localhost:8080/v1/chat/completions"
HEALTH="http://localhost:8080/v1/models"
STARTED_BY_US=0
DIVIDER="─────────────────────────────"

# 退出时若是本脚本启的 Gemma，把它关掉；外部已存在的实例不动
cleanup() {
  if [ "$STARTED_BY_US" -eq 1 ]; then
    pkill -f "mlx_lm.server" 2>/dev/null
  fi
}
trap cleanup EXIT INT TERM

if [ ! -f "$INBOX" ] || [ ! -s "$INBOX" ]; then
  echo "❌ 今天的 nature $INBOX_REL 是空的，先用 sort.sh 分类。"
  exit 0
fi

echo "🔄 整理灵感 $TODAY ..."

# Gemma 没在跑就静默拉起来；最多等 60s
if ! curl -s "$HEALTH" >/dev/null 2>&1; then
  STARTED_BY_US=1
  nohup ~/start_secretary.sh >/tmp/secretary.log 2>&1 &
  for i in {1..60}; do
    if curl -s "$HEALTH" >/dev/null 2>&1; then
      break
    fi
    if [ "$i" -eq 60 ]; then
      echo "❌ Gemma 服务启动超时 [60s]，请检查 /tmp/secretary.log"
      exit 1
    fi
    sleep 1
  done
fi

RESPONSE=$(python3 /Users/rui/Projects/SciLink37/collect_helper.py "$INBOX" "$API")

if [ -z "$RESPONSE" ]; then
  echo "❌ 本地 AI 没有响应。"
  exit 1
fi

echo "$RESPONSE" > "$COLLECT"

# 终端显示：套上分隔框
echo ""
echo "$DIVIDER"
echo "  $TODAY  SciLink37 Collect"
echo "$DIVIDER"
echo ""
echo "$RESPONSE"
echo ""
echo "$DIVIDER"
echo " ✅ 已写入 $COLLECT_REL"
echo "$DIVIDER"
