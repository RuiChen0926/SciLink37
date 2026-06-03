#!/bin/bash

source /Users/rui/Projects/SciLink37/config.sh
case "${MODEL:-2b}" in
  26b) SELECTED_MODEL="$MODEL_26B" ;;
  *)   SELECTED_MODEL="$MODEL_2B" ;;
esac

INBOX_DIR=/Users/rui/Projects/SciLink37/inbox
TODAY="${1:-$(date "+%Y-%m-%d")}"
DAY_DIR="$INBOX_DIR/$TODAY"
SCIENCE="$DAY_DIR/science.md"
RAW="$DAY_DIR/raw.md"
# 优先用 sort.sh 过滤后的 science 子集；没有就回退到原始 raw
if [ -f "$SCIENCE" ] && [ -s "$SCIENCE" ]; then
  INBOX="$SCIENCE"
  INBOX_REL="inbox/$TODAY/science.md"
else
  INBOX="$RAW"
  INBOX_REL="inbox/$TODAY/raw.md"
fi
DIGEST="$DAY_DIR/digest.md"
DIGEST_REL="inbox/$TODAY/digest.md"
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
  echo "❌ 今天的 inbox $INBOX_REL 是空的，先用 capture.sh 或悬浮框记录一些想法。"
  exit 0
fi

echo "🔄 整理中 $TODAY ..."

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

RESPONSE=$(python3 /Users/rui/Projects/SciLink37/digest_helper.py "$INBOX" "$API" "$SELECTED_MODEL")

if [ -z "$RESPONSE" ]; then
  echo "❌ 本地 AI 没有响应。"
  exit 1
fi

# 写入文件：原样保留 prompt 自带的 ## 1./2./3. 标题
echo "$RESPONSE" > "$DIGEST"

# 终端显示：去掉 ## 前缀，套上分隔框
echo ""
echo "$DIVIDER"
echo "  $TODAY  SciLink37 Digest"
echo "$DIVIDER"
echo ""
echo "$RESPONSE" | sed -E 's/^##[[:space:]]*//'
echo ""
echo "$DIVIDER"
echo " ✅ 已写入 $DIGEST_REL"
echo "$DIVIDER"
