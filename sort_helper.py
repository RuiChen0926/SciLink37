import json
import os
import re
import sys
from http.client import HTTPConnection
from urllib.parse import urlparse

inbox_path = sys.argv[1]
api = sys.argv[2]
science_path = sys.argv[3]
nature_path = sys.argv[4]
model = sys.argv[5]

with open(inbox_path, "r") as f:
    inbox_content = f.read()

TIMESTAMP_RE = re.compile(r"^\s*(\[\d{4}-\d{2}-\d{2} \d{2}:\d{2}\])\s*")

BATCH_SIZE = 5


def parse_raw_entries(content):
    """raw.md → [(timestamp, full_entry_text), ...]，按 [20...] 行切分。"""
    entries = []
    current_ts = None
    current_lines = []
    for line in content.splitlines(keepends=True):
        m = TIMESTAMP_RE.match(line)
        if m and line.lstrip().startswith("[20"):
            if current_ts is not None:
                entries.append((current_ts, "".join(current_lines).rstrip()))
            current_ts = m.group(1)
            current_lines = [line]
        elif current_ts is not None:
            current_lines.append(line)
    if current_ts is not None:
        entries.append((current_ts, "".join(current_lines).rstrip()))
    return entries


def first_body_char(entry_text):
    """条目正文（去掉时间戳那一行）的第一个非空字符。"""
    parts = entry_text.split("\n", 1)
    body = (parts[1] if len(parts) > 1 else "").lstrip()
    return body[0] if body else ""


def with_tag(entry_text, tag):
    """在时间戳后插入分类 tag，吃掉原 ! / ? 前缀。"""
    parts = entry_text.split("\n", 1)
    if len(parts) < 2:
        return entry_text
    ts_line = parts[0]
    body = parts[1].lstrip()
    if body and body[0] in "!?":
        body = body[1:].lstrip()
    return f"{ts_line}\n{tag} {body}"


# 第 1 步：! / ? 走快捷通道，强制归入 science，不打扰 Gemma
raw_entries = parse_raw_entries(inbox_content)
forced_science = []
forced_ts = set()
to_gemma_texts = []
for ts, text in raw_entries:
    ch = first_body_char(text)
    if ch == "!":
        forced_science.append(with_tag(text, "[直觉]"))
        forced_ts.add(ts)
    elif ch == "?":
        forced_science.append(with_tag(text, "[卡点]"))
        forced_ts.add(ts)
    else:
        to_gemma_texts.append(text)

science_entries = list(forced_science)
nature_entries = []
noise_entries = []

