# SciLink37 · CLAUDE.md

## 这个项目是什么

SciLink37 是一个**本地运行的科研意图转化系统**。
它的唯一工作：把研究者零散的思维碎片（语音、手稿、意识流笔记），通过本地 Gemma E2B，转化为一条可以直接交给 Claude Code 执行的研究指令。

目标用户：没有机构支持、没有团队、没有 PI 的独立科研者——所有计算和 AI 推理跑在自己的机器上，数据不出门，零成本。

参赛背景：Kaggle · Gemma 4 for Good Hackathon · Health & Sciences track。

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
├── CLAUDE.md              # 本文件
├── capture.sh             # 捕获研究碎片 → inbox.md
├── digest.sh              # inbox.md → 本地 Gemma → 结构化输出
├── digest_helper.py       # API 调用逻辑（调用本地 MLX 服务器）
├── inbox.md               # 临时碎片存储（每次 digest 后可清空）
└── start_secretary.sh     # 启动本地 Gemma E2B 服务器（mlx_lm.server）
```

---

## 核心 Pipeline

```
capture.sh  →  inbox.md  →  digest.sh  →  digest_helper.py
                                               ↓
                               本地 Gemma E2B（http://localhost:8080/v1）
                                               ↓
                               结构化输出（三段式）
                                               ↓
                               给 Claude Code 的第一条指令
```

---

## Digest 输出格式（三段式，不得更改）

```
## 初始场
[当前阶段、停在哪里、最活跃问题]

## 边界场
[今天范围、不做什么、约束条件]

## 给 Claude 的第一条指令
[一句话，直接可发给 Claude Code 的可执行指令]
```

这个格式是系统的核心协议。任何修改都需要同步更新 `digest_helper.py` 里的 system prompt。

---

## 本地 AI 服务器

| 参数 | 值 |
|------|-----|
| 模型 | `mlx-community/gemma-4-e2b-it-4bit` |
| 启动方式 | `./start_secretary.sh` |
| API 端点 | `http://localhost:8080/v1/chat/completions` |
| temperature | 0.3 |
| max_tokens | 1200 |

Claude Code 在调用 `digest_helper.py` 前，**必须确认服务器已启动**（可用 `curl http://localhost:8080/v1/models` 检查）。

---

## 开发约定

**做什么**
- 保持 pipeline 线性、无分叉：capture → digest → 指令，仅此一条路
- 脚本报错时直接打印清晰的中文错误信息
- inbox.md 是临时文件，可被清空，不做持久存储

**不做什么**
- 不引入任何需要联网的依赖（离线优先是核心设计原则）
- 不做 UI、不做 Web 界面——这是 CLI 工具
- 不微调模型（使用预训练权重 + system prompt 驱动）
- 不做双层架构、不做 JSON 协议、不做调度脚本（这些是 v2 的事）

---

## 常见操作

```bash
# 启动本地 AI 服务器
./start_secretary.sh

# 捕获一条研究碎片
./capture.sh

# 整理 inbox，生成结构化输出
./digest.sh

# 检查服务器是否在线
curl http://localhost:8080/v1/models
```

---

## 当前状态（2026-05-18）

- [x] 本地 Gemma E2B 服务器可启动
- [x] `capture.sh` / `digest.sh` / `digest_helper.py` 脚本存在
- [ ] capture → digest 完整 pipeline 端到端验证
- [ ] README（英文，用于 Kaggle 提交）
- [ ] Demo 录制（2 分钟视频）
- [ ] GitHub 公开仓库

**今日优先级**：先跑通 pipeline，再写文档，最后录视频。
