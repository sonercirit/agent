# Agent

A terminal-native AI assistant with tool execution, designed for complex agentic tasks.

## Features

- **Multi-provider**: Gemini (direct) and OpenRouter (Claude, GPT, etc.)
- **Tool execution**: bash, file operations, web search, image analysis
- **Undo system**: Git-based or manual file tracking
- **Vi keybindings**: Full vim mode with `prompt_toolkit`
- **Cost tracking**: Real-time token usage and cost display
- **Cache awareness**: Prompt caching support for Gemini and Anthropic

## Quick Start

```bash
# Install uv if needed
curl -LsSf https://astral.sh/uv/install.sh | sh

# Clone and run
git clone git@github.com:sonercirit/agent.git && cd agent
export GEMINI_API_KEY=your_key  # or add to .env
./run_agent.sh
```

## Usage

```bash
# Interactive (default)
./run_agent.sh

# With initial prompt
./run_agent.sh --initial-prompt "Summarize this repo"

# Auto mode (no approval prompts)
./run_agent.sh --mode auto

# Use OpenRouter
./run_agent.sh --provider openrouter --model anthropic/claude-sonnet-4
```

## Keyboard Shortcuts

| Keys | Action |
|------|--------|
| `Alt+Enter` | Submit message |
| `Alt+E` | Open in $EDITOR |
| `Alt+I` | Paste clipboard image |
| `Alt+Z` | Undo last turn |
| `Ctrl+W` | Stop gracefully |
| `Ctrl+C` | Cancel/interrupt |

## Tools

| Tool | Description |
|------|-------------|
| `bash(command)` | Execute shell command (30s timeout) |
| `search_files(pattern)` | Find files with `fd` |
| `search_string(query)` | Search with `ripgrep` |
| `read_file(path)` | Read file content |
| `update_file(path, content)` | Write/patch files |
| `google_search(query)` | Web search via grounding |
| `describe_image(paths)` | Analyze images |

## Configuration

Environment variables (or `.env` file):

```bash
GEMINI_API_KEY=...        # For Gemini provider
OPENROUTER_API_KEY=...    # For OpenRouter provider
DEFAULT_MODEL=...         # Override default model
```

CLI options:

| Flag | Description | Default |
|------|-------------|---------|
| `--mode` | `manual` or `auto` | `manual` |
| `--provider` | `gemini` or `openrouter` | `gemini` |
| `--model` | Model identifier | `gemini-3-pro-preview` |
| `--debug` | Verbose logging | off |

## Requirements

- Python 3.10+
- Optional: `fd`, `ripgrep` (for file search tools)
- Optional: `wl-clipboard`/`xclip`/`pngpaste` (for image paste)

## License

MIT
