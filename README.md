# SciLink37

[English](README.md) | [简体中文](README_zh.md)

**Local research-idea capture and instruction drafting for AI-assisted scientific workflows.**

SciLink37 is a personal research workflow prototype for macOS: it captures fragmented thoughts, organizes research notes using local language models, and generates task instructions ready for researcher review and handoff to AI-assisted coding tools.

**Project Status: Personal research prototype requiring manual configuration.** The current codebase contains hardcoded machine paths, external model launch scripts, and personalized research prompts. It handles the capture and structuring of research inputs; all generated instructions require human review. The project itself does not execute scientific experiments or validate scientific conclusions.

## Features

- **Quick Capture**: Double-tap `Command` to bring up a native floating input bar, appending thoughts to daily Markdown files.
- **Multimodal Inputs**: Manual typing, pre-filling from selected text, URL title/summary extraction, screen OCR, and voice transcription.
- **Triage & Classification**: Items starting with `!` or `?` bypass the model directly into the main research stream; other notes are classified by a local LLM into `science`, `nature`, and `noise`.
- **Instruction Drafting**: Structures fragmented research ideas into a clear three-part directive: "Current Question, Task Scope, and Initial Instruction."
- **Archival & Synthesis**: Groups scientific and inspirational notes by theme and generates a daily summary.
- **Dashboard**: Browse and edit daily files, and trigger Sort / Digest / Collect pipelines. Triple-tap `Command` to open the web dashboard.

## Architecture & Data Flow

```text
floater.py → inbox/YYYY-MM-DD/raw.md
                         ↓ sort.sh + sort_helper.py
                   science.md + nature.md

science.md (falls back to raw.md if missing or empty)
    → digest.sh + digest_helper.py → prompt.md

science.md + nature.md
    → collect.sh + collect_helper.py → inspiration.md
```

The Dashboard reads and writes directly to these local Markdown files and invokes the same Bash scripts without a dedicated database. Digest prioritizes `science.md`, falling back to `raw.md` when absent or empty. Items tagged as `noise` are filtered out from downstream derived files while remaining in the original `raw.md`. In case of count discrepancies during classification, an `unclassified.md` file may be generated for manual inspection.

| Component | Implementation |
| --- | --- |
| Native Capture & Global Hotkeys | Python, PyObjC, AppKit, Quartz / CGEventTap |
| OCR | macOS Vision Framework |
| Voice Transcription | sounddevice, NumPy, mlx-whisper |
| URL Content Scraping | requests, BeautifulSoup; optionally assisted by local LLM |
| Local Model Inference | MLX / mlx_lm.server, HTTP API: `localhost:8080` |
| Local Dashboard | Flask, `127.0.0.1:8037`; local `marked.js` for Markdown rendering |
| Data Storage & Orchestration | Markdown, Python, Bash; optional LaunchAgent |

## Requirements

- macOS; current model inference and audio transcription are tailored for Apple Silicon / MLX environments.
- Python 3, Bash, curl, Git, and sufficient local RAM and disk storage for selected model weights.
- Installed model serving runtime and accessible weights. Model identifiers configured in `config.sh` must be verified locally.
- Accessibility / Input Monitoring permissions for the floating window global hotkeys; Screen Recording for OCR screen capture; Microphone permission for voice input (per macOS system prompts).

Dependency versions are not currently pinned, and cross-platform compatibility has not been verified. The setup guide below is synthesized from the source code and has not been tested in a clean environment as part of this documentation release.

## Installation & Setup

### 1. Clone Code & Python Environment

```bash
git clone https://github.com/RuiChen0926/SciLink37.git
cd SciLink37
python3 -m venv .venv
source .venv/bin/activate
python -m pip install flask pyobjc mlx-lm
# Optional inputs: URL scraping, audio recording, speech transcription
python -m pip install requests beautifulsoup4 numpy sounddevice mlx-whisper
```

Dependencies listed above reflect current imports in source code and are not pinned. If URL or audio packages are absent, corresponding capabilities will gracefully degrade with logging.

### 2. Configure Project Paths

The current prototype relies on hardcoded absolute paths that must be adapted before execution:

| File | Paths to Adapt |
| --- | --- |
| `floater.py` | `INBOX_DIR` |
| `dashboard.py` | `PROJECT_DIR` |
| `sort.sh` / `digest.sh` / `collect.sh` | Absolute paths to `config.sh`, `inbox`, and Python helper scripts |
| `dashboard.plist` | Python interpreter, script path, and `WorkingDirectory` |

Replace `/Users/rui/Projects/SciLink37` with your local repository path. Ensure CLI commands, GUI tools, and LaunchAgent point to the same Python environment containing the installed dependencies.

### 3. Prepare Local Model Service

- `config.sh` is configured with `mlx-community/gemma-4-e2b-it-4bit` and `mlx-community/gemma-4-26b-a4b-it-4bit`. These reflect the author's local setup and are not guaranteed to run out of the box in all environments.
- `sort` and `digest` default to the 2B model; `collect` defaults to the 26B model (can be overridden with `MODEL=2b`).
- `start.sh` and pipeline scripts depend on `~/start_secretary.sh`. This script is not included in the repository; you must supply your own service or modify the invocations to provide an OpenAI-compatible endpoint at `localhost:8080`.
- Download and cache model weights prior to execution; initial dependency installation and weight retrieval require internet connectivity.

Verify model endpoints:

```bash
curl http://localhost:8080/v1/models
```

