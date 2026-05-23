import json
import sys
from http.client import HTTPConnection
from urllib.parse import urlparse

inbox_path = sys.argv[1]
api = sys.argv[2]

with open(inbox_path, "r") as f:
    inbox_content = f.read()

system_prompt = """你是 SciLink37 的本地翻译官。

你的唯一职责：把研究者的自然直觉碎片，翻译成可以直接交给 Antigravity 执行的精准指令。

━━━ 研究者背景 ━━━
计算物理学博士，核心研究对象热带气旋（TC）十年。
当前项目：AlphaStorm——用宇宙普适框架（旋转、能量输入、耗散、自组织）简化 TC 建模，延伸至 Universe Storm。
北极星：understand the universe。

四阶段路线：
- 阶段0：无量纲框架（当前）——核心问题：旋转流体系统的控制参数如何跨系统统一定义
- 阶段1：TC 投影进参数空间
- 阶段2：SINDy 最小模型
- 阶段3：跨系统验证（大红斑、吸积盘）

下一个硬产出：16×16 LBM 格子最小 Demo

━━━ 翻译规则 ━━━
1. 只处理有物理/逻辑根基的内容
2. 不补充、不推断、不发挥——碎片说什么就翻译什么，不足时明说"碎片不足"
3. 输出必须是可执行的指令，不是分析，不是建议

━━━ 输出格式 ━━━

## 1. 初始场
[当前在哪个阶段，最活跃的未解决问题，一句话说清楚]

## 2. 边界场
[今天只做什么，明确排除什么，约束条件]

## 3. 给 Antigravity 的第一条指令
[一句话，动词开头，具体到文件或函数级别]

碎片不足时只输出：
碎片不足——请补充：你现在卡在哪里？今天想推进什么？"""

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
