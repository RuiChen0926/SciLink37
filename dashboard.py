#!/usr/bin/env python3
"""SciLink37 本地 Web Dashboard（Flask，端口 8037）。

只读浏览 + 一键触发 pipeline：按天翻看 raw / science / nature / prompt / inspiration 五个产物，
并能直接在网页上跑 sort.sh / digest.sh / collect.sh（带日期参数，跑哪一天看哪一天）。

设计约束（沿用项目惯例）：
- 离线优先：marked.js 是本地 vendor 文件（static/marked.min.js），不走 CDN。
- 单文件：前端单页 HTML 内嵌在本文件里，没有打包/构建步骤。
- 不碰 Gemma 端口 8080，不改 inbox 目录契约，只读 + 调已有的 *.sh。
- LaunchAgent 开机常驻（dashboard.plist），三击 Command 由 floater.py 唤起浏览器。
"""
import os
import re
import subprocess
from pathlib import Path

from flask import Flask, jsonify, request, send_from_directory

PROJECT_DIR = Path("/Users/rui/Projects/SciLink37")
INBOX_DIR = PROJECT_DIR / "inbox"
STATIC_DIR = PROJECT_DIR / "static"
PORT = 8037

# 日期文件夹名严格 YYYY-MM-DD —— 既是契约也是防路径穿越的白名单
DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")

# Tab → 文件名映射（inbox/YYYY-MM-DD/ 下的契约文件名）
TAB_FILES = {
    "raw": "raw.md",
    "science": "science.md",
    "nature": "nature.md",
    "prompt": "prompt.md",
    "inspiration": "inspiration.md",
}

# pipeline 触发器 → 对应脚本。键即 /api/run/<action> 的 action
RUN_SCRIPTS = {
    "sort": "sort.sh",
    "digest": "digest.sh",
    "collect": "collect.sh",
}
# Gemma 首次加载 + 推理可能要几十秒，给足超时
RUN_TIMEOUT = 600

app = Flask(__name__, static_folder=None)


@app.after_request
def _no_cache(resp):
    """开发期单用户工具：禁缓存，避免浏览器拿旧页面（如标题布局改了却没刷新）。"""
    resp.headers["Cache-Control"] = "no-store"
    return resp


def _valid_date(date):
    """日期参数必须是 YYYY-MM-DD，否则拒绝（兼作路径穿越防护）。"""
    return bool(date) and bool(DATE_RE.match(date))


def _list_dates():
    """inbox/ 下所有 YYYY-MM-DD 文件夹，新日期在前。"""
    if not INBOX_DIR.is_dir():
        return []
    dates = [p.name for p in INBOX_DIR.iterdir() if p.is_dir() and DATE_RE.match(p.name)]
    return sorted(dates, reverse=True)


def _read_tab(day_dir, filename):
    """读单个产物文件；不存在或空返回空串。"""
    f = day_dir / filename
    if not f.is_file():
        return ""
    try:
        return f.read_text(encoding="utf-8")
    except Exception as exc:  # noqa: BLE001
        return f"⚠️ 读取 {filename} 失败：{exc}"


@app.get("/")
def index():
    return PAGE_HTML


@app.get("/static/<path:name>")
def static_files(name):
    return send_from_directory(STATIC_DIR, name)


@app.get("/api/dates")
def api_dates():
    return jsonify({"dates": _list_dates()})


@app.get("/api/files")
def api_files():
    date = request.args.get("date", "")
    if not _valid_date(date):
        return jsonify({"error": "date 参数缺失或格式错误（应为 YYYY-MM-DD）"}), 400
    day_dir = INBOX_DIR / date
    files = {tab: _read_tab(day_dir, name) for tab, name in TAB_FILES.items()}
    return jsonify({"date": date, "files": files})


