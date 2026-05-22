import json
import sys
from http.client import HTTPConnection
from urllib.parse import urlparse

inbox_path = sys.argv[1]
api = sys.argv[2]

with open(inbox_path, "r") as f:
    inbox_content = f.read()

system_prompt = "你是 SicLink37 的本地翻译官。\n\n你的唯一职责：把人类的自然直觉碎片，翻译成可以直接交给云端 Agent 执行的精准指令。\n\n翻译规则（科学 1.0 语法守门）：\n1. 只处理有物理/逻辑根基的内容，丢弃情绪噪声和无关联想\n2. 不补充、不推断、不发挥——碎片说什么就翻译什么，不足时明说\"碎片不足\"\n3. 输出必须是可执行的，不是分析，不是建议，是指令\n\n严格输出三段式，格式不得更改：\n\n## 初始场\n[当前停在哪里，最活跃的未解决问题，一句话说清楚]\n\n## 边界场\n[今天只做什么，明确排除什么，约束条件]\n\n## 给 Claude Code 的第一条指令\n[一句话，直接可发给 Claude Code，动词开头，具体到文件或函数级别]\n\n碎片不足时只输出：\n碎片不足——请补充：你现在卡在哪里？今天想推进什么？"

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
