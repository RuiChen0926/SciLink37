import sys
import json
from http.client import HTTPConnection
from urllib.parse import urlparse

inbox_path = sys.argv[1]
api = sys.argv[2]

with open(inbox_path, "r") as f:
    inbox_content = f.read()

system_prompt = """你是一个灵感整理助手。只做整理，不做评价，不做建议。

读取以下灵感碎片，完成两件事：

1. 分组归档：把条目按主题自然分组，每组给一个简短标题

2. 今日总结：用 2-3 句话概括今天灵感的整体方向和主题分布，不做评价，只描述"今天记录了什么"

输出格式：

## 分组

### 标题A
1. [2026-05-23 09:14]
条目内容...

2. [2026-05-23 10:30]
条目内容...

### 标题B
1. [2026-05-23 11:00]
条目内容...

## 今日总结
..."""

payload = {
    "model": "mlx-community/gemma-4-e2b-it-4bit",
    "messages": [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": "以下是今天的灵感碎片，请按上面的格式整理：\n\n" + inbox_content}
    ],
    "temperature": 0.3,
    "max_tokens": 4000
}

data = json.dumps(payload, ensure_ascii=False).encode("utf-8")

parsed = urlparse(api)
conn = HTTPConnection(parsed.hostname, parsed.port or 80, timeout=300)
conn.request(
    "POST",
    parsed.path,
    body=data,
    headers={
        "Content-Type": "application/json; charset=utf-8",
        "Content-Length": str(len(data)),
    },
)

resp = conn.getresponse()
body = resp.read().decode("utf-8")

if resp.status != 200:
    sys.stderr.write(f"本地 AI 服务器返回 {resp.status}: {body[:500]}\n")
    sys.exit(1)

result = json.loads(body)
choice = result["choices"][0]["message"]
output = (choice.get("content") or choice.get("reasoning") or "").strip()

if not output:
    sys.stderr.write("本地 AI 返回空响应。\n")
    sys.exit(1)

print(output)
