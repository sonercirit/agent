"""Main agent loop and UI."""

import asyncio

try:
    import uvloop

    asyncio.set_event_loop_policy(uvloop.EventLoopPolicy())
except ImportError:
    pass

import os
import json
import time
import logging
import html
from prompt_toolkit import PromptSession, print_formatted_text
from prompt_toolkit.key_binding import KeyBindings
from prompt_toolkit.formatted_text import HTML, FormattedText
from prompt_toolkit.styles import Style
from prompt_toolkit.lexers import PygmentsLexer
from prompt_toolkit.application import Application
from prompt_toolkit.layout.containers import Window
from prompt_toolkit.layout.controls import FormattedTextControl
from prompt_toolkit.layout.layout import Layout
from prompt_toolkit.patch_stdout import patch_stdout
from prompt_toolkit.key_binding.vi_state import InputMode
from pygments.lexers.markup import MarkdownLexer

from .config import config
from .llm import call_llm
from .tools import TOOLS, TOOL_SCHEMAS, save_clipboard_image
from .undo import UndoManager

# ---------------------------------------------------------------------------
# Setup
# ---------------------------------------------------------------------------

# Restore working directory if provided
if "AGENT_WORK_DIR" in os.environ:
    os.chdir(os.environ["AGENT_WORK_DIR"])


class PTKHandler(logging.Handler):
    """Logging handler that uses prompt_toolkit for output."""

    def emit(self, record):
        try:
            msg = html.escape(self.format(record))
            color = {logging.ERROR: "ansired", logging.WARNING: "ansiyellow"}.get(record.levelno, "ansiwhite")
            print_formatted_text(HTML(f"<{color}>{msg}</{color}>"))
        except Exception:
            self.handleError(record)


# Configure logging
logging.getLogger().handlers = []
handler = PTKHandler()
handler.setFormatter(logging.Formatter("%(asctime)s - %(name)s - %(levelname)s - %(message)s"))
logging.getLogger().addHandler(handler)
logging.getLogger().setLevel(logging.DEBUG if config.debug else logging.INFO)
logger = logging.getLogger("Agent")

# ---------------------------------------------------------------------------
# System Prompt
# ---------------------------------------------------------------------------

SYSTEM_PROMPT = """You are a powerful agentic AI assistant.
You have access to a bash tool which allows you to do almost anything on the system.
You should use this tool to accomplish the user's requests.
You are optimized for high reasoning and complex tasks.
Always verify your actions and output.
If you need to run a command, just do it.
The user has set a strict output limit of 1k tokens per tool call. If you see truncated output, refine your command (e.g., use grep, head, tail) to get the specific information you need.

String and scalar parameters should be specified as is, while lists and objects should use JSON format.

Answer the user's request using the relevant tool(s), if they are available. Check that all the required parameters for each tool call are provided or can reasonably be inferred from context. IF there are no relevant tools or there are missing values for required parameters, ask the user to supply these values; otherwise proceed with the tool calls. If the user provides a specific value for a parameter (for example provided in quotes), make sure to use that value EXACTLY. DO NOT make up values for or ask about optional parameters.

If you intend to call multiple tools and there are no dependencies between the calls, make all of the independent calls in the same block, otherwise you MUST wait for previous calls to finish first to determine the dependent values (do NOT use placeholders or guess missing parameters).

Guidelines for tool usage:
- For bash commands, prefer concise commands that get specific information
- Use grep, head, tail, awk to filter output when needed
- For file operations, verify paths exist before modifying
- When searching code, use grep or find to locate relevant files first
- Always check command exit status and handle errors appropriately
- For complex multi-step tasks, break them down and verify each step

When working with files:
- Read files before modifying to understand context
- Use partial updates (old_content parameter) when possible for precision
- Create backups of important files before major changes
- Verify changes after making them

For debugging and investigation:
- Start with broad searches, then narrow down
- Check logs and error messages carefully
- Test hypotheses incrementally
- Document findings as you go"""

# ---------------------------------------------------------------------------
# State
# ---------------------------------------------------------------------------

messages = [{"role": "system", "content": SYSTEM_PROMPT}]
undo_manager = UndoManager()
total_cost = 0.0
last_request_time = 0.0
has_seen_cached_tokens = False

# Wrap update_file to track changes for undo
_original_update_file = TOOLS["update_file"]


async def _tracked_update_file(path, content, old_content=None):
    undo_manager.record_file_change(path)
    return await _original_update_file(path, content, old_content)