# 第 2 步：剩下的交给 Gemma 三分类（分批，避免单次 thinking 撑爆 max_tokens）
if to_gemma_texts:
    system_prompt = """你是一个分类器。研究者背景：计算物理博士，做 AlphaStorm 项目，研究热带气旋（TC）和宇宙普适框架（旋转、耗散、自组织）。

把每一条碎片分为三类：
- science：与 TC、AlphaStorm、无量纲框架、Universe Storm、物理直觉、数值方法、Alpha 系列方法论直接相关；
  也包括 AGI / OOD / 因果推理 / 对称性 / 守恒律 / 涌现自由度 等宇宙普适框架的认识论支柱
- nature：外部信息、灵感、泛泛观察。硬规则：以 [链接] 开头的条目一律归 nature，无论工具与研究相关性多强
- noise：输入错误、测试内容、情绪碎片、无意义内容；也包括对本系统 / 工具的吐槽 / 自嘲 / meta-commentary

输出格式（这是字面示例，不是模板——直接照样输出真实的整数序号，不要写 indices 或任何占位符）：
{"science": [0, 2], "nature": [1], "noise": [3]}

上面示例的意思：若输入有 4 条碎片，第 0 条和第 2 条归 science，第 1 条归 nature，第 3 条归 noise。

直接输出 JSON，不要写任何分析过程、思考步骤或解释文字。"""

    parsed_api = urlparse(api)

    def classify_batch(batch_texts):
        previews = [f"[{i}] {' '.join(t.split())[:300]}" for i, t in enumerate(batch_texts)]
        payload = {
            "model": model,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": "以下是今天的研究碎片，请逐条分类：\n\n" + "\n".join(previews)}
            ],
            "temperature": 0.3,
            "max_tokens": 1500
        }
        data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        conn = HTTPConnection(parsed_api.hostname, parsed_api.port or 80, timeout=300)
        conn.request(
            "POST",
            parsed_api.path,
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
        raw = (choice.get("content") or choice.get("reasoning") or "").strip()
        if not raw:
            sys.stderr.write("本地 AI 返回空响应。\n")
            sys.exit(1)
        # Gemma 可能把 JSON 包在 ```json ... ``` 里，或后面跟一大段分析；用 raw_decode 只取第一个完整 JSON
        start = raw.find("{")
        if start == -1:
            sys.stderr.write(f"本地 AI 未返回可解析 JSON：\n{raw[:500]}\n")
            sys.exit(1)
        try:
            parsed_json, _ = json.JSONDecoder().raw_decode(raw[start:])
        except json.JSONDecodeError as e:
            sys.stderr.write(f"JSON 解析失败 ({e})：\n{raw[start:start + 500]}\n")
            sys.exit(1)
        return (
            parsed_json.get("science", []) or [],
            parsed_json.get("nature", []) or [],
            parsed_json.get("noise", []) or [],
        )

    for batch_start in range(0, len(to_gemma_texts), BATCH_SIZE):
        batch = to_gemma_texts[batch_start:batch_start + BATCH_SIZE]
        s_idx, n_idx, x_idx = classify_batch(batch)
        for idx in s_idx:
            if isinstance(idx, int) and 0 <= idx < len(batch):
                science_entries.append(batch[idx])
        for idx in n_idx:
            if isinstance(idx, int) and 0 <= idx < len(batch):
                nature_entries.append(batch[idx])
        for idx in x_idx:
            if isinstance(idx, int) and 0 <= idx < len(batch):
                noise_entries.append(batch[idx])


def write_entries(path, entries):
    formatted = []
    for i, e in enumerate(entries, 1):
        e = e.strip()
        m = TIMESTAMP_RE.match(e)
        if m:
            body = e[m.end():].lstrip()
            formatted.append(f"{i}. {m.group(1)}\n{body}".rstrip())
        else:
            formatted.append(f"{i}. {e}".rstrip())
    with open(path, "w") as f:
        f.write("\n\n".join(formatted))
        if formatted:
            f.write("\n")


write_entries(science_path, science_entries)
write_entries(nature_path, nature_entries)
# noise 直接丢弃，不写文件

# 验证：raw.md 里以 [20 开头的行数 vs 分类后的总条数
total_raw = len(raw_entries)
total_classified = len(science_entries) + len(nature_entries) + len(noise_entries)

if total_raw != total_classified:
    # Gemma 经常不回写时间戳，所以按内容签名匹配（去掉时间戳后的前 40 个非空白字符）
    def signature(text):
        s = TIMESTAMP_RE.sub("", text.strip(), count=1).lstrip()
        return "".join(s.split())[:40]

    # 强制条目按 ts 直接排除（一定被处理了），剩下走签名匹配
    gemma_classified = science_entries[len(forced_science):] + nature_entries + noise_entries
    remaining = [signature(e) for e in gemma_classified]
    missing = []
    for ts, text in raw_entries:
        if ts in forced_ts:
            continue
        sig = signature(text)
        if sig in remaining:
            remaining.remove(sig)
        else:
            missing.append(text)
    diff = total_raw - total_classified

    print(f"⚠️  输入 {total_raw} 条，分类 {total_classified} 条，有 {diff} 条未被处理")

    if missing:
        unclassified_path = os.path.join(os.path.dirname(inbox_path), "unclassified.md")
        with open(unclassified_path, "w") as f:
            f.write("\n\n".join(missing) + "\n")
        print(f"   未分类条目已写入 {unclassified_path}，供人工检查")
else:
    # 全分类成功：清掉旧 unclassified.md，免得历史失败的残留误导
    stale_unclassified = os.path.join(os.path.dirname(inbox_path), "unclassified.md")
    if os.path.exists(stale_unclassified):
        os.remove(stale_unclassified)
    print(f"✅ 已分类：{len(science_entries)} 条 Science，{len(nature_entries)} 条 Nature，{len(noise_entries)} 条 Noise（已过滤）")
