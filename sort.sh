#!/bin/bash

source /Users/rui/Projects/SciLink37/config.sh
case "${MODEL:-2b}" in
  26b) SELECTED_MODEL="$MODEL_26B" ;;
  *)   SELECTED_MODEL="$MODEL_2B" ;;
esac

INBOX_DIR=/Users/rui/Projects/SciLink37/inbox
TODAY="${1:-$(date "+%Y-%m-%d")}"
DAY_DIR="$INBOX_DIR/$TODAY"
INBOX="$DAY_DIR/raw.md"
SCIENCE="$DAY_DIR/science.md"
IDEAS="$DAY_DIR/nature.md"
INBOX_REL="inbox/$TODAY/raw.md"
API="http://localhost:8080/v1/chat/completions"
HEALTH="http://localhost:8080/v1/models"
STARTED_BY_US=0

# 退出时若是本脚本启的 Gemma，把它关掉；外部已存在的实例不动
cleanup() {
  if [ "$STARTED_BY_US" -eq 1 ]; then
    pkill -f "mlx_lm.server" 2>/dev/null
  fi
}
trap cleanup EXIT INT TERM

if [ ! -f "$INBOX" ] || [ ! -s "$INBOX" ]; then
  echo "❌ 今天的 inbox $INBOX_REL 是空的，先用 capture.sh 或悬浮框记录一些想法。"
  exit 0
fi

echo "🔄 分类中 $TODAY ..."

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

if ! python3 /Users/rui/Projects/SciLink37/sort_helper.py "$INBOX" "$API" "$SCIENCE" "$IDEAS" "$SELECTED_MODEL"; then
  echo "❌ 分类失败，未写入任何文件。"
  exit 1
fi
