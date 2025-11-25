# Agent

A terminal-native, high-reasoning AI operator designed for complex tasks. It orchestrates local tools, manages heavy-duty LLM reasoning (Gemini/OpenRouter), and maintains a robust, auditable history.

**Key Features:**

- **Observability**: Real-time cost tracking, cache telemetry, and reason-trace streaming.
- **Safety**: Granular "Undo" (git/file-based), manual approval modes, and graceful stops.
- **Ergonomics**: `prompt_toolkit` UI with Vim bindings, syntax highlighting, and clipboard image support.

## Quick Start

Get up and running immediately using `uv`.

```bash
# 1. Clone and setup
git clone <repo-url>
cd agent
./run_agent.sh --help

# 2. Configure credentials
export GEMINI_API_KEY=your_key
# or create a .env file

# 3. Run (Interactive Manual Mode)
./run_agent.sh

# 4. Run (Autonomous Mode)
./run_agent.sh --mode auto --initial-prompt "Audit this repo and summarize README.md"
```

## Table of Contents

- [Quick Start](#quick-start)
- [Installation & Setup](#installation--setup)
- [Usage & Configuration](#usage--configuration)
- [Keyboard Shortcuts](#keyboard-shortcuts)
- [Tool Catalog](#tool-catalog)
- [Architecture & Internals](#architecture--internals)
- [Development](#development)

## Installation & Setup

### Prerequisites

- **Python 3.10+**
- **[uv](https://github.com/astral-sh/uv)**: `curl -LsSf https://astral.sh/uv/install.sh | sh`
- **System Tools**: `fd`, `ripgrep` (for file search), `wl-clipboard`/`xclip`/`pngpaste` (for images).

### Configuration

Create a `.env` file or export variables:

```bash
GEMINI_API_KEY=...             # Default provider
OPENROUTER_API_KEY=...         # If using OpenRouter
DEFAULT_MODEL=...              # Optional: google/gemini-3-pro-preview
```

## Usage & Configuration

### CLI Options

| Flag           | Description                                      | Default        |
| :------------- | :----------------------------------------------- | :------------- |
| `--mode`, `-m` | `manual` (approve tools) or `auto` (autonomous). | `manual`       |
| `--provider`   | Backend: `gemini` or `openrouter`.               | `gemini`       |
| `--model`      | specific model identifier.                       | `gemini-3-pro` |
| `--debug`      | Verbose logging.                                 | `INFO`         |

### Interactive Session

- **Submit**: `Alt+Enter` (or `Esc` then `Enter`).
- **Multiline**: Supported naturally.
- **Paste Image**: `Alt+I` (reads from system clipboard).

## Keyboard Shortcuts

| Context      | Keys        | Action                                     |
| :----------- | :---------- | :----------------------------------------- |
| **Anywhere** | `Ctrl+C`    | Interrupt/Cancel.                          |
| **Input**    | `Alt+Enter` | Submit message.                            |
| **Input**    | `Alt+E`     | Edit in `$EDITOR`.                         |
| **Input**    | `Alt+I`     | Paste image from clipboard.                |
| **Input**    | `Alt+Z`     | **Undo**: Revert last turn & file changes. |
| **Thinking** | `Ctrl+W`    | Graceful stop (finish current step).       |

## Tool Catalog

The agent maps these Python functions to LLM tools:

| Tool                    | Description                                |
| :---------------------- | :----------------------------------------- |
| `bash(command)`         | Execute shell commands (30s timeout).      |
| `search_files(pattern)` | Find files using `fd`.                     |
| `search_string(query)`  | Grep files using `rg`.                     |
| `read_file/update_file` | Read/Write file content (with validation). |
| `google_search(query)`  | Trigger online grounding/search.           |
| `describe_image(paths)` | Analyze local or clipboard images.         |

## Architecture & Internals

### Project Structure

- **`src/agent.py`**: Main loop, UI bootstrapping, and orchestration.
- **`src/llm.py`**: Dispatcher for Gemini/OpenRouter.
- **`src/tools.py`**: Tool implementations and schema generation.
- **`src/undo.py`**: Manages state snapshots (Git-based or manual backups).
- **`src/cache.py`**: Handles Anthropic/Gemini token caching strategies.

### Safety & Recovery

- **Undo Mechanism**: `Alt+Z` triggers a rollback. If Git is present, it reverts the tree. Otherwise, it restores file backups.
- **Guardrails**: Tool outputs are truncated (~4k chars) to prevent context flooding.
- **Observability**: Monitor cost and cache status in real-time.

## Development

Managed via `uv`.

```bash
# Sync dependencies
uv sync

# Run linting
uv run ruff check
```

## Dependencies

Main stacks: `prompt_toolkit`, `requests`, `python-dotenv`.
