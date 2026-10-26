# SciLink37 · CLAUDE.md

## 这个项目是什么

SciLink37 是一个**本地运行的科研意图转化系统**。
它的唯一工作：把研究者零散的思维碎片（语音、手稿、意识流笔记），通过本地 Gemma E2B，转化为一条可以直接交给 Antigravity 执行的研究指令。

目标用户：没有机构支持、没有团队、没有 PI 的独立科研者——所有计算和 AI 推理跑在自己的机器上，数据不出门，零成本。

> **文档分工**：用户使用说明、安装步骤、命令手册都在 [README.md](README.md)（面向外部用户）。本文件（CLAUDE.md）是给协作 AI 的开发指南，两者职责不同。

---

## 研究者背景（系统上下文）

**研究者**：Rui Chen，计算机科学与技术博士，具有大气物理与物理海洋学背景；研究经历涵盖热带气旋形成预测、强度订正、时空机器学习及全球数据集开发。

**当前研究**：AlphaStorm 项目——用宇宙普适框架（旋转、能量输入、耗散、自组织）简化 TC 建模，并延伸至跨系统验证（大红斑、吸积盘）。北极星：Understand the Universe。

**四阶段路线图**：
- 阶段 0：无量纲框架（当前）
- 阶段 1：TC 投影
- 阶段 2：SINDy 最小模型
- 阶段 3：跨系统验证（大红斑、吸积盘）

**本地算力**：Apple M5 MacBook Pro，MLX 加速，Gemma E2B 常驻。

---

## 项目结构

```
SciLink37/
├── CLAUDE.md                       # 本文件（协作 AI 的开发指南）
├── README.md                       # 项目说明 / 用户手册（面向外部用户）
├── floater.py                      # 双击 Command 唤起悬浮输入框写 raw.md；三击 Command 打开 Dashboard（LaunchAgent 开机常驻）
├── dashboard.py                    # 本地 Web Dashboard（Flask，端口 8037）：按天浏览/编辑产物 + 一键触发 pipeline（LaunchAgent 开机常驻）
├── dashboard.plist                 # Dashboard 的 LaunchAgent（开机自启，装到 ~/Library/LaunchAgents/）
├── static/marked.min.js            # Dashboard 前端的 Markdown 渲染库（本地 vendor，离线可用，不走 CDN）
├── start.sh                        # 启动本地 Gemma 服务器（包装 ~/start_secretary.sh + 健康检查）
├── stop.sh                         # pkill 本地 Gemma 服务器
├── disable.sh                      # pkill floater.py（开机自启的关掉按钮）
├── sort.sh                         # 把 raw.md 按主题分类 → science.md / nature.md
├── sort_helper.py                  # 分类 API 调用（! / ? 走快捷通道；其余交 Gemma 输出 JSON）
├── digest.sh                       # 读 science.md（缺则回退 raw.md）→ 写 prompt.md
├── digest_helper.py                # Digest API 调用（三段式 system prompt）
├── collect.sh                      # 读 science.md + nature.md（合并）→ 分组归档 + 今日总结 → 写 inspiration.md
├── collect_helper.py               # Collect API 调用（灵感整理 system prompt）
└── inbox/                          # 按天分文件夹的碎片目录
    └── YYYY-MM-DD/                 # 每天一个文件夹，跨天自动新建
        ├── raw.md                  # 当天所有 floater 输入追加到这里
        ├── science.md              # sort.sh 分出来的科研相关条目
        ├── nature.md               # sort.sh 分出来的灵感 / 外部信息条目
        ├── prompt.md               # digest.sh 写出的三段式指令
        ├── inspiration.md          # collect.sh 写出的灵感分组 + 今日总结（读 science + nature）
        └── unclassified.md         # sort_helper 兜底：raw 总条数 ≠ 分类条数时，未匹配条目写到这里，供人工检查
```

> `~/start_secretary.sh` 不在 repo 里——它是用户机器上的 Gemma 启动脚本（`mlx_lm.server` 加 4-bit 模型），被 `start.sh` 包装、也被 `sort.sh` / `digest.sh` / `collect.sh` / `floater.py` 在 Gemma 离线时按需 nohup 拉起。

---

## 核心 Pipeline

```
       floater.py  →  inbox/YYYY-MM-DD/raw.md
                              ↓
                          sort.sh
                              ↓
        ┌─────────────────────┴─────────────────────┐
        ↓                                           ↓
inbox/YYYY-MM-DD/science.md          inbox/YYYY-MM-DD/nature.md
        ↓                                           ↓
     digest.sh                                  collect.sh
        ↓                          （读 science + nature 两路合并）
        ↓                                           ↓
inbox/YYYY-MM-DD/prompt.md           inbox/YYYY-MM-DD/inspiration.md
（三段式指令 → Antigravity）            （灵感分组 + 今日总结）
```