@app.post("/api/run/<action>")
def api_run(action):
    if action not in RUN_SCRIPTS:
        return jsonify({"error": f"未知动作 {action}"}), 404
    date = request.args.get("date", "")
    if not _valid_date(date):
        return jsonify({"error": "date 参数缺失或格式错误（应为 YYYY-MM-DD）"}), 400

    script = PROJECT_DIR / RUN_SCRIPTS[action]
    try:
        # 同步执行：脚本自带「Gemma 离线则按需拉起」逻辑，跑完才返回，前端随即刷新对应 Tab
        proc = subprocess.run(
            ["bash", str(script), date],
            cwd=str(PROJECT_DIR),
            capture_output=True,
            text=True,
            timeout=RUN_TIMEOUT,
        )
    except subprocess.TimeoutExpired:
        return jsonify({"ok": False, "error": f"{RUN_SCRIPTS[action]} 超时（{RUN_TIMEOUT}s）"}), 504
    except Exception as exc:  # noqa: BLE001
        return jsonify({"ok": False, "error": f"执行失败：{exc}"}), 500

    return jsonify({
        "ok": proc.returncode == 0,
        "returncode": proc.returncode,
        "stdout": proc.stdout[-4000:],
        "stderr": proc.stderr[-4000:],
    })


@app.post("/api/save")
def api_save():
    """编辑模式写回：body 为 {date, tab, content}，写到 inbox/<date>/<tab 对应文件>.md。"""
    data = request.get_json(silent=True) or {}
    date = data.get("date", "")
    tab = data.get("tab", "")
    content = data.get("content", "")
    if not _valid_date(date):
        return jsonify({"error": "date 参数缺失或格式错误（应为 YYYY-MM-DD）"}), 400
    if tab not in TAB_FILES:
        return jsonify({"error": f"未知 tab：{tab}"}), 400
    if not isinstance(content, str):
        return jsonify({"error": "content 必须是字符串"}), 400
    day_dir = INBOX_DIR / date
    day_dir.mkdir(parents=True, exist_ok=True)
    try:
        (day_dir / TAB_FILES[tab]).write_text(content, encoding="utf-8")
    except Exception as exc:  # noqa: BLE001
        return jsonify({"ok": False, "error": f"写入失败：{exc}"}), 500
    return jsonify({"ok": True, "bytes": len(content.encode("utf-8"))})