TOOLS["update_file"] = _tracked_update_file

# ---------------------------------------------------------------------------
# Core Logic
# ---------------------------------------------------------------------------


def display_usage(usage: dict, elapsed_minutes: float):
    """Display cost and cache information."""
    global total_cost, has_seen_cached_tokens

    cost = usage.get("cost", 0)
    if cost:
        total_cost += cost
        print_formatted_text(HTML(f"<ansicyan>Cost: ${cost:.6f} | Total: ${total_cost:.6f}</ansicyan>"))

    cached = (
        usage.get("cachedContentTokenCount", 0)
        or usage.get("cache_read_input_tokens", 0)
        or usage.get("prompt_tokens_details", {}).get("cached_tokens", 0)
        or 0
    )
    created = usage.get("cache_creation_input_tokens", 0)

    if cached or created:
        print_formatted_text(HTML(f"<ansigreen>Cache: {cached} read, {created} created</ansigreen>"))

    if cached > 0:
        has_seen_cached_tokens = True
    elif has_seen_cached_tokens:
        ttl = 60.0 if config.provider == "gemini" else 5.0
        reason = "Prefix mismatch" if elapsed_minutes < ttl - 1 else "Cache TTL expired"
        print_formatted_text(HTML(f"<ansired>WARNING: Cache dropped to 0! ({reason})</ansired>"))


async def execute_tools(tool_calls: list):
    """Execute tool calls and add results to messages."""
    print_formatted_text(HTML("\n<ansiyellow>Tool Calls:</ansiyellow>"))

    # In manual mode, ask for approval before executing tools
    if config.mode == "manual":
        for tc in tool_calls:
            name = tc["function"]["name"]
            args = json.loads(tc["function"]["arguments"]) if tc["function"]["arguments"] else {}
            print_formatted_text(FormattedText([("bold", f"  {name}"), ("", f"({json.dumps(args)})")]))

        try:
            approval_session = PromptSession()
            response = await approval_session.prompt_async(
                HTML("<ansicyan>Execute? [Y/n]: </ansicyan>")
            )
            response = response.strip().lower()
            if response in ("n", "no"):
                print_formatted_text(HTML("<ansiyellow>Tool execution cancelled.</ansiyellow>"))
                for tc in tool_calls:
                    messages.append({
                        "role": "tool",
                        "tool_call_id": tc.get("id", "unknown"),
                        "name": tc["function"]["name"],
                        "content": "Tool execution cancelled by user."
                    })
                return
        except (EOFError, KeyboardInterrupt):
            print_formatted_text(HTML("\n<ansiyellow>Tool execution cancelled.</ansiyellow>"))
            for tc in tool_calls:
                messages.append({
                    "role": "tool",
                    "tool_call_id": tc.get("id", "unknown"),
                    "name": tc["function"]["name"],
                    "content": "Tool execution cancelled by user."
                })
            return

    for tc in tool_calls:
        name = tc["function"]["name"]
        args = json.loads(tc["function"]["arguments"]) if tc["function"]["arguments"] else {}

        if config.mode == "auto":
            print_formatted_text(FormattedText([("bold", f"  {name}"), ("", f"({json.dumps(args)})")]))
        logger.debug(f"Executing {name} with {args}")

        if name in TOOLS:
            try:
                result = await TOOLS[name](**args)
            except Exception as e:
                result = f"Error: {e}"
                logger.error(f"Tool error: {e}")
        else:
            result = f"Error: Tool '{name}' not found."

        messages.append({"role": "tool", "tool_call_id": tc.get("id", "unknown"), "name": name, "content": str(result)})
        print_formatted_text(FormattedText([("#888888", f"Result: {str(result)[:100]}...")]))