按天分文件夹：每条 floater 输入自动追加到当天日期文件夹下的 `raw.md`，跨天自动新建文件夹。sort.sh 在原地写出 science.md / nature.md；digest.sh 优先读 science.md，缺失则回退到 raw.md；collect.sh 读 science.md + nature.md（两路合并后送 Gemma）。所有产物都留在同一天的文件夹里，方便回溯。

---

## Digest 输出格式（三段式，不得更改）

```
## 1. 初始场
[当前在哪个阶段，最活跃的未解决问题，一句话说清楚]

## 2. 边界场
[今天只做什么，明确排除什么，约束条件]

## 3. 给 Antigravity 的第一条指令
[一句话，动词开头，具体到文件或函数级别]
```

这个格式是系统的核心协议。任何修改都需要同步更新 `digest_helper.py` 里的 system prompt。

---

## 本地 AI 服务器

| 参数 | 值 |
|------|-----|
| 模型 | `mlx-community/gemma-4-e2b-it-4bit` |
| 启动方式 | `./start.sh`（包装 `~/start_secretary.sh`） |
| API 端点 | `http://localhost:8080/v1/chat/completions` |
| temperature | 0.3 |
| max_tokens | 1200 |

Claude Code 在调用 `digest_helper.py` 前，**必须确认服务器已启动**（可用 `curl http://localhost:8080/v1/models` 检查）。

---

## 模型选型

`config.sh` 注册了两个本地模型，用环境变量 `MODEL` 切换（默认 2B）：

| MODEL | 模型字符串 | 适合任务 | 不适合任务 |
|------|------|---------|-----------|
| `2b`（默认） | `mlx-community/gemma-4-e2b-it-4bit` | sort / digest | — |
| `26b` | `mlx-community/gemma-4-26b-a4b-it-4bit`（MoE：26B 总参 / 4B 激活） | collect（推理质量超过 2B） | sort / digest（不按格式输出） |

**实测结论**（2026-06-03）：26B 在结构化输出任务上不可用——sort 不出 JSON、digest 不出 `## 1./## 2./## 3.` 三段式，token 全花在 thinking / 自我对话上。collect 是自由文本任务（分组 + 总结），结构柔性大，26B 的推理优势能体现，且按格式输出。

**各任务默认模型**

| 脚本 | 默认 MODEL | 覆盖方法 |
|------|-----------|---------|
| `./sort.sh` | `2b` | 不建议覆盖（26B 不出 JSON） |
| `./digest.sh` | `2b` | 不建议覆盖（26B 不出三段式） |
| `./collect.sh` | `26b`（`MODEL_DEFAULT_COLLECT`） | `MODEL=2b ./collect.sh` 降级 |

默认值在 `config.sh` 的 `MODEL_DEFAULT_*` 常量里。

**机制**：`mlx_lm.server` 是 lazy-load 多模型——只要本地缓存有，请求里写哪个模型字段就现场加载哪个。`~/start_secretary.sh` 的 `MODEL` 只控制启动时**预热**哪个，不限制后续切换；三个 pipeline 脚本会在请求前校验 `SELECTED_MODEL` 是否在本地缓存里。

---

## 本地 Web Dashboard

`dashboard.py` 是一层薄薄的本地 Web 界面，**只读/编辑 inbox 里的同一批文件、并触发同一批脚本**，不是另一条 pipeline。CLI 仍是核心；Dashboard 只是方便按天回看和微调。

| 参数 | 值 |
|------|-----|
| 框架 | Flask |
| 端口 | `8037`（硬编码，只听 `127.0.0.1`，数据不出门） |
| 启动 | `dashboard.plist`（LaunchAgent 开机常驻），或手动 `python3 dashboard.py` |
| 唤起 | floater 里**三击 Command**（1 秒内三次）→ `open http://localhost:8037` |
| 前端 | 单页内嵌在 `dashboard.py` 里，Markdown 用本地 `static/marked.min.js` 渲染（离线，不走 CDN） |
| 依赖 | `flask`（一次性 `pip install`，运行时离线） |

**路由**

| 方法 路径 | 作用 |
|------|-----|
| `GET /` | 单页主界面 |
| `GET /static/<f>` | 前端静态资源（marked.min.js） |
| `GET /api/dates` | 列出 `inbox/` 下所有 `YYYY-MM-DD` 文件夹（新→旧） |
| `GET /api/files?date=` | 返回当天 raw/science/nature/prompt/inspiration 五个产物内容 |
| `POST /api/run/{sort,digest,collect}?date=` | **同步**执行对应脚本（带日期参数，跑完才返回，最长 600s；脚本自带 Gemma 按需拉起） |
| `POST /api/save` | 编辑模式写回：body `{date, tab, content}` → 写对应 `.md` |