PAGE_HTML = r"""<!DOCTYPE html>
<html lang="zh">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>SciLink37 Dashboard</title>
<script src="/static/marked.min.js"></script>
<style>
  :root {
    --bg: #1c1c1e; --panel: #2c2c2e; --panel2: #3a3a3c;
    --text: #e5e5e7; --muted: #98989d; --accent: #0a84ff;
    --border: #48484a; --ok: #30d158; --err: #ff453a;
  }
  @media (prefers-color-scheme: light) {
    :root {
      --bg: #f2f2f7; --panel: #ffffff; --panel2: #e9e9ee;
      --text: #1c1c1e; --muted: #6c6c70; --accent: #0a84ff;
      --border: #d1d1d6; --ok: #34c759; --err: #ff3b30;
    }
  }
  * { box-sizing: border-box; }
  body {
    margin: 0; background: var(--bg); color: var(--text);
    font: 15px/1.6 -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
  }
  header {
    display: grid; grid-template-columns: 1fr auto 1fr; align-items: center; gap: 14px;
    padding: 14px 20px; background: var(--panel);
    border-bottom: 1px solid var(--border); position: sticky; top: 0; z-index: 10;
  }
  header h1 { font-size: 17px; margin: 0; font-weight: 600; }
  .hleft { display: flex; align-items: center; gap: 14px; justify-self: start; }
  .brand-center { justify-self: center; margin: 0; font-size: 27px; font-weight: 700; letter-spacing: .5px; }
  .datenav { display: flex; align-items: center; gap: 6px; }
  select, button {
    font: inherit; color: var(--text); background: var(--panel2);
    border: 1px solid var(--border); border-radius: 8px; padding: 6px 12px;
    cursor: pointer; transition: background .12s, opacity .12s;
  }
  select { min-width: 150px; }
  button:hover { background: var(--border); }
  button:disabled { opacity: .5; cursor: default; }
  .arrow { padding: 6px 10px; font-weight: 600; }
  .runbar { display: flex; gap: 8px; justify-self: end; }
  .runbar button { background: var(--accent); color: #fff; border-color: transparent; font-weight: 500; }
  .runbar button:hover { filter: brightness(1.1); }
  .runbar button.busy { background: var(--panel2); color: var(--muted); }
  .tabs { display: flex; gap: 4px; padding: 12px 20px 0; }
  .tab {
    padding: 8px 18px; border-radius: 8px 8px 0 0; background: transparent;
    border: 1px solid transparent; border-bottom: none; color: var(--muted);
  }
  .tab.active { background: var(--panel); color: var(--text); border-color: var(--border); }
  /* 采集处理层 (raw/science/nature) | 输出层 (prompt/inspiration) 之间的竖线分隔 */
  .tab-divider { align-self: center; width: 1px; height: 18px; background: var(--border); margin: 0 8px; }
  main { padding: 0 20px 40px; }
  .panel-wrap { position: relative; }
  .edit-btn {
    position: absolute; top: 10px; right: 12px; z-index: 5;
    font-size: 12px; padding: 4px 12px; opacity: .85;
  }
  .edit-btn:hover { opacity: 1; }
  #content {
    background: var(--panel); border: 1px solid var(--border); border-radius: 0 10px 10px 10px;
    padding: 48px 26px 22px; min-height: 60vh;
  }
  #content.loading { opacity: .4; }
  #editor {
    display: none; width: 100%; min-height: 62vh; resize: vertical;
    background: var(--panel); color: var(--text);
    border: 1px solid var(--accent); border-radius: 0 10px 10px 10px;
    padding: 48px 26px 22px; outline: none;
    font-family: "SF Mono", Menlo, monospace; font-size: 13px; line-height: 1.7;
    tab-size: 2;
  }
  .empty { color: var(--muted); font-style: italic; padding: 30px 0; text-align: center; }
  /* markdown 渲染样式 */
  #content h1, #content h2, #content h3 { line-height: 1.3; }
  #content h1 { font-size: 22px; border-bottom: 1px solid var(--border); padding-bottom: 6px; }
  #content h2 { font-size: 18px; margin-top: 1.4em; }
  #content h3 { font-size: 16px; color: var(--accent); }
  #content code {
    background: var(--panel2); padding: 2px 6px; border-radius: 5px;
    font-family: "SF Mono", Menlo, monospace; font-size: 13px;
  }
  #content pre { background: var(--panel2); padding: 14px; border-radius: 8px; overflow-x: auto; }
  #content pre code { background: none; padding: 0; }
  #content blockquote {
    margin: 1em 0; padding: 2px 16px; border-left: 3px solid var(--accent); color: var(--muted);
  }
  #content a { color: var(--accent); }
  #content hr { border: none; border-top: 1px solid var(--border); margin: 1.5em 0; }
  #toast {
    position: fixed; bottom: 24px; left: 50%; transform: translateX(-50%);
    background: var(--panel2); border: 1px solid var(--border); border-radius: 10px;
    padding: 12px 20px; box-shadow: 0 8px 30px rgba(0,0,0,.3);
    opacity: 0; pointer-events: none; transition: opacity .2s; max-width: 80vw;
    white-space: pre-wrap; font-size: 13px;
  }
  #toast.show { opacity: 1; }
  #toast.ok { border-color: var(--ok); }
  #toast.err { border-color: var(--err); }
</style>
</head>
<body>
<header>
  <div class="hleft">
    <h1>Dashboard</h1>
    <div class="datenav">
      <button class="arrow" id="prevDate" title="前一天">←</button>
      <select id="dateSelect"></select>
      <button class="arrow" id="nextDate" title="后一天">→</button>
    </div>
  </div>
  <h2 class="brand-center">SciLink37</h2>
  <div class="runbar">
    <button data-action="sort">Sort</button>
    <button data-action="digest">Digest</button>
    <button data-action="collect">Collect</button>
  </div>
</header>

<div class="tabs" id="tabs">
  <button class="tab active" data-tab="raw">raw</button>
  <button class="tab" data-tab="science">science</button>
  <button class="tab" data-tab="nature">nature</button>
  <span class="tab-divider" title="采集处理层 | 输出层"></span>
  <button class="tab" data-tab="prompt">prompt</button>
  <button class="tab" data-tab="inspiration">inspiration</button>
</div>

<main>
  <div class="panel-wrap">
    <button id="editToggle" class="edit-btn" title="Edit / Read 切换">✎ Edit</button>
    <div id="content"></div>
    <textarea id="editor" spellcheck="false"></textarea>
  </div>
</main>
<div id="toast"></div>

<script>
const TABS = ["raw", "science", "nature", "prompt", "inspiration"];
let dates = [];
let curDate = null;
let curTab = "raw";
let filesCache = {};   // { raw, science, nature, prompt, inspiration }
let editMode = false;  // 编辑模式在切 Tab / 切日期间保持，只有点「阅读」才退出

const $ = (sel) => document.querySelector(sel);
const dateSelect = $("#dateSelect");
const content = $("#content");
const editor = $("#editor");
const editToggle = $("#editToggle");

function toast(msg, kind) {
  const t = $("#toast");
  t.textContent = msg;
  t.className = "show " + (kind || "");
  clearTimeout(t._timer);
  t._timer = setTimeout(() => { t.className = ""; }, kind === "err" ? 6000 : 3000);
}

function renderTab() {
  const md = filesCache[curTab] || "";
  if (!md.trim()) {
    content.innerHTML = '<div class="empty">（' + curTab + ' 还没有内容）</div>';
    return;
  }
  content.innerHTML = marked.parse(md);
}

function updateEditButton() {
  editToggle.textContent = editMode ? "✓ Read" : "✎ Edit";
}

// 根据 editMode 显示「渲染视图」或「原始 MD textarea」，并填入当前 Tab 内容
function renderView() {
  if (editMode) {
    editor.value = filesCache[curTab] || "";
    content.style.display = "none";
    editor.style.display = "block";
  } else {
    editor.style.display = "none";
    content.style.display = "block";
    renderTab();
  }
  updateEditButton();
}

// 自动保存：把 textarea 当前内容写回指定 date/tab（仅在编辑中且确有改动时）
async function flushEdit(date, tab) {
  if (!editMode || !date) return;
  const text = editor.value;
  if (text === (filesCache[tab] || "")) return;  // 没改动，跳过
  filesCache[tab] = text;
  try {
    await fetch("/api/save", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ date, tab, content: text }),
    });
    toast("✅ 已保存 " + tab, "ok");
  } catch (e) {
    toast("❌ 保存失败：" + e, "err");
  }
}

async function loadFiles() {
  if (!curDate) return;
  content.classList.add("loading");
  try {
    const r = await fetch("/api/files?date=" + encodeURIComponent(curDate));
    const data = await r.json();
    if (data.error) { toast(data.error, "err"); return; }
    filesCache = data.files || {};
    renderView();
  } catch (e) {
    toast("加载失败：" + e, "err");
  } finally {
    content.classList.remove("loading");
  }
}

async function setDate(date) {
  await flushEdit(curDate, curTab);  // 切日期前先存掉旧日期正在编辑的内容
  curDate = date;
  dateSelect.value = date;
  const idx = dates.indexOf(date);
  $("#prevDate").disabled = idx >= dates.length - 1;  // dates 倒序，末尾是最早
  $("#nextDate").disabled = idx <= 0;
  await loadFiles();
}

async function loadDates() {
  const r = await fetch("/api/dates");
  const data = await r.json();
  dates = data.dates || [];
  dateSelect.innerHTML = dates.map((d) => '<option value="' + d + '">' + d + "</option>").join("");
  if (dates.length) await setDate(dates[0]);
  else content.innerHTML = '<div class="empty">inbox/ 下还没有任何日期文件夹</div>';
}

async function runAction(action, btn) {
  if (!curDate) return;
  await flushEdit(curDate, curTab);  // 跑脚本前先把正在编辑的内容存盘
  const label = btn.textContent;
  btn.disabled = true;
  btn.classList.add("busy");
  btn.textContent = label + " …";
  toast(action + " 运行中（首次会加载 Gemma，请稍候）…");
  try {
    const r = await fetch("/api/run/" + action + "?date=" + encodeURIComponent(curDate), { method: "POST" });
    const data = await r.json();
    if (data.ok) {
      toast("✅ " + action + " 完成", "ok");
      // 动作名 → 产物 Tab：sort→science，digest→prompt，collect→inspiration
      const jumpMap = { sort: "science", digest: "prompt", collect: "inspiration" };
      await loadFiles();
      await switchTab(jumpMap[action] || curTab);
    } else {
      toast("❌ " + action + " 失败：\n" + (data.error || data.stderr || data.stdout || "未知错误"), "err");
    }
  } catch (e) {
    toast("❌ 请求失败：" + e, "err");
  } finally {
    btn.disabled = false;
    btn.classList.remove("busy");
    btn.textContent = label;
  }
}

async function switchTab(tab) {
  if (tab === curTab) return;
  await flushEdit(curDate, curTab);  // 切 Tab 前先存掉旧 Tab 正在编辑的内容
  curTab = tab;
  document.querySelectorAll(".tab").forEach((el) => {
    el.classList.toggle("active", el.dataset.tab === tab);
  });
  renderView();  // 编辑模式保持：新 Tab 直接进 textarea；否则渲染
}

async function toggleEdit() {
  if (editMode) {
    await flushEdit(curDate, curTab);  // 退出编辑前存盘
    editMode = false;
  } else {
    editMode = true;
  }
  renderView();
  if (editMode) editor.focus();
}

// ---- 事件绑定 ----
dateSelect.addEventListener("change", (e) => setDate(e.target.value));
$("#prevDate").addEventListener("click", () => {
  const idx = dates.indexOf(curDate);
  if (idx < dates.length - 1) setDate(dates[idx + 1]);
});
$("#nextDate").addEventListener("click", () => {
  const idx = dates.indexOf(curDate);
  if (idx > 0) setDate(dates[idx - 1]);
});
document.querySelectorAll(".tab").forEach((el) => {
  el.addEventListener("click", () => switchTab(el.dataset.tab));
});
document.querySelectorAll(".runbar button").forEach((btn) => {
  btn.addEventListener("click", () => runAction(btn.dataset.action, btn));
});
editToggle.addEventListener("click", toggleEdit);
// 键盘左右箭头切日期（编辑中 / 下拉聚焦时不抢，交给光标移动）
document.addEventListener("keydown", (e) => {
  if (e.target.tagName === "SELECT" || e.target.tagName === "TEXTAREA") return;
  if (e.key === "ArrowLeft") $("#prevDate").click();
  if (e.key === "ArrowRight") $("#nextDate").click();
});

loadDates();
</script>
</body>
</html>"""


if __name__ == "__main__":
    print(f"✅ SciLink37 Dashboard: http://localhost:{PORT}")
    # threaded=True：pipeline 跑 60s 时不阻塞其它请求；只听 localhost，数据不出门
    app.run(host="127.0.0.1", port=PORT, threaded=True)
