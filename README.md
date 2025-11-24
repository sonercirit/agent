# Agent

A powerful agentic AI assistant designed for high reasoning and complex tasks. It supports both OpenRouter and Google Gemini as LLM providers, with a suite of system tools and web search capabilities.

## Features

- **Multi-Provider Support**:
  - **Google Gemini**: Native support for Gemini models (default).
  - **OpenRouter**: Access to a wide range of models (e.g., Claude, GPT-5).
- **Comprehensive Toolset**:
  - `bash`: Execute any system command (requires caution).
  - `search_files`: Find files by name pattern (uses `fd`).
  - `search_string`: Search for text within files (uses `ripgrep`).
  - `read_file`: Read file contents (smart line limiting).
  - `update_file`: Create or update files (supports full overwrite and partial replace).
  - `google_search`: Perform web searches using Gemini's Grounding feature.
  - `describe_image`: Describe image files or images from the clipboard (uses Gemini Vision).
- **Interactive Editor (Vim Mode)**:
  - **Native Vim Keybindings**: Uses `prompt_toolkit` with `vi_mode=True`.
  - **Ctrl+S** to submit your prompt.
  - **Ctrl+E** to open the current prompt in your external editor (`$EDITOR`).
  - **Ctrl+V** to paste an image path from the clipboard.
  - **Ctrl+C** to interrupt the agent during execution.
- **Optimization**:
  - **Prompt Caching**: Intelligent cache management to optimize token usage.
- **Modes**:
  - `manual` (default): User approves every tool execution for safety.
  - `auto`: Autonomous mode where the agent executes tools automatically.
- **Safety**:
  - Strict 1k token output limit on tool calls to prevent context flooding.
  - User confirmation in manual mode.

## Setup

### Prerequisites

- **Python**: Version 3.10 or higher.
- **uv**: Fast Python package installer and resolver.
  ```bash
  curl -LsSf https://astral.sh/uv/install.sh | sh
  ```
- **External Tools**:
  - `fd` (or `fd-find`): For fast file searching.
  - `ripgrep` (`rg`): For fast text searching.
  - **Clipboard Tools** (Optional, for `describe_image` clipboard support):
    - Linux (Wayland): `wl-clipboard` (provides `wl-paste`)
    - Linux (X11): `xclip`
    - macOS: `pngpaste`

### Installation

1. **Clone the repository**:
   ```bash
   git clone <repo-url>
   cd agent
   ```

2. **Configure Environment**:
   Create a `.env` file in the root directory and add your API keys:
   ```bash
   GEMINI_API_KEY=your_gemini_key          # Required for default Gemini provider
   OPENROUTER_API_KEY=your_openrouter_key  # Required if using OpenRouter provider
   DEFAULT_MODEL=google/gemini-2.0-flash-thinking-exp:free # Optional: Override default model
   ```

## Usage

Run the agent using the provided script (automatically handles dependencies via `uv`):

```bash
./run_agent.sh [options]
```

Or directly with `uv`:

```bash
uv run python -m src.agent [options]
```

### Interactive Controls

- **Ctrl+S**: Send your message to the agent.
- **Ctrl+E**: Open the current input in your default external editor (e.g., Vim, Nano).
- **Ctrl+V**: Paste an image from the clipboard (inserts the temporary file path).
- **Ctrl+C**: Interrupt the agent while it is thinking or executing tools.
- **Ctrl+D** or type `exit`: Exit the application.

### Options

- `--mode`, `-m`: Operation mode.
  - `manual` (default): Ask for approval before executing tools.
  - `auto`: Execute tools automatically.
- `--model`: Specify the LLM model to use.
  - Default: `google/gemini-2.0-flash-thinking-exp:free` (via Gemini or OpenRouter) or configured default.
- `--provider`: Choose the LLM provider.
  - `gemini` (default)
  - `openrouter`

### Recommended Settings

For the most efficient workflow, it is recommended to run the agent in **autonomous mode**. This allows the agent to chain multiple tools and reasoning steps without interruption.

```bash
./run_agent.sh --mode auto
```

### Examples

**Run with default settings (Gemini, Manual mode):**

```bash
./run_agent.sh
```

**Run in autonomous mode with a specific model (via OpenRouter):**

```bash
./run_agent.sh --mode auto --provider openrouter --model anthropic/claude-3.5-sonnet
```

**Run using OpenRouter provider:**

```bash
./run_agent.sh --provider openrouter
```
