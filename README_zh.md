# SciLink37

[English](README.md) | [简体中文](README_zh.md)

**Local research-idea capture and instruction drafting for AI-assisted scientific workflows.**

SciLink37 是一个面向 macOS 的个人科研工作流原型：捕获零散想法，使用本地语言模型整理研究笔记，再生成供研究者审阅、交给 AI 编程工具的任务指令。

**项目状态：个人研究原型，需要手动配置。** 当前代码包含作者机器的路径、外部模型启动脚本和个性化研究提示词。它负责科研输入的捕获与整理；生成的指令需要人工检查，项目本身不自动执行科学实验或验证科学结论。

## 功能

- **快速捕获**：双击 Command 唤起原生悬浮输入框，按日期追加到 Markdown 文件。
- **多种输入**：手动输入、选中文字预填、URL 标题/摘要、屏幕 OCR、语音转写。
- **分类**：以 `!` / `?` 开头的条目直接进入研究主线；其余条目由本地模型分为 science、nature 和 noise。
- **指令草拟**：将研究碎片整理为“当前问题、任务边界、第一条指令”三段式输出。
- **归档**：按主题分组科研与灵感笔记，并生成当日总结。
- **Dashboard**：按日期浏览和编辑文件，触发 Sort / Digest / Collect。三击 Command 可打开面板。

## 架构与数据流

```text
floater.py → inbox/YYYY-MM-DD/raw.md
                         ↓ sort.sh + sort_helper.py
                   science.md + nature.md

science.md（缺失或为空时用 raw.md）
    → digest.sh + digest_helper.py → prompt.md

science.md + nature.md
    → collect.sh + collect_helper.py → inspiration.md
```

Dashboard 使用同一组本地文件和脚本，不另建数据库。Digest 优先读取 science.md；该文件缺失或为空时回退到 raw.md。分类出的 noise 不写入派生文件，原始 raw.md 保留；若分类数量检查不一致，程序可能生成 unclassified.md 供人工检查。

| 组件 | 实现 |
| --- | --- |
| 原生捕获与快捷键 | Python、PyObjC、AppKit、Quartz / CGEventTap |
| OCR | macOS Vision Framework |
| 语音转写 | sounddevice、NumPy、mlx-whisper |
| URL 信息抓取 | requests、BeautifulSoup；部分情况调用本地模型辅助整理 |
| 本地模型接口 | MLX / mlx_lm.server，HTTP API：localhost:8080 |
| 本地面板 | Flask，127.0.0.1:8037；本地 marked.js 渲染 Markdown |
| 数据与编排 | Markdown、Python、Bash；可选 LaunchAgent |

## 环境要求

- macOS；当前模型推理与语音方案面向 Apple Silicon / MLX 环境。
- Python 3 环境、Bash、curl、Git，以及支持所选模型的本地内存与存储空间。
- 已安装的模型服务和可访问的模型权重。模型标识来自 config.sh，需在本机确认可用。
- 悬浮框全局快捷键需要相应的辅助功能 / 输入监控权限；OCR 屏幕捕获与语音输入分别需要录屏、麦克风权限，具体以 macOS 提示为准。

当前没有锁定依赖版本，也未提供跨设备兼容性测试矩阵。以下为根据源码整理的配置流程，尚未作为本次文档更新的一部分在全新环境中验证。

## 安装与配置

### 1. 获取代码与 Python 环境

```bash
git clone https://github.com/RuiChen0926/SciLink37.git
cd SciLink37
python3 -m venv .venv
source .venv/bin/activate
python -m pip install flask pyobjc mlx-lm
# 可选输入功能：URL 抓取、录音、语音转写
python -m pip install requests beautifulsoup4 numpy sounddevice mlx-whisper
```

上述依赖列表按源码导入整理，尚未锁定兼容版本。URL 或语音依赖缺失时，相关功能会降级并输出日志。

### 2. 配置项目路径

当前原型使用作者机器的绝对路径，运行前需要修改：

| 文件 | 需要适配的内容 |
| --- | --- |
| floater.py | INBOX_DIR |
| dashboard.py | PROJECT_DIR |
| sort.sh / digest.sh / collect.sh | config.sh、inbox 与 Python helper 的绝对路径 |
| dashboard.plist | Python 解释器、脚本路径和 WorkingDirectory |

将 /Users/rui/Projects/SciLink37 替换为你自己的项目目录。配置 Python 路径时，确保 CLI、GUI 和 LaunchAgent 使用已安装依赖的同一个环境。

### 3. 准备本地模型服务

- config.sh 当前登记了 mlx-community/gemma-4-e2b-it-4bit 与 mlx-community/gemma-4-26b-a4b-it-4bit。它们是当前代码的配置值，不代表所有环境均已验证可用。
- sort / digest 默认选择 2b；collect 默认选择 26b，可通过 MODEL=2b 覆盖。
- start.sh 和 pipeline 脚本依赖 **~/start_secretary.sh**；该启动脚本不在仓库中，需要自行提供或修改调用位置，使服务在 localhost:8080 提供模型列表与对话接口。
- 下载并缓存所需权重后再运行；初次安装依赖和下载模型需要网络。

