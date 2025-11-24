import asyncio
import sys
import json
import time
import logging
import html
from prompt_toolkit import PromptSession, print_formatted_text
from prompt_toolkit.key_binding import KeyBindings
from prompt_toolkit.formatted_text import HTML
from prompt_toolkit.styles import Style
from prompt_toolkit.lexers import PygmentsLexer
from pygments.lexers.markup import MarkdownLexer
from prompt_toolkit.application import Application
from prompt_toolkit.layout.containers import Window
from prompt_toolkit.layout.controls import FormattedTextControl
from prompt_toolkit.layout.layout import Layout
from prompt_toolkit.patch_stdout import patch_stdout

from .config import config
from .llm import call_llm
from .tools import tool_implementations, tools_schema, save_clipboard_image
from .cache import manage_cache
from .utils import ask_approval


# Setup Logging
class PTKHandler(logging.Handler):
    def emit(self, record):
        try:
            msg = self.format(record)
            escaped_msg = html.escape(msg)
            if record.levelno >= logging.ERROR:
                style = "ansired"
            elif record.levelno >= logging.WARNING:
                style = "ansiyellow"
            elif record.levelno >= logging.INFO:
                style = "ansiwhite"
            else:
                style = "style fg='#888888'"

            print_formatted_text(
                HTML(
                    f"<{style}>{escaped_msg}</{style if ' ' not in style else style.split()[0]}>"
                )
            )
        except Exception:
            self.handleError(record)


root_logger = logging.getLogger()
root_logger.setLevel(logging.DEBUG if config.debug else logging.INFO)
# Remove existing handlers to avoid duplication if reloaded
if root_logger.handlers:
    root_logger.handlers = []

handler = PTKHandler()
handler.setFormatter(
    logging.Formatter("%(asctime)s - %(name)s - %(levelname)s - %(message)s")
)
root_logger.addHandler(handler)

logger = logging.getLogger("Agent")

system_prompt = """You are a powerful agentic AI assistant.
You have access to a bash tool which allows you to do almost anything on the system.
You should use this tool to accomplish the user's requests.
You are optimized for high reasoning and complex tasks.
Always verify your actions and output.
If you need to run a command, just do it.
The user has set a strict output limit of 1k tokens per tool call. If you see truncated output, refine your command (e.g., use grep, head, tail) to get the specific information you need."""

messages = [{"role": "system", "content": system_prompt}]
last_request_time = 0
total_cost = 0
has_seen_cached_tokens = False


def handle_usage(usage, elapsed_minutes):
    global total_cost, has_seen_cached_tokens

    cost = usage.get("cost")
    if cost:
        total_cost += cost
        print_formatted_text(
            HTML(
                f"<ansicyan>Cost: ${cost:.6f} | Total Session Cost: ${total_cost:.6f}</ansicyan>"
            )
        )

    cached_tokens = (
        usage.get("prompt_tokens_details", {}).get("cached_tokens", 0)
        or usage.get("cachedContentTokenCount", 0)
        or 0
    )

    if cached_tokens > 0:
        has_seen_cached_tokens = True

    if has_seen_cached_tokens and cached_tokens == 0:
        is_gemini = config.provider == "gemini" or "gemini" in config.model.lower()
        cache_ttl = 60.0 if is_gemini else 5.0
        reason = (
            "Prefix mismatch or Checkpoint limit"
            if elapsed_minutes < (cache_ttl - 1)
            else "Cache TTL expired"
        )

        print_formatted_text(
            HTML(
                f"<ansired>WARNING: Cached tokens dropped to 0! (Elapsed: {elapsed_minutes:.1f} minutes). Cause: {reason}.</ansired>"
            )
        )


async def _process_turn_logic(user_input, stop_check_callback=None):
    global last_request_time

    logger.debug(f"Processing turn with input: {user_input}")
    messages.append({"role": "user", "content": user_input})

    turn_finished = False

    while not turn_finished:
        if stop_check_callback and stop_check_callback():
            print_formatted_text(
                HTML(
                    "\n<ansiyellow>Stopping after current step as requested.</ansiyellow>"
                )
            )
            break

        try:
            manage_cache(messages)

            current_time = time.time() * 1000
            elapsed_minutes = 0
            if last_request_time > 0:
                elapsed_minutes = (current_time - last_request_time) / 60000

            logger.debug("Calling LLM...")
            response = await call_llm(messages, tools_schema)
            last_request_time = time.time() * 1000

            response_message = response["message"]
            usage = response["usage"]

            logger.debug(f"LLM Response: {json.dumps(response_message, default=str)}")
            logger.debug(f"Usage: {usage}")

            if usage:
                handle_usage(usage, elapsed_minutes)

            messages.append(response_message)

            # Show reasoning
            if response_message.get("reasoning"):
                print_formatted_text(
                    HTML("\n<style fg='#888888'>=== Thinking Process ===</style>")
                )
                print_formatted_text(
                    HTML("<style fg='#888888'>{}</style>").format(
                        response_message["reasoning"]
                    )
                )
                print_formatted_text(
                    HTML("<style fg='#888888'>========================</style>\n")
                )

            if response_message.get("tool_calls"):
                if stop_check_callback and stop_check_callback():
                    print_formatted_text(
                        HTML(
                            "\n<ansiyellow>Stopping before executing tools as requested.</ansiyellow>"
                        )
                    )
                    break
                await handle_tool_calls(response_message["tool_calls"])
            else:
                print_formatted_text(HTML("\n<ansigreen>Assistant:</ansigreen>"))
                print_formatted_text(HTML("{}").format(response_message["content"]))
                print_formatted_text(HTML(""))
                turn_finished = True

        except asyncio.CancelledError:
            raise
        except Exception as e:
            logger.exception("Error during turn processing")
            print_formatted_text(HTML("\n<ansired>Error: {}</ansired>").format(str(e)))
            turn_finished = True


async def process_turn(user_input):
    kb = KeyBindings()
    processing_task = None
    stop_requested = False

    @kb.add("c-w")
    def _(event):
        nonlocal stop_requested
        stop_requested = True

    @kb.add("c-c")
    def _(event):
        if processing_task:
            processing_task.cancel()

    def get_status_text():
        if stop_requested:
            return HTML(
                " <ansiyellow>Stopping after current step...</ansiyellow> (Ctrl+C to force quit)"
            )
        return HTML(
            " <ansigreen>Thinking...</ansigreen> (Ctrl+W to stop gracefully, Ctrl+C to force quit)"
        )

    status_window = Window(
        content=FormattedTextControl(get_status_text), height=1, style="class:status"
    )

    app = Application(layout=Layout(status_window), key_bindings=kb, full_screen=False)

    async def run_logic():
        nonlocal processing_task
        try:
            await _process_turn_logic(user_input, lambda: stop_requested)
        except asyncio.CancelledError:
            print_formatted_text(HTML("\n<ansired>User requested interrupt.</ansired>"))
        finally:
            app.exit()

    with patch_stdout():
        processing_task = asyncio.create_task(run_logic())
        await app.run_async()
        if not processing_task.done():
            processing_task.cancel()
            try:
                await processing_task
            except asyncio.CancelledError:
                pass


async def handle_tool_calls(tool_calls):
    print_formatted_text(HTML("\n<ansiyellow>Tool Calls:</ansiyellow>"))

    for tool_call in tool_calls:
        func_name = tool_call["function"]["name"]
        args_str = tool_call["function"]["arguments"]

        try:
            args = json.loads(args_str)
        except json.JSONDecodeError:
            args = {}

        print_formatted_text(
            HTML("  <b>{}</b>({})").format(func_name, json.dumps(args))
        )
        logger.debug(f"Executing tool {func_name} with args: {args}")

        # Approval check for sensitive tools
        if config.mode == "manual":
            # Simple approval for now, can be expanded
            pass

        if func_name in tool_implementations:
            try:
                result = await tool_implementations[func_name](**args)
            except Exception as e:
                result = f"Error executing tool: {str(e)}"
                logger.error(f"Tool execution error: {e}")
        else:
            result = f"Error: Tool '{func_name}' not found."
            logger.error(result)

        # Add tool result to messages
        messages.append(
            {
                "role": "tool",
                "tool_call_id": tool_call.get("id", "call_unknown"),
                "name": func_name,
                "content": str(result),
            }
        )

        logger.debug(f"Tool Result: {str(result)}")
        print_formatted_text(
            HTML("<style fg='#888888'>Result: {}...</style>").format(str(result)[:100])
        )


async def main():
    print_formatted_text(
        HTML("<ansicyan>Agent started in {} mode using model {}</ansicyan>").format(
            config.mode, config.model
        )
    )
    print_formatted_text(HTML("<style fg='#888888'>Shortcuts:</style>"))
    print_formatted_text(HTML("<style fg='#888888'>  Alt+Enter : Submit</style>"))
    print_formatted_text(
        HTML("<style fg='#888888'>  Alt+E     : Open External Editor</style>")
    )
    print_formatted_text(
        HTML("<style fg='#888888'>  Alt+I     : Paste Image from Clipboard</style>")
    )
    print_formatted_text(HTML("<style fg='#888888'>  Ctrl+C    : Stop/Cancel</style>"))
    print_formatted_text(HTML("<style fg='#888888'>  Type 'exit' to quit.</style>"))

    if config.initial_prompt:
        print_formatted_text(HTML("\n<ansicyan>Executing initial prompt...</ansicyan>"))
        await process_turn(config.initial_prompt)

    kb = KeyBindings()

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
        style=Style.from_dict(
            {
                "prompt": "ansicyan bold",
            }
        ),
    )

    while True:
        try:
            user_input = await session.prompt_async(
                HTML("<b>User (Alt+Enter to send):</b>\n"),
            )

            if user_input.strip().lower() == "exit":
                break

            if not user_input.strip():
                continue

            await process_turn(user_input)

        except KeyboardInterrupt:
            continue
        except EOFError:
            break


if __name__ == "__main__":
    asyncio.run(main())
