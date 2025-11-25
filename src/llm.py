"""LLM provider router."""

from .config import config
from .providers.gemini import call_gemini
from .providers.openrouter import call_openrouter


async def call_llm(messages: list, tools: list, model: str = None) -> dict:
    """Route LLM calls to the configured provider."""
    if config.provider == "gemini":
        return await call_gemini(messages, tools, model)
    return await call_openrouter(messages, tools, model)