**前端交互**：日期切换器（下拉 + ←/→）；五个 Tab `raw / science / nature ｜ prompt / inspiration`（竖线分隔「采集处理层 ｜ 输出层」）；Sort / Digest / Collect 触发按钮；Obsidian 式 **Edit / Read** 切换——编辑模式显示原始 MD textarea，**切 Tab / 切日期 / 退出编辑 / 跑脚本前都会自动 `POST /api/save`**，无需手动确认。

**安全/防护**：`date` 必须匹配 `^\d{4}-\d{2}-\d{2}$`（兼作路径穿越白名单），`tab` 必须在 `TAB_FILES` 白名单内；非法一律 400。响应统一带 `Cache-Control: no-store`，避免浏览器拿到旧页面。

---

## 开发约定

**做什么**
- pipeline 线性、按天文件夹组织：floater → raw → sort → {science, nature} → {digest, collect}
- 脚本报错时直接打印清晰的中文错误信息
- raw.md 按天追加，sort/digest/collect 都不动 raw——每天的碎片和所有派生产物都留档

**不做什么**
- 不引入任何**运行时需要联网**的依赖（离线优先是核心设计原则）；新增的 `flask` / `marked.js` 都是装好后纯本地运行，marked.js 走 vendor 不走 CDN
- 捕获/整理的核心仍是 CLI + 本地文件；Dashboard 只是覆盖在同一批文件上的本地只读/编辑/触发层，**不另起一套数据流，不替代 CLI**
- 不微调模型（使用预训练权重 + system prompt 驱动）
- 不做双层架构、不做 JSON 协议、不做云端/多用户（保持单机单用户）

**硬约束（不可改）**
- `floater.py` 和 `dashboard.py` 都是 LaunchAgent 开机拉起的常驻进程，**修改源码后必须 `launchctl kickstart -k gui/$(id -u)/com.scilink37.<floater|dashboard>`（或 `kill <pid>` 让 LaunchAgent 自动重拉）才会加载新代码**，否则跑的还是旧的
- Dashboard 端口固定 `8037`（`dashboard.py` 硬编码，只听 localhost）；marked.js 必须留在本地 `static/`，**不可改成 CDN**——会破坏离线原则
- `inbox/` 的目录结构和文件名（`YYYY-MM-DD/{raw,science,nature,prompt,inspiration}.md`）是 pipeline 各脚本之间的契约，**不可更改**——任何一个名字动了，下游脚本全部断链。（v1 的 `digest.md` / `collect.md` 已于 2026-06-03 重命名为 `prompt.md` / `inspiration.md`）
- `sort_helper.py` / `digest_helper.py` 的 system prompt 嵌入了当前研究阶段（见上方 [研究者背景]），**随研究阶段推进需要人工同步更新**，不要自动改
- Gemma 端口固定 `8080`，所有脚本硬编码，**不可更改**——动端口要同步改一堆地方

---

## 常见操作

```bash
# 启动本地 AI 服务器（已在跑时短路返回）
./start.sh

# 关停本地 AI 服务器
./stop.sh

# 关停 floater（关掉双击 Command 触发；下次开机 LaunchAgent 会再拉起）
./disable.sh

# 把今天的 raw.md 分类成 science.md / nature.md
./sort.sh

# 整理今天的 science.md（缺则用 raw.md），结果写入 inbox/YYYY-MM-DD/prompt.md
./digest.sh

# 整理今天的 science.md + nature.md（合并），结果写入 inbox/YYYY-MM-DD/inspiration.md
./collect.sh

# 检查服务器是否在线
curl http://localhost:8080/v1/models

# 打开本地 Web Dashboard（也可在 floater 里三击 Command）
open http://localhost:8037

# 改了 floater.py / dashboard.py 后重启对应常驻进程（加载新代码）
launchctl kickstart -k gui/$(id -u)/com.scilink37.dashboard   # 或 com.scilink37.floater

# 首次安装 Dashboard 的开机自启
cp dashboard.plist ~/Library/LaunchAgents/com.scilink37.dashboard.plist
launchctl load ~/Library/LaunchAgents/com.scilink37.dashboard.plist

# 碎片捕获本身没有单独的命令——floater.py 是 LaunchAgent 开机常驻进程，
# 双击 Command 唤起悬浮框直接写入今天的 raw.md；三击 Command 打开 Dashboard。
```

---

## 当前状态（2026-05-23）

- [x] 本地 Gemma E2B 服务器可启动（`./start.sh` / `./stop.sh`）
- [x] floater.py 开机常驻 + 双击 Command 唤起 + `!` / `?` 快捷通道
- [x] floater → sort → digest / collect 完整 pipeline 端到端验证通过
- [x] 本地 Web Dashboard（`dashboard.py`，端口 8037）：按天浏览/编辑产物 + 一键触发 pipeline；floater 三击 Command 唤起
- [x] GitHub 仓库已建：[RuiChen0926/SciLink37](https://github.com/RuiChen0926/SciLink37)（当前 private）
- [ ] Demo 录制（2 分钟视频）

**今日优先级**：先跑通 pipeline，再写文档，最后录视频。
