import subprocess
import os
import time
import random
import json
from .utils import limit_output


async def bash(command):
    try:
        process = subprocess.run(
            command, shell=True, capture_output=True, text=True, timeout=30
        )
        output = process.stdout + (
            f"\nSTDERR:\n{process.stderr}" if process.stderr else ""
        )
        if not output.strip():
            return "(Command executed successfully with no output)"
        return limit_output(output)
    except subprocess.TimeoutExpired:
        return limit_output("Error: Command timed out after 30 seconds.", True)
    except Exception as e:
        return limit_output(f"Error executing command:\n{str(e)}", True)


async def search_files(pattern):
    if not pattern:
        return "Error: 'pattern' is required."
    return await bash(f'fd "{pattern}"')


async def search_string(query):
    if not query:
        return "Error: 'query' is required."
    return await bash(f'rg -n -C 5 -- "{query}" .')


async def read_file(path, start_line=None, end_line=None):
    if not path:
        return "Error: 'path' is required."
    try:
        with open(path, "r", encoding="utf-8") as f:
            lines = f.readlines()

        start = 0
        end = len(lines)

        if start_line is not None:
            start = int(start_line) - 1
            if start < 0:
                start = 0

        if end_line is not None:
            end = int(end_line)

        MAX_LINES = 500
        if end - start > MAX_LINES:
            end = start + MAX_LINES

        if start >= len(lines):
            return ""
        if end > len(lines):
            end = len(lines)
        if start < 0:
            start = 0

        selected_lines = lines[start:end]
        return limit_output(f"(Total lines: {len(lines)})\n" + "".join(selected_lines))
    except Exception as e:
        return f"Error reading file: {str(e)}"


async def update_file(path, content, old_content=None):
    if not path or content is None:
        return "Error: 'path' and 'content' are required."

    try:
        if old_content:
            try:
                with open(path, "r", encoding="utf-8") as f:
                    current_content = f.read()
            except Exception as e:
                return f"Error reading file for partial update: {str(e)}. (File must exist for partial updates)"

            if old_content not in current_content:
                return "Error: 'old_content' text block not found in file. Please ensure exact match (including whitespace/indentation)."

            new_content = current_content.replace(old_content, content)
            with open(path, "w", encoding="utf-8") as f:
                f.write(new_content)
            return f"Successfully updated {path} (partial replace)."
        else:
            os.makedirs(os.path.dirname(path), exist_ok=True)
            with open(path, "w", encoding="utf-8") as f:
                f.write(content)
            return f"Successfully updated {path} (full overwrite)."
    except Exception as e:
        return f"Error updating file: {str(e)}"


async def save_clipboard_image():
    temp_file_path = os.path.join(
        "/tmp", f"clipboard_{int(time.time())}_{random.randint(1000, 9999)}.png"
    )

    commands = [
        f'wl-paste -t image/png > "{temp_file_path}"',
        f'xclip -selection clipboard -t image/png -o > "{temp_file_path}"',
        f'pngpaste "{temp_file_path}"',
    ]

    for cmd in commands:
        try:
            subprocess.run(cmd, shell=True, check=True, capture_output=True)
            if os.path.exists(temp_file_path) and os.path.getsize(temp_file_path) > 0:
                return temp_file_path
        except subprocess.CalledProcessError:
            continue

    return None


async def describe_image(paths):
    # This creates a circular dependency if we import call_llm here.
    # We will handle this by passing the llm caller or importing inside the function.
    from .llm import call_llm

    if not paths:
        return "Error: 'paths' is required."

    image_paths = paths if isinstance(paths, list) else [paths]
    processed_paths = []

    for p in image_paths:
        if p == "clipboard":
            path = await save_clipboard_image()
            if not path:
                return "Error reading from clipboard."
            processed_paths.append(path)
        else:
            processed_paths.append(p)

    # Construct message for LLM
    content = [{"type": "text", "text": "Describe these images in detail."}]
    for p in processed_paths:
        try:
            import base64

            with open(p, "rb") as f:
                b64_data = base64.b64encode(f.read()).decode("utf-8")
                content.append(
                    {
                        "type": "image_url",
                        "image_url": {"url": f"data:image/png;base64,{b64_data}"},
                    }
                )
        except Exception as e:
            return f"Error reading image {p}: {str(e)}"

    response = await call_llm(
        [{"role": "user", "content": content}], [], model="google/gemini-3-pro-preview"
    )
    return response["message"]["content"]


async def google_search(query):
    # This is a trigger for the "grounding" logic in the provider
    # In the python version, we can just return a special string or handle it in the provider
    # For now, let's return a placeholder that the agent loop can recognize if needed,
    # or just let the LLM see the result.
    # Actually, the JS version had complex logic to enable grounding.
    # We will implement the "tool" version which triggers a second call.
    return f"__google_search_trigger__: {query}"


tool_implementations = {
    "bash": bash,
    "search_files": search_files,
    "search_string": search_string,
    "read_file": read_file,
    "update_file": update_file,
    "google_search": google_search,
    "describe_image": describe_image,
}

tools_schema = [
    {
        "type": "function",
        "function": {
            "name": "bash",
            "description": "Execute a bash command.",
            "parameters": {
                "type": "object",
                "properties": {
                    "command": {
                        "type": "string",
                        "description": "The bash command to execute.",
                    }
                },
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
                "properties": {
                    "pattern": {
                        "type": "string",
                        "description": "The filename pattern to search for.",
                    }
                },
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
                "properties": {
                    "query": {
                        "type": "string",
                        "description": "The string to search for.",
                    }
                },
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
                    "start_line": {
                        "type": "integer",
                        "description": "Start line number.",
                    },
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
                    "old_content": {
                        "type": "string",
                        "description": "Optional text block to replace.",
                    },
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
                "properties": {
                    "query": {"type": "string", "description": "The search query."}
                },
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
