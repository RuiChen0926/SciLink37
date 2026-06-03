#!/bin/bash

source /Users/rui/Projects/SciLink37/config.sh
case "${MODEL:-$MODEL_DEFAULT_COLLECT}" in
  26b) SELECTED_MODEL="$MODEL_26B" ;;
  *)   SELECTED_MODEL="$MODEL_2B" ;;
esac

INBOX_DIR=/Users/rui/Projects/SciLink37/inbox
TODAY="${1:-$(date "+%Y-%m-%d")}"
DAY_DIR="$INBOX_DIR/$TODAY"
SCIENCE="$DAY_DIR/science.md"
NATURE="$DAY_DIR/nature.md"
INSPIRATION="$DAY_DIR/inspiration.md"
INSPIRATION_REL="inbox/$TODAY/inspiration.md"
API="http://localhost:8080/v1/chat/completions"
HEALTH="http://localhost:8080/v1/models"
STARTED_BY_US=0
DIVIDER="─────────────────────────────"

# collect 是 pipeline 末端，用完即释放：无论是否本脚本启的，结束都关掉 Gemma
cleanup() {
  pkill -f "mlx_lm.server" 2>/dev/null
}
trap cleanup EXIT INT TERM

# science 与 nature 至少要有一个非空，否则没东西可整理
if { [ ! -f "$SCIENCE" ] || [ ! -s "$SCIENCE" ]; } && { [ ! -f "$NATURE" ] || [ ! -s "$NATURE" ]; }; then
  echo "❌ 今天的 science / nature 都是空的，先用 sort.sh 分类。"
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

AVAILABLE=$(curl -s "$HEALTH" | python3 -c "import sys, json; print('\n'.join(m['id'] for m in json.load(sys.stdin)['data']))" 2>/dev/null)
if ! echo "$AVAILABLE" | grep -Fxq "$SELECTED_MODEL"; then
  echo "❌ 本地未缓存模型 $SELECTED_MODEL"
  echo "   服务器可用模型："
  echo "$AVAILABLE" | sed 's/^/     /'
  exit 1
fi

RESPONSE=$(python3 /Users/rui/Projects/SciLink37/collect_helper.py "$SCIENCE" "$NATURE" "$API" "$SELECTED_MODEL")

if [ -z "$RESPONSE" ]; then
  echo "❌ 本地 AI 没有响应。"
  exit 1
fi

echo "$RESPONSE" > "$INSPIRATION"

# 终端显示：套上分隔框
echo ""
echo "$DIVIDER"
echo "  $TODAY  SciLink37 Inspiration"
echo "$DIVIDER"
echo ""
echo "$RESPONSE"
echo ""
echo "$DIVIDER"
echo " ✅ 已写入 $INSPIRATION_REL"
echo "$DIVIDER"
