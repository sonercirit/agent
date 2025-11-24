from .config import config
from .providers.openrouter import call_openrouter
from .providers.gemini import call_gemini

async def call_llm(messages, tools, model=None):
    if config.provider == "gemini":
        return await call_gemini(messages, tools, model)
    else:
        return await call_openrouter(messages, tools, model)
