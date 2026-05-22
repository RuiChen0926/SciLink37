import json
import sys
from http.client import HTTPConnection
from urllib.parse import urlparse

inbox_path = sys.argv[1]
api = sys.argv[2]

with open(inbox_path, "r") as f:
    inbox_content = f.read()

system_prompt = "你是计算物理学研究者Rui的私人秘书。接收中英混杂的碎片输入，严格输出三段式：\n\n## 初始场\n[当前阶段、停在哪里、最活跃问题]\n\n## 边界场\n[今天范围、不做什么、约束条件]\n\n## 给 Claude 的第一条指令\n[一句话，直接可发给Claude的指令]\n\n碎片不足则说：碎片不足，请补充今天想推进的方向。"

payload = {
    "model": "mlx-community/gemma-4-e2b-it-4bit",
    "messages": [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": "以下是我最近记录的研究碎片，请整理：\n\n" + inbox_content}
    ],
    "temperature": 0.3,
    "max_tokens": 1200
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
