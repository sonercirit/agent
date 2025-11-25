"""Tool implementations and schemas for the agent."""

import subprocess
import os
import time
import random
import base64
from .utils import truncate_output

# ---------------------------------------------------------------------------
# Tool Implementations
# ---------------------------------------------------------------------------


async def bash(command: str) -> str:
    """Execute a bash command with timeout."""
    try:
        proc = subprocess.run(command, shell=True, capture_output=True, text=True, timeout=30)
        output = proc.stdout + (f"\nSTDERR:\n{proc.stderr}" if proc.stderr else "")
        return truncate_output(output) if output.strip() else "(Command executed successfully with no output)"
    except subprocess.TimeoutExpired:
        return "Error: Command timed out after 30 seconds."
    except Exception as e:
        return f"Error executing command: {e}"


async def search_files(pattern: str) -> str:
    """Search for files by name pattern using fd."""
    if not pattern:
        return "Error: 'pattern' is required."
    return await bash(f'fd "{pattern}"')


async def search_string(query: str) -> str:
    """Search for a string in files using ripgrep."""
    if not query:
        return "Error: 'query' is required."
    return await bash(f'rg -n -C 5 -- "{query}" .')


async def read_file(path: str, start_line: int = None, end_line: int = None) -> str:
    """Read file content with optional line range."""
    if not path:
        return "Error: 'path' is required."
    try:
        with open(path, "r", encoding="utf-8") as f:
            lines = f.readlines()

        start = max(0, (start_line or 1) - 1)
        end = min(len(lines), end_line or len(lines))

        # Limit to 500 lines max
        if end - start > 500:
            end = start + 500

        return truncate_output(f"(Total lines: {len(lines)})\n" + "".join(lines[start:end]))
    except Exception as e:
        return f"Error reading file: {e}"


async def update_file(path: str, content: str, old_content: str = None) -> str:
    """Update a file (full overwrite or partial replace)."""
    if not path or content is None:
        return "Error: 'path' and 'content' are required."
    try:
        if old_content:
            with open(path, "r", encoding="utf-8") as f:
                current = f.read()
            if old_content not in current:
                return "Error: 'old_content' text block not found in file. Ensure exact match (including whitespace)."
            content = current.replace(old_content, content)

        os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            f.write(content)
        return f"Successfully updated {path}."
    except Exception as e:
        return f"Error updating file: {e}"


async def save_clipboard_image() -> str | None:
    """Save clipboard image to temp file. Returns path or None."""
    temp_path = f"/tmp/clipboard_{int(time.time())}_{random.randint(1000, 9999)}.png"
    commands = [
        f'wl-paste -t image/png > "{temp_path}"',
        f'xclip -selection clipboard -t image/png -o > "{temp_path}"',
        f'pngpaste "{temp_path}"',
    ]
    for cmd in commands:
        try:
            subprocess.run(cmd, shell=True, check=True, capture_output=True)
            if os.path.exists(temp_path) and os.path.getsize(temp_path) > 0:
                return temp_path
        except subprocess.CalledProcessError:
            continue
    return None


async def describe_image(paths: list) -> str:
    """Describe images using LLM vision."""
    from .llm import call_llm

    if not paths:
        return "Error: 'paths' is required."

    image_paths = paths if isinstance(paths, list) else [paths]
    content = [{"type": "text", "text": "Describe these images in detail."}]

    for p in image_paths:
        actual_path = await save_clipboard_image() if p == "clipboard" else p
        if not actual_path:
            return "Error reading from clipboard."
        try:
            with open(actual_path, "rb") as f:
                b64 = base64.b64encode(f.read()).decode("utf-8")
            content.append({"type": "image_url", "image_url": {"url": f"data:image/png;base64,{b64}"}})
        except Exception as e:
            return f"Error reading image {p}: {e}"

    response = await call_llm([{"role": "user", "content": content}], [])
    return response["message"]["content"]


async def google_search(query: str) -> str:
    """Perform a web search using Google Search grounding."""
    from .llm import call_llm

    if not query:
        return "Error: 'query' is required."

    messages = [
        {"role": "system", "content": "Search the web and provide a detailed answer."},
        {"role": "user", "content": query},
    ]
    # Special trigger tool to enable grounding in providers
    tools = [
        {
            "type": "function",
            "function": {
                "name": "__google_search_trigger__",
                "description": "Trigger search",
                "parameters": {"type": "object", "properties": {}},
            },
        }
    ]

    try:
        response = await call_llm(messages, tools)
        return response["message"]["content"]
    except Exception as e:
        return f"Error performing google search: {e}"


# ---------------------------------------------------------------------------
# Tool Registry
# ---------------------------------------------------------------------------

TOOLS = {
    "bash": bash,
    "search_files": search_files,
    "search_string": search_string,
    "read_file": read_file,
    "update_file": update_file,
    "google_search": google_search,
    "describe_image": describe_image,
}

# ---------------------------------------------------------------------------
# Tool Schemas (OpenAI-compatible format)
# ---------------------------------------------------------------------------

TOOL_SCHEMAS = [
    {
        "type": "function",
        "function": {
            "name": "bash",
            "description": "Execute a bash command.",
            "parameters": {
                "type": "object",
                "properties": {"command": {"type": "string", "description": "The bash command to execute."}},
                "required": ["command"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "search_files",
            "description": "Search for files by name pattern.",
            "parameters": {
                "type": "object",
                "properties": {"pattern": {"type": "string", "description": "The filename pattern to search for."}},
                "required": ["pattern"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "search_string",
            "description": "Search for a string in files.",
            "parameters": {
                "type": "object",
                "properties": {"query": {"type": "string", "description": "The string to search for."}},
                "required": ["query"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "read_file",
            "description": "Read the content of a file.",
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {"type": "string", "description": "The path to the file."},
                    "start_line": {"type": "integer", "description": "Start line number."},
                    "end_line": {"type": "integer", "description": "End line number."},
                },
                "required": ["path"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "update_file",
            "description": "Update a file.",
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {"type": "string", "description": "The path to the file."},
                    "content": {"type": "string", "description": "The new content."},
                    "old_content": {"type": "string", "description": "Optional text block to replace."},
                },
                "required": ["path", "content"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "google_search",
            "description": "Perform a web search using Google Search Grounding.",
            "parameters": {
                "type": "object",
                "properties": {"query": {"type": "string", "description": "The search query."}},
                "required": ["query"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "describe_image",
            "description": "Describe one or more images.",
            "parameters": {
                "type": "object",
                "properties": {
                    "paths": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "Array of paths to image files, or 'clipboard'.",
                    }
                },
                "required": ["paths"],
            },
        },
    },
]