检查接口：

```bash
curl http://localhost:8080/v1/models
```

服务器返回的模型列表需要包含任务选择的模型标识，否则脚本会报错。

### 4. 配置研究上下文

sort_helper.py 与 digest_helper.py 中保留了作者的 AlphaStorm 研究上下文。这是个性化配置；用于其他研究时，需人工调整研究主题、阶段与任务边界，并检查分类和指令输出是否符合预期。

## 使用

### 捕获与面板

在两个终端分别启动：

```bash
# 终端 A：本地 Dashboard
python dashboard.py

# 终端 B：原生捕获窗口与全局快捷键
python floater.py
```

打开 http://localhost:8037。双击 Command 捕获想法，Enter 保存，Esc 取消；三击 Command 打开面板。不要同时启动重复的 floater / Dashboard 进程。

输入示例（仅演示，不是实验结果）：

```text
! 比较加入海洋变量前后，模型对快速增强样本的表现。
? 如何按风暴划分训练集与测试集，减少同一风暴样本之间的泄漏？
一篇相关论文的标题或链接。
```

每个片段存入当日 raw.md；! 表示直觉，? 表示问题。两类标记优先保留到 science.md。

### 运行整理流程

完成路径和模型配置后，在项目目录运行：

```bash
bash sort.sh
bash digest.sh
MODEL=2b bash collect.sh

# 处理指定日期：日期目录需已有相应输入文件
bash sort.sh YYYY-MM-DD
bash digest.sh YYYY-MM-DD
MODEL=2b bash collect.sh YYYY-MM-DD
```

这里显式选择 2b 运行 collect，便于只准备一个模型的初次检查；不指定 MODEL 时仍使用 config.sh 中的默认值。可从 Dashboard 的按钮触发同样的步骤。

**人工检查点**：确认 raw.md 追加正确，science.md / nature.md 分类合理，prompt.md 的任务与边界可理解，inspiration.md 可追溯到输入。生成指令应由研究者审阅后再交给 Antigravity 等工具。

### 可选自启动

先手动运行验证，再编辑 dashboard.plist 中的解释器和项目路径，将其安装到 ~/Library/LaunchAgents/。仓库提供 Dashboard 的 LaunchAgent 示例；捕获窗口的自启动配置需要自行准备。代码修改后，已启动的常驻进程需要重启才能加载更新。

## 主要文件

| 文件 | 职责 |
| --- | --- |
| floater.py | 捕获窗口、全局快捷键、OCR、URL 抓取和语音 |
| dashboard.py / dashboard.plist | 本地面板及可选自启动配置 |
| sort.sh / sort_helper.py | 分类与未分类条目检查 |
| digest.sh / digest_helper.py | 三段式研究指令草拟 |
| collect.sh / collect_helper.py | 笔记分组与总结 |
| config.sh | 模型标识与任务默认值 |
| start.sh / stop.sh | 包装本机模型服务的启动与停止 |
| static/marked.min.js | 本地 Markdown 渲染依赖 |
| inbox/YYYY-MM-DD/ | raw / science / nature / prompt / inspiration 等 Markdown 文件 |
| CLAUDE.md | 开发上下文与项目约定 |

## 已知限制与网络行为

- **可移植性**：路径仍为硬编码，模型启动脚本未随仓库提供；没有一键安装器或锁定依赖文件。
- **本地推理的边界**：分类、整理与语音可在依赖和权重就绪后使用本地模型；URL 抓取会连接目标网站，因此不应将全部功能描述为“零网络依赖”。
- **人工核验**：当前没有公开的分类准确率、指令质量基准或完整自动化测试；模型输出可能遗漏、误分类或不符合格式。
- **单机使用**：Dashboard 监听 127.0.0.1，提供文件编辑和脚本执行接口，按单用户本地工具设计。
- **模型进程**：stop.sh 与 collect.sh 的清理逻辑会按 mlx_lm.server 进程名停止服务；与其他本地任务共用模型服务时需注意这一行为。
- **数据整理**：inbox 是运行数据目录；共享示例应使用脱敏或合成输入。仓库中已跟踪的缓存与运行数据仍需后续清理。
- **演示与许可证**：尚未提供独立的演示视频、项目截图或 LICENSE 文件。

## 作者与研究背景

**Rui Chen** — 计算机科学与技术博士（Ph.D. in Computer Science and Technology），具有大气物理与物理海洋学背景；曾于 Imperial College London 进行大气物理方向的访问博士研究。

研究经历包括热带气旋形成预测、强度订正、时空机器学习、全球数据集开发，以及 CPU/GPU 集群上的数据处理、模型训练与推理。近期关注 AI-assisted scientific workflows，以及 AI-driven simulation and discovery。

SciLink37 中，Rui 负责需求定义、交互设计及端到端工作流核验，并使用 Claude Code 等 AI 编程工具辅助实现。

- [Google Scholar](https://scholar.google.com/citations?user=4UO7LegAAAAJ)
- [LinkedIn](https://www.linkedin.com/in/rui-chen-19945b363/)
