# SciLink37

一个本地运行的科研意图转化系统。唯一的工作：把研究者零散的思维碎片，转化为可以直接交给 Antigravity 执行的精准指令。

---

## 设计哲学

研究者最宝贵的资产不是数据，是直觉。但直觉是易碎的——它出现在走路时、睡前、读文献的间隙，不捕获就消失。

SciLink37 做三件事：**捕获、分类、翻译**。

捕获降低摩擦，让碎片能进来；分类隔离噪声，让信号浮出来；翻译跨越鸿沟，让直觉变成行动。

---

## 快速开始

### 记录碎片

开机即用，双击 Command 唤起悬浮框：

```
Fact Recording...   ! 直觉  ? 卡点  → 记录
```

输入规范：

- `!` 开头 → 关键直觉或突破，最高优先级
- `?` 开头 → 卡住的问题，优先进入研究主线
- 直接输入 → 摘录、链接、普通信息

支持五种输入方式：手打、选中文字自动预填、URL 抓取标题摘要、OCR 框选、语音输入。

### 整理与消化

```bash
./sort.sh       # 分类：Science / Nature / Noise
./digest.sh     # Science → 三段式研究指令（写 prompt.md）
./collect.sh    # Science + Nature → 分组归档 + 今日总结（写 inspiration.md）
```

### 按需启动 Gemma

```bash
./start.sh      # 手动启动 Gemma（用于其他任务）
./stop.sh       # 关闭 Gemma
```

---

## 工作流

```
双击 Command
    ↓
inbox/YYYY-MM-DD/raw.md
    ↓
./sort.sh
    ├── science.md    → ! ? 优先，研究主线
    ├── nature.md     → 灵感、外部信息
    └── noise         → 直接丢弃
    ↓
./digest.sh                    ./collect.sh
（读 science）                 （读 science + nature）
    ↓                              ↓
prompt.md                      inspiration.md
（给 Antigravity 的指令）       （分组归档）
```

---

## Digest 输出格式

```
─────────────────────────────
  YYYY-MM-DD  SciLink37 Prompt
─────────────────────────────

1. 初始场
当前在哪个阶段，最活跃的未解决问题

2. 边界场
今天只做什么，明确排除什么

3. 给 Antigravity 的第一条指令
一句话，动词开头，具体到文件或函数级别

─────────────────────────────
  ✅ 已写入 inbox/YYYY-MM-DD/prompt.md
─────────────────────────────
```

---

## 目录结构

```
SciLink37/
├── floater.py              # 悬浮捕获窗口（开机常驻）
├── sort.sh                 # 分类脚本
├── sort_helper.py          # 分类逻辑（调用 Gemma）
├── digest.sh               # 研究整理脚本
├── digest_helper.py        # 翻译逻辑（调用 Gemma）
├── collect.sh              # 灵感归档脚本
├── collect_helper.py       # 归档逻辑（调用 Gemma）
├── start.sh                # 启动 Gemma
├── stop.sh                 # 关闭 Gemma
├── disable.sh              # 彻底禁用 floater 自启动
└── inbox/
    └── YYYY-MM-DD/
        ├── raw.md          # 原始记录（不动）
        ├── science.md      # 研究主线碎片
        ├── nature.md       # 灵感外部信息
        ├── prompt.md       # 研究指令输出（digest.sh）
        └── inspiration.md  # 灵感归档输出（collect.sh，读 science + nature）
```

---

## 研究者背景

**Rui** · 计算物理学博士，核心研究对象热带气旋（TC）十年。

当前项目：**AlphaStorm** — 用宇宙普适框架（旋转、能量输入、耗散、自组织）简化 TC 建模，延伸至 Universe Storm。北极星：understand the universe。

四阶段路线：
- 阶段 0：无量纲框架（当前）
- 阶段 1：TC 投影进参数空间
- 阶段 2：SINDy 最小模型
- 阶段 3：跨系统验证（大红斑、吸积盘）

---

## 技术架构

- **捕获层**：PyObjC + NSVisualEffectView，CGEventTap 监听双击 Command
- **语音识别**：mlx-whisper 本地推理
- **OCR**：macOS Vision Framework（VNRecognizeTextRequest）
- **分类 / 翻译**：Gemma 4 E2B（mlx-community/gemma-4-e2b-it-4bit），本地 MLX 推理
- **自启动**：macOS LaunchAgent

本地运行，数据不出门，零云端依赖。

---

## 历史数据蒸馏（可选）

如果你有过去的研究笔记或对话记录，可以用二次蒸馏的方式接入 SciLink37：

每天10分钟，翻一个历史文档，遇到今天仍有共鸣的判断或卡点，用 `!` 或 `?` 重新记进 floater。

经过你今天视角的二次判断，历史碎片才真正进入研究主线。

---

*SciLink37 · 输入侧 Harness · 让直觉到达 Agent*
