# SciLink37 · CLAUDE.md

## 这个项目是什么

SciLink37 是一个**本地运行的科研意图转化系统**。
它的唯一工作：把研究者零散的思维碎片（语音、手稿、意识流笔记），通过本地 Gemma E2B，转化为一条可以直接交给 Antigravity 执行的研究指令。

目标用户：没有机构支持、没有团队、没有 PI 的独立科研者——所有计算和 AI 推理跑在自己的机器上，数据不出门，零成本。

> **文档分工**：用户使用说明、安装步骤、命令手册都在 [README.md](README.md)（面向外部用户）。本文件（CLAUDE.md）是给协作 AI 的开发指南，两者职责不同。

---

## 研究者背景（系统上下文）

**研究者**：Rui，计算物理学方向，研究热带气旋（TC）快速增强（RI）十年。

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
├── floater.py                      # 双击 Command 唤起的悬浮输入框，写入今天的 raw.md（LaunchAgent 开机常驻）
├── start.sh                        # 启动本地 Gemma 服务器（包装 ~/start_secretary.sh + 健康检查）
├── stop.sh                         # pkill 本地 Gemma 服务器
├── disable.sh                      # pkill floater.py（开机自启的关掉按钮）
├── sort.sh                         # 把 raw.md 按主题分类 → science.md / nature.md
├── sort_helper.py                  # 分类 API 调用（! / ? 走快捷通道；其余交 Gemma 输出 JSON）
├── digest.sh                       # 读 science.md（缺则回退 raw.md）→ 写 digest.md
├── digest_helper.py                # Digest API 调用（三段式 system prompt）
├── collect.sh                      # 读 nature.md → 分组归档 + 今日总结 → 写 collect.md
├── collect_helper.py               # Collect API 调用（灵感整理 system prompt）
└── inbox/                          # 按天分文件夹的碎片目录
    └── YYYY-MM-DD/                 # 每天一个文件夹，跨天自动新建
        ├── raw.md                  # 当天所有 floater 输入追加到这里
        ├── science.md              # sort.sh 分出来的科研相关条目
        ├── nature.md               # sort.sh 分出来的灵感 / 外部信息条目
        ├── digest.md               # digest.sh 写出的三段式指令
        ├── collect.md              # collect.sh 写出的灵感分组 + 今日总结
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
        ↓                                           ↓
inbox/YYYY-MM-DD/digest.md           inbox/YYYY-MM-DD/collect.md
（三段式指令 → Antigravity）            （灵感分组 + 今日总结）
```

按天分文件夹：每条 floater 输入自动追加到当天日期文件夹下的 `raw.md`，跨天自动新建文件夹。sort.sh 在原地写出 science.md / nature.md；digest.sh 优先读 science.md，缺失则回退到 raw.md；collect.sh 读 nature.md。所有产物都留在同一天的文件夹里，方便回溯。

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

## 开发约定

**做什么**
- pipeline 线性、按天文件夹组织：floater → raw → sort → {science, nature} → {digest, collect}
- 脚本报错时直接打印清晰的中文错误信息
- raw.md 按天追加，sort/digest/collect 都不动 raw——每天的碎片和所有派生产物都留档

**不做什么**
- 不引入任何需要联网的依赖（离线优先是核心设计原则）
- 不做 UI、不做 Web 界面——这是 CLI 工具
- 不微调模型（使用预训练权重 + system prompt 驱动）
- 不做双层架构、不做 JSON 协议、不做调度脚本（这些是 v2 的事）

**硬约束（不可改）**
- `floater.py` 是 LaunchAgent 开机拉起的常驻进程，**修改源码后必须 `launchctl restart`（或 `kill <pid>` 让 LaunchAgent 自动重拉）才会加载新代码**，否则跑的还是旧的
- `inbox/` 的目录结构和文件名（`YYYY-MM-DD/{raw,science,nature,digest,collect}.md`）是 pipeline 各脚本之间的契约，**不可更改**——任何一个名字动了，下游脚本全部断链
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

# 整理今天的 science.md（缺则用 raw.md），结果写入 inbox/YYYY-MM-DD/digest.md
./digest.sh

# 整理今天的 nature.md，结果写入 inbox/YYYY-MM-DD/collect.md
./collect.sh

# 检查服务器是否在线
curl http://localhost:8080/v1/models

# 碎片捕获本身没有单独的命令——floater.py 是 LaunchAgent 开机常驻进程，
# 双击 Command 唤起悬浮框直接写入今天的 raw.md。
```

---

## 当前状态（2026-05-23）

- [x] 本地 Gemma E2B 服务器可启动（`./start.sh` / `./stop.sh`）
- [x] floater.py 开机常驻 + 双击 Command 唤起 + `!` / `?` 快捷通道
- [x] floater → sort → digest / collect 完整 pipeline 端到端验证通过
- [x] GitHub 仓库已建：[RuiChen0926/SciLink37](https://github.com/RuiChen0926/SciLink37)（当前 private）
- [ ] Demo 录制（2 分钟视频）

**今日优先级**：先跑通 pipeline，再写文档，最后录视频。
