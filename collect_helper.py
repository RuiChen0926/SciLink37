import sys
import json
from http.client import HTTPConnection
from urllib.parse import urlparse

science_path = sys.argv[1]
nature_path = sys.argv[2]
api = sys.argv[3]
model = sys.argv[4]


def _read(path):
    try:
        with open(path, "r") as f:
            return f.read().strip()
    except FileNotFoundError:
        return ""


# 合并 science.md + nature.md：科研条目和灵感条目一起送进来整理
_sections = []
science_content = _read(science_path)
if science_content:
    _sections.append("【科研】\n" + science_content)
nature_content = _read(nature_path)
if nature_content:
    _sections.append("【灵感】\n" + nature_content)
inbox_content = "\n\n".join(_sections)

if not inbox_content:
    sys.stderr.write("science.md 与 nature.md 都是空的，没有可整理的内容。\n")
    sys.exit(1)

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
    "model": model,
    "messages": [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": "以下是今天的科研笔记与灵感碎片，请按上面的格式整理：\n\n" + inbox_content}
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
