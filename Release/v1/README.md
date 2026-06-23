# ⏰ 在干嘛 - WAYD (What Are You Doing)

> 一个 Python 桌面时间追踪工具，随机弹窗问你"在干嘛"，自动截图并记录到 SQLite。

English | [中文](#中文)

---

## English

### Overview

**WAYD** is a desktop time-tracking tool that runs in the Windows system tray. It periodically pops up a window asking "What are you doing?", takes a screenshot, and logs your response to a local SQLite database. It also includes a history viewer for browsing, searching, editing, and managing records.

### Features

- **🖥️ System Tray** — pystray icon with right-click menu (Show Window, Record Now, Status, Quit)
- **⏰ Random Intervals** — Configurable interval range (default 25–45 min) between popups
- **📸 Auto Screenshot** — Captures screenshot before each popup
- **🔔 Toast Notification** — Windows native notification 30s before popup
- **📊 History Viewer** — tkinter-based viewer with search, filter, pagination
- **✏️ CRUD Operations** — Add, edit, delete records with screenshot trash management
- **🗑️ Safe Delete** — Screenshots moved to `screenshots/trash/` before DB deletion
- **⚙️ Configurable** — Adjustable interval via Settings dialog in control panel
- **📝 Notes** — CLI note-taking tool with step sequence tracking and tag support (e.g., `-t x` for error collection)
- **🏷️ Tags** — Categorize notes with tags, filter by tag in the notes viewer
- **🔍 Note Viewer** — Browse/search/filter notes by tag, keyword, date in a dedicated viewer window

### Architecture

Three Python scripts sharing a SQLite database:

| Script | Description |
|--------|-------------|
| `src/main.py` | Background daemon with system tray, worker loop, and popup window |
| `src/view.py` | History manager with Treeview, filtering, and record management |
| `src/note.py` | CLI note-taking tool (`note <step> <content> -t <tag>`) |

### Quick Start

```bash
# Install dependencies
uv sync

# Run the popup daemon
uv run python src/main.py

# Run the history viewer (includes Notes viewer button)
uv run python src/view.py

# Record a note with tag (e.g., "x" = 错题集 / error collection)
uv run python src/note.py a13 "把1抄成了-1" -t x

# List notes filtered by tag
uv run python src/note.py list -t x

# View note statistics
uv run python src/note.py stats
```

### Database Schema

Table `records`:

| Column | Type | Description |
|--------|------|-------------|
| `id` | INTEGER PK | Auto-increment |
| `timestamp` | TEXT | ISO format datetime |
| `doing` | TEXT | What you were doing |
| `next_plan` | TEXT | Next plan |
| `screenshot_path` | TEXT | Path to screenshot |
| `ai_analysis` | TEXT | Placeholder for AI analysis |

Table `notes`:

| Column | Type | Description |
|--------|------|-------------|
| `id` | INTEGER PK | Auto-increment |
| `timestamp` | TEXT | ISO format datetime |
| `step_sequence` | TEXT | Step/problem identifier (e.g., `a13`) |
| `content` | TEXT | Note content |
| `tags` | TEXT | Tags for categorization (e.g., `x` = 错题集) |

### Requirements

- Python >= 3.13
- Windows (uses `win10toast`, `pystray`, `PIL.ImageGrab`)
- See `pyproject.toml` for full dependency list

### Project Structure

```
├── src/
│   ├── main.py          # Background daemon & system tray
│   ├── view.py          # History viewer & management (+ Notes viewer)
│   └── note.py          # CLI note-taking tool
├── screenshots/         # Captured screenshots (auto-created)
│   └── trash/           # Deleted screenshots
├── Release/
│   └── v1/              # Distributable source package
├── pyproject.toml       # Project configuration
├── whatido.db           # SQLite database (auto-created)
├── config.json          # Interval settings (auto-created)
└── README.md
```

---

## 中文

### 概述

**WAYD（在干嘛）** 是一个 Windows 系统托盘工具。它会定时随机弹窗询问"你现在在做什么？"，同时自动截图，并将你的回答记录到本地 SQLite 数据库中。还附带一个历史记录查看器，支持搜索、编辑和管理记录。

### 功能

- **🖥️ 系统托盘** — pystray 图标 + 右键菜单（显示窗口、立即记录、状态、退出）
- **⏰ 随机间隔** — 可配置弹窗间隔范围（默认 25–45 分钟）
- **📸 自动截图** — 每次弹窗前自动截屏
- **🔔 Toast 通知** — 弹窗前 30 秒发送 Windows 原生通知提醒
- **📊 历史查看** — tkinter 表格视图，支持日期/关键词筛选、分页
- **✏️ 增删改查** — 新增、编辑、删除记录，截图自动移入回收站
- **🗑️ 安全删除** — 删除记录时截图移至 `screenshots/trash/`，而非直接丢弃
- **⚙️ 间隔设置** — 控制面板可调整随机间隔范围
- **📝 笔记记录** — 命令行工具，按步骤序列记录笔记，支持标签分类
- **🏷️ 标签系统** — `-t x` 快速标记错题集等分类，支持按标签筛选
- **🔍 笔记查看** — 在 view.py 中内嵌笔记查看器，支持标签/关键词/日期筛选

### 架构

三个 Python 脚本共享一个 SQLite 数据库：

| 脚本 | 说明 |
|------|------|
| `src/main.py` | 后台守护程序：系统托盘、工作循环、弹窗 |
| `src/view.py` | 历史管理器：表格视图、筛选、增删改查（含笔记查看器） |
| `src/note.py` | 笔记 CLI 工具：`note <步骤> <内容> -t <标签>` |

### 快速开始

```bash
# 安装依赖
uv sync

# 启动后台弹窗守护程序
uv run python src/main.py

# 启动历史记录查看器（含笔记查看按钮）
uv run python src/view.py

# 记录一条笔记（标签 x = 错题集）
uv run python src/note.py a13 "把1抄成了-1" -t x

# 按标签查看笔记
uv run python src/note.py list -t x

# 查看笔记统计
uv run python src/note.py stats
```

### 数据库表结构

`records` 表：

| 字段 | 类型 | 说明 |
|------|------|------|
| `id` | INTEGER PK | 自增主键 |
| `timestamp` | TEXT | ISO 格式时间戳 |
| `doing` | TEXT | 在做什么 |
| `next_plan` | TEXT | 下一步计划 |
| `screenshot_path` | TEXT | 截图文件路径 |
| `ai_analysis` | TEXT | AI 分析预留字段 |

### 环境要求

- Python >= 3.13
- Windows 系统（依赖 `win10toast`、`pystray`、`PIL.ImageGrab`）
- 完整依赖列表见 `pyproject.toml`

### 项目结构

```
├── src/
│   ├── main.py          # 后台守护程序 & 系统托盘
│   └── view.py          # 历史查看器 & 记录管理
├── screenshots/         # 截图存储目录（自动创建）
│   └── trash/           # 回收站截图
├── pyproject.toml       # 项目配置
├── whatido.db           # SQLite 数据库（自动创建）
├── config.json          # 间隔设置（自动创建）
└── README.md
```

---

## License

MIT
