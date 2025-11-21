# Agent

A powerful agentic AI assistant using OpenRouter and JSDoc.

## Features

- **Provider**: OpenRouter (supports all models).
- **Optimization**: Prompt caching and context window management (50k limit).
- **Tools**: Bash tool (can do everything).
- **Modes**:
  - `manual` (default): Approve every tool call.
  - `auto`: Auto-approve tool calls.
- **Safety**: 1k token output limit on tool calls.

## Setup

1. Install dependencies:
   ```bash
   npm install
   ```
2. Set your OpenRouter API key in `.env`:
   ```bash
   OPENROUTER_API_KEY=your_key_here
   ```

## Usage

Run the agent:

```bash
node src/index.js
```

Options:

- `--mode`: `auto` or `manual` (default: `manual`)
- `--model`: Specify the model (default: `google/gemini-3-pro-preview`)

Example:

```bash
node src/index.js --mode auto --model "google/gemini-3-pro"
```