async def process_turn_logic(user_input: str, stop_check=None):
    """Process a single turn of conversation."""
    global last_request_time

    undo_manager.start_turn(messages)
    messages.append({"role": "user", "content": user_input})

    while True:
        if stop_check and stop_check():
            print_formatted_text(HTML("\n<ansiyellow>Stopping after current step.</ansiyellow>"))
            break

        request_time = time.time()
        elapsed = (request_time - last_request_time) / 60.0 if last_request_time else 0
        last_request_time = request_time

        try:
            response = await call_llm(messages, TOOL_SCHEMAS)
        except asyncio.CancelledError:
            raise
        except Exception as e:
            logger.exception("LLM call failed")
            print_formatted_text(HTML(f"\n<ansired>Error: {e}</ansired>"))
            break

        msg = response["message"]
        if response.get("usage"):
            display_usage(response["usage"], elapsed)

        # Display reasoning if present
        if msg.get("reasoning"):
            print_formatted_text(HTML(f"\n<style fg='#888888'>{html.escape(msg['reasoning'][:500])}...</style>"))

        # Add assistant message (preserve reasoning_details for Gemini via OpenRouter)
        assistant_msg = {"role": "assistant", "content": msg.get("content") or ""}
        if msg.get("tool_calls"):
            assistant_msg["tool_calls"] = msg["tool_calls"]
        if msg.get("reasoning"):
            assistant_msg["reasoning"] = msg["reasoning"]
        if msg.get("reasoning_details"):
            assistant_msg["reasoning_details"] = msg["reasoning_details"]
        messages.append(assistant_msg)

        # Display response
        if msg.get("content"):
            print_formatted_text(HTML(f"\n<ansigreen>Assistant:</ansigreen>\n{html.escape(msg['content'])}"))

        # Handle tool calls or finish
        if msg.get("tool_calls"):
            await execute_tools(msg["tool_calls"])
        else:
            break


async def process_turn(user_input: str):
    """Process turn with UI wrapper for cancellation."""
    kb = KeyBindings()
    stop_requested = False
    task = None

    @kb.add("c-w")
    def _(event):
        nonlocal stop_requested
        stop_requested = True

    @kb.add("c-c")
    def _(event):
        if task:
            task.cancel()

    def status():
        if stop_requested:
            return HTML(" <ansiyellow>Stopping...</ansiyellow> (Ctrl+C to force)")
        return HTML(" <ansigreen>Thinking...</ansigreen> (Ctrl+W: stop, Ctrl+C: cancel)")

    app = Application(layout=Layout(Window(FormattedTextControl(status), height=1)), key_bindings=kb)

    async def run():
        nonlocal task
        try:
            await process_turn_logic(user_input, lambda: stop_requested)
        except asyncio.CancelledError:
            print_formatted_text(HTML("\n<ansired>Interrupted.</ansired>"))
        finally:
            app.exit()

    with patch_stdout():
        task = asyncio.create_task(run())
        await app.run_async()
        if not task.done():
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


async def main():
    print_formatted_text(HTML(f"<ansicyan>Agent started ({config.mode} mode, {config.model})</ansicyan>"))

    if config.initial_prompt:
        print_formatted_text(HTML("\n<ansicyan>Executing initial prompt...</ansicyan>"))
        await process_turn(config.initial_prompt)

    kb = KeyBindings()

    @kb.add("escape", "z")
    def _(event):
        last_user = next((m["content"] for m in reversed(messages) if m["role"] == "user"), "")
        restored = undo_manager.undo()
        if restored:
            messages[:] = restored
            event.current_buffer.text = last_user if isinstance(last_user, str) else ""
            print_formatted_text(HTML("\n<ansiyellow>Undone last turn.</ansiyellow>"))
        else:
            print_formatted_text(HTML("\n<ansired>Nothing to undo.</ansired>"))

    @kb.add("escape", "enter")
    def _(event):
        event.current_buffer.validate_and_handle()

    @kb.add("escape", "e")
    def _(event):
        event.current_buffer.open_in_editor()

    @kb.add("escape", "i")
    async def _(event):
        path = await save_clipboard_image()
        if path:
            event.current_buffer.insert_text(path)

    session = PromptSession(
        key_bindings=kb,
        vi_mode=True,
        multiline=True,
        lexer=PygmentsLexer(MarkdownLexer),
        style=Style.from_dict({"prompt": "ansicyan bold"}),
    )

    def toolbar():
        mode = session.app.vi_state.input_mode
        labels = {InputMode.INSERT: "INSERT", InputMode.NAVIGATION: "COMMAND", InputMode.REPLACE: "REPLACE"}
        return HTML(f" <b>[{labels.get(mode, mode)}]</b>")

    while True:
        try:
            user_input = await session.prompt_async(
                HTML("<b>User (Alt+Enter: Send, Alt+E: Editor, Alt+I: Image, Alt+Z: Undo, Ctrl+D: Exit):</b>\n"),
                bottom_toolbar=toolbar,
            )
            if user_input.strip().lower() == "exit":
                break
            if user_input.strip():
                await process_turn(user_input)
        except KeyboardInterrupt:
            continue
        except EOFError:
            break


if __name__ == "__main__":
    asyncio.run(main())
