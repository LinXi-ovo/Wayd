# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

"WhatAreYouDoing-WAYD" (在干嘛) — a Python desktop time-tracking tool using tkinter. Randomly pops up asking "what are you doing?", captures a screenshot, and logs the response to SQLite. Includes a separate history viewer with search/edit/delete/trash.

## Architecture

Two standalone scripts that share a SQLite DB:

- **`src/main.py`** — Background daemon: infinite loop with random-interval sleep, checks work hours (9:00-23:00), captures screenshot via Pillow `ImageGrab`, shows tkinter popup, saves to `whatido.db`. Runs as a hidden system-tray-like window.
- **`src/view.py`** — History manager: tkinter Treeview with pagination, date/keyword filter, add/edit/delete records, double-click to open screenshot via `os.startfile`. Newer unused functions for soft-delete/trash workflow exist as design doc in `nextStep.md`.

Key config constants in main.py: `WORK_START`/`WORK_END` (hours), `MIN_INTERVAL`/`MAX_INTERVAL` (seconds), `SCREENSHOT_DIR`, `DB_FILE`.

## Database Schema (`whatido.db`)

Table `records`: id (PK), timestamp, doing, next_plan, screenshot_path, ai_analysis

## Commands

```bash
# Run the popup daemon
uv run python src/main.py

# Run the history viewer
uv run python src/view.py

# Install dependencies
uv sync
```

## Key Dependencies

- Python >= 3.13
- Pillow (screenshot capture)
- pyautogui (declared but unused currently)
- uv (package manager)

## Notable Design Decisions

- Screenshots are always captured before showing the popup, regardless of whether user submits
- `delete_records` physically moves screenshots to `screenshots/trash/` before DB deletion
- The AI analysis placeholder at `trigger_ai_analysis()` is a no-op hook for future integration
