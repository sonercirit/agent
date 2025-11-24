from .config import config


def limit_output(output, is_error=False):
    char_limit = config.tool_output_limit * 4
    if len(output) > char_limit:
        return (
            output[:char_limit]
            + f"\n... (Output truncated. Total length: {len(output)} chars.)"
        )
    return output


def ask_approval(question):
    try:
        response = input(f"{question} (y/n): ")
        return response.lower() == "y"
    except EOFError:
        return False