The returned model list must include the model IDs selected by the scripts, or execution will fail.

### 4. Configure Research Context

`sort_helper.py` and `digest_helper.py` contain the author's personalized AlphaStorm research context. To adapt this system for other scientific domains, update the domain topics, milestones, and task scope constraints, and verify that the resulting classifications and drafted prompts match your expectations.

## Usage

### Capture & Dashboard

Launch the services in two separate terminal windows:

```bash
# Terminal A: Local Dashboard
python dashboard.py

# Terminal B: Native capture window with global hotkeys
python floater.py
```

Navigate to `http://localhost:8037`. Double-tap `Command` to capture ideas (`Enter` to save, `Esc` to cancel); triple-tap `Command` to open the Dashboard. Avoid starting duplicate background instances of `floater` or `dashboard`.

Input examples (illustrative only, not experimental results):

```text
! Compare model performance on rapid intensification cases before and after including ocean variables.
? How can we split the train/test sets by storm event to minimize data leakage across identical tracks?
A title or link to a relevant paper.
```

Each snippet is logged to the daily `raw.md`; `!` indicates intuitions and `?` indicates research questions. Both markers bypass classification and are prioritized in `science.md`.

### Run Processing Pipeline

Once paths and models are properly configured, execute the pipeline within the project directory:

```bash
bash sort.sh
bash digest.sh
MODEL=2b bash collect.sh

# Process a specific date (date directory must contain existing input files):
bash sort.sh YYYY-MM-DD
bash digest.sh YYYY-MM-DD
MODEL=2b bash collect.sh YYYY-MM-DD
```

Overriding `MODEL=2b` for `collect` allows running the entire pipeline with a single loaded small model. Omitting `MODEL` falls back to defaults defined in `config.sh`. The same stages can also be triggered directly via buttons in the Dashboard.

**Human-in-the-Loop Checkpoints**: Verify that new inputs append correctly to `raw.md`, entries are logically categorized into `science.md` / `nature.md`, `prompt.md` outlines actionable directives within realistic task boundaries, and `inspiration.md` accurately preserves context. Generated task instructions must always be reviewed by a human researcher before handing off to AI coding assistants such as Antigravity.

### Optional LaunchAgent Auto-start

After verifying manual execution, update the Python interpreter and project directory paths in `dashboard.plist`, then copy it to `~/Library/LaunchAgents/`. The repository includes a sample plist for the Dashboard; an autostart configuration for the floater input window must be prepared separately. Running background processes must be restarted to load any code modifications.

## Key Files

| File | Responsibility |
| --- | --- |
| `floater.py` | Floating input window, global hotkey handling, OCR, URL extraction, and speech transcription |
| `dashboard.py` / `dashboard.plist` | Local Web Dashboard and sample LaunchAgent autostart configuration |
| `sort.sh` / `sort_helper.py` | Item triage, classification, and unclassified entry checking |
| `digest.sh` / `digest_helper.py` | Three-part research instruction drafting |
| `collect.sh` / `collect_helper.py` | Idea grouping, synthesis, and daily summaries |
| `config.sh` | Model identifiers and task defaults |
| `start.sh` / `stop.sh` | Wrapper scripts for starting and stopping the local model server |
| `static/marked.min.js` | Vendored client-side Markdown rendering library |
| `inbox/YYYY-MM-DD/` | Daily Markdown files: `raw`, `science`, `nature`, `prompt`, `inspiration`, etc. |
| `CLAUDE.md` | Development context and system conventions |

## Known Limitations & Network Behavior

- **Portability**: Paths are currently hardcoded; external model startup scripts are omitted; no one-click installer or lockfile is provided.
- **Local Inference Boundaries**: Classification, synthesis, and voice transcription operate locally once weights and packages are installed; URL scraping connects to target sites and requires internet access.
- **Human Verification**: No formal classification accuracy benchmarks or automated test suites are included; LLM outputs may occasionally omit, misclassify, or violate format constraints.
- **Single-Machine Use**: The Dashboard binds to `127.0.0.1` and allows arbitrary file edits and script executions; it is designed strictly for single-user local environments.
- **Process Management**: `stop.sh` and cleanup routines in `collect.sh` terminate processes matching `mlx_lm.server`; exercise caution if sharing the local model runtime with other workloads.
- **Data Hygiene**: The `inbox/` directory contains active operational data; examples should only use synthetic or de-identified notes. Tracked runtime caches in the repository remain to be cleaned up.
- **Demos & Licensing**: Standalone demo recordings, screenshots, and formal `LICENSE` files are not yet included.

## Author & Research Background

**Rui Chen** — Ph.D. in Computer Science and Technology, with academic backgrounds in atmospheric physics and physical oceanography; previously a Visiting Ph.D. Researcher in Atmospheric Physics at Imperial College London.

Research experience spans tropical cyclone genesis prediction, intensity consensus correction, spatio-temporal machine learning, global scientific dataset development, and large-scale data processing/model training across CPU/GPU clusters. Current research interests focus on AI-assisted scientific workflows and AI-driven simulation and discovery.

In SciLink37, Rui is responsible for requirements definition, interaction architecture, and end-to-end workflow validation, leveraging AI coding tools such as Claude Code for collaborative implementation.

- [Google Scholar](https://scholar.google.com/citations?user=4UO7LegAAAAJ)
- [LinkedIn](https://www.linkedin.com/in/rui-chen-19945b363/)
