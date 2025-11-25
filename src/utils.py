"""Utility functions."""

from .config import config


def truncate_output(output: str) -> str:
    """Truncate output to configured limit."""
    char_limit = config.tool_output_limit * 4
    if len(output) > char_limit:
        return output[:char_limit] + f"\n... (Output truncated. Total length: {len(output)} chars.)"
    return output
