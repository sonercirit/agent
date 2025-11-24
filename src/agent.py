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

async def process_turn(user_input):
    global last_request_time
    
    messages.append({"role": "user", "content": user_input})
    
    turn_finished = False
    interrupted = False
    
    while not turn_finished and not interrupted:
        print(f"{Colors.DIM}Thinking... (Ctrl+C to interrupt){Colors.RESET}")
        
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
                await handle_tool_calls(response_message["tool_calls"])
            else:
                print(f"\n{Colors.GREEN}Assistant:{Colors.RESET}")
                print(f"{response_message['content']}\n")
                turn_finished = True
                
        except KeyboardInterrupt:
            print(f"\n{Colors.RED}User requested interrupt.{Colors.RESET}")
            interrupted = True
            break
        except Exception as e:
            print(f"\n{Colors.RED}Error: {str(e)}{Colors.RESET}")
            turn_finished = True

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
        # Gemini expects specific format, OpenRouter (OpenAI) expects another
        # We'll use the standard OpenAI format and let the provider adapters handle it
        messages.append({
            "role": "tool",
            "tool_call_id": tool_call.get("id", "call_unknown"),
            "name": func_name,
            "content": str(result)
        })
        
        print(f"{Colors.DIM}Result: {str(result)[:100]}...{Colors.RESET}")

async def main():
    print(f"{Colors.CYAN}Agent started in {config.mode} mode using model {config.model}{Colors.RESET}")
    print(f"{Colors.DIM}Type 'exit' to quit. Ctrl+S to submit. Ctrl+E for external editor.{Colors.RESET}")
    
    kb = KeyBindings()

    @kb.add('c-s')
    def _(event):
        event.current_buffer.validate_and_handle()

    @kb.add('c-e')
    def _(event):
        event.current_buffer.open_in_editor()
        
    @kb.add('c-v')
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
                HTML("<b>User (Ctrl+S to send):</b>\n"),
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
