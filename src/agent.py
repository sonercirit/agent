import asyncio
import sys
import json
import time
from prompt_toolkit import PromptSession
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

# Colors
class Colors:
    RESET = "\033[0m"
    RED = "\033[31m"
    GREEN = "\033[32m"
    YELLOW = "\033[33m"
    BLUE = "\033[34m"
    MAGENTA = "\033[35m"
    CYAN = "\033[36m"
    WHITE = "\033[37m"
    GRAY = "\033[90m"
    BOLD = "\033[1m"
    DIM = "\033[2m"

system_prompt = """You are a powerful agentic AI assistant.
You have access to a bash tool which allows you to do almost anything on the system.
You should use this tool to accomplish the user's requests.
You are optimized for high reasoning and complex tasks.
Always verify your actions and output.
If you need to run a command, just do it.
The user has set a strict output limit of 1k tokens per tool call. If you see truncated output, refine your command (e.g., use grep, head, tail) to get the specific information you need."""

messages = [{"role": "system", "content": system_prompt}]
last_request_time = 0

async def _process_turn_logic(user_input, stop_check_callback=None):
    global last_request_time
    
    messages.append({"role": "user", "content": user_input})
    
    turn_finished = False
    
    while not turn_finished:
        if stop_check_callback and stop_check_callback():
            print(f"\n{Colors.YELLOW}Stopping after current step as requested.{Colors.RESET}")
            break

        try:
            manage_cache(messages)
            
            current_time = time.time() * 1000
            elapsed_minutes = 0
            if last_request_time > 0:
                elapsed_minutes = (current_time - last_request_time) / 60000
            
            response = await call_llm(messages, tools_schema)
            last_request_time = time.time() * 1000
            
            response_message = response["message"]
            usage = response["usage"]
            
            messages.append(response_message)
            
            # Show reasoning
            if response_message.get("reasoning"):
                print(f"\n{Colors.GRAY}=== Thinking Process ==={Colors.RESET}")
                print(f"{Colors.GRAY}{response_message['reasoning']}{Colors.RESET}")
                print(f"{Colors.GRAY}========================{Colors.RESET}\n")
                
            if response_message.get("tool_calls"):
                if stop_check_callback and stop_check_callback():
                    print(f"\n{Colors.YELLOW}Stopping before executing tools as requested.{Colors.RESET}")
                    break
                await handle_tool_calls(response_message["tool_calls"])
            else:
                print(f"\n{Colors.GREEN}Assistant:{Colors.RESET}")
                print(f"{response_message['content']}\n")
                turn_finished = True
                
        except asyncio.CancelledError:
            raise
        except Exception as e:
            print(f"\n{Colors.RED}Error: {str(e)}{Colors.RESET}")
            turn_finished = True

async def process_turn(user_input):
    kb = KeyBindings()
    processing_task = None
    stop_requested = False

    @kb.add('c-w')
    def _(event):
        nonlocal stop_requested
        stop_requested = True
        # We don't exit here, we let the logic loop notice the flag or finish naturally
        # But we need to notify the user
        pass

    @kb.add('c-c')
    def _(event):
        if processing_task:
            processing_task.cancel()
        # Do NOT call event.app.exit() here. 
        # The cancellation will trigger the finally block in run_logic which calls app.exit()
    
    def get_status_text():
        if stop_requested:
            return HTML(" <style class='ansiyellow'>Stopping after current step...</style> (Ctrl+C to force quit)")
        return HTML(" <style class='ansigreen'>Thinking...</style> (Ctrl+W to stop gracefully, Ctrl+C to force quit)")

    status_window = Window(content=FormattedTextControl(get_status_text), height=1, style="class:status")
    
    app = Application(
        layout=Layout(status_window),
        key_bindings=kb,
        full_screen=False
    )
    
    async def run_logic():
        nonlocal processing_task
        try:
             # We need to pass the stop_check to _process_turn_logic
             # But _process_turn_logic is outside. 
             # We can wrap it or modify it.
             # Let's modify _process_turn_logic to check a global or callback?
             # Or better, we define the logic inside here or pass a context.
             
             # Since _process_turn_logic is global, let's pass a lambda to check stop
             await _process_turn_logic(user_input, lambda: stop_requested)
        except asyncio.CancelledError:
            print(f"\n{Colors.RED}User requested interrupt.{Colors.RESET}")
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
    print(f"\n{Colors.YELLOW}Tool Calls:{Colors.RESET}")
    
    for tool_call in tool_calls:
        func_name = tool_call["function"]["name"]
        args_str = tool_call["function"]["arguments"]
        
        try:
            args = json.loads(args_str)
        except json.JSONDecodeError:
            args = {}
            
        print(f"  {Colors.BOLD}{func_name}{Colors.RESET}({json.dumps(args)})")
        
        # Approval check for sensitive tools
        if config.mode == "manual":
            # Simple approval for now, can be expanded
            pass 
            
        if func_name in tool_implementations:
            try:
                result = await tool_implementations[func_name](**args)
            except Exception as e:
                result = f"Error executing tool: {str(e)}"
        else:
            result = f"Error: Tool '{func_name}' not found."
            
        # Add tool result to messages
        messages.append({
            "role": "tool",
            "tool_call_id": tool_call.get("id", "call_unknown"),
            "name": func_name,
            "content": str(result)
        })
        
        print(f"{Colors.DIM}Result: {str(result)[:100]}...{Colors.RESET}")

async def main():
    print(f"{Colors.CYAN}Agent started in {config.mode} mode using model {config.model}{Colors.RESET}")
    print(f"{Colors.DIM}Shortcuts:{Colors.RESET}")
    print(f"{Colors.DIM}  Alt+Enter : Submit{Colors.RESET}")
    print(f"{Colors.DIM}  Alt+E     : Open External Editor{Colors.RESET}")
    print(f"{Colors.DIM}  Alt+I     : Paste Image from Clipboard{Colors.RESET}")
    print(f"{Colors.DIM}  Ctrl+C    : Stop/Cancel{Colors.RESET}")
    print(f"{Colors.DIM}  Type 'exit' to quit.{Colors.RESET}")
    
    kb = KeyBindings()

    @kb.add('escape', 'enter')
    def _(event):
        event.current_buffer.validate_and_handle()

    @kb.add('escape', 'e')
    def _(event):
        event.current_buffer.open_in_editor()
        
    @kb.add('escape', 'i')
    async def _(event):
        path = await save_clipboard_image()
        if path:
            event.current_buffer.insert_text(path)

    session = PromptSession(
        key_bindings=kb,
        vi_mode=True,
        multiline=True,
        lexer=PygmentsLexer(MarkdownLexer),
        style=Style.from_dict({
            'prompt': 'ansicyan bold',
        })
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