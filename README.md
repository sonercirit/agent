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
  - `google_search`: Perform web searches using Gemini's Grounding feature (implemented via a sub-agent pattern to coexist with function calling).
  - `describe_image`: Describe image files or images from the clipboard (uses Gemini Vision).
- **Interactive Editor**:
  - Custom multiline input editor.
  - **Ctrl+S** to submit your prompt.
  - **Ctrl+W** to interrupt the agent during execution.
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

- **Node.js**: Version 18 or higher.
- **External Tools**:
  - `fd` (or `fd-find`): For fast file searching.
  - `ripgrep` (`rg`): For fast text searching.
  - **Clipboard Tools** (Optional, for `describe_image` clipboard support):
    - Linux (Wayland): `wl-clipboard` (provides `wl-paste`)
    - Linux (X11): `xclip`
    - macOS: `pngpaste`

  **Installation (Arch Linux):**

  ```bash
  sudo pacman -S fd ripgrep xclip wl-clipboard
  ```

  **Installation (Ubuntu/Debian):**

  ```bash
  sudo apt install fd-find ripgrep xclip wl-clipboard
  ln -s $(which fdfind) ~/.local/bin/fd # Optional: alias fdfind to fd
  ```

  **Installation (macOS):**

  ```bash
  brew install fd ripgrep pngpaste
  ```

### Installation

1. **Install dependencies**:

   ```bash
   npm install
   ```

2. **Configure Environment**:
   Create a `.env` file in the root directory and add your API keys:
   ```bash
   GEMINI_API_KEY=your_gemini_key          # Required for default Gemini provider
   OPENROUTER_API_KEY=your_openrouter_key  # Required if using OpenRouter provider
   DEFAULT_MODEL=google/gemini-3-pro-preview # Optional: Override default model
   ```

## Usage

Run the agent using the CLI:

```bash
node src/index.js [options]
```

### Interactive Controls

- **Ctrl+S**: Send your message to the agent.
- **Ctrl+W**: Interrupt the agent while it is thinking or executing tools.
- **Ctrl+C**: Exit the application.

### Options

- `--mode`, `-m`: Operation mode.
  - `manual` (default): Ask for approval before executing tools.
  - `auto`: Execute tools automatically.
- `--model`: Specify the LLM model to use.
  - Default: `google/gemini-3-pro-preview` (via Gemini or OpenRouter) or configured default.
- `--provider`: Choose the LLM provider.
  - `gemini` (default)
  - `openrouter`

### Recommended Settings

For the most efficient workflow, it is recommended to run the agent in **autonomous mode**. This allows the agent to chain multiple tools and reasoning steps without interruption.

```bash
node src/index.js --mode auto
```

### Examples

**Run with default settings (Gemini, Manual mode):**

```bash
node src/index.js
```

**Run in autonomous mode with a specific model (via OpenRouter):**

```bash
node src/index.js --mode auto --provider openrouter --model x-ai/grok-4.1-fast:free
```

**Run using OpenRouter provider:**

```bash
node src/index.js --provider openrouter
```

## Architecture

The agent uses a loop-based architecture:

1. **Input**: User provides a prompt via the multiline editor.
2. **Reasoning**: The LLM analyzes the request and decides if tools are needed.
3. **Tool Execution**:
   - If a tool is called, the agent executes it (after approval in manual mode).
   - For `google_search`, a specialized sub-agent call is made to Gemini to leverage Grounding without conflicting with standard function calling.
4. **Response**: The tool output is fed back to the LLM, which generates the final response or decides to take further actions.

## License

ISC
