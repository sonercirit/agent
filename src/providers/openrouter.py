import requests
import json
import time
import asyncio
import logging
import html
from prompt_toolkit import print_formatted_text
from prompt_toolkit.formatted_text import HTML
from ..config import config

logger = logging.getLogger(__name__)


async def call_openrouter(messages, tools, model=None):
    headers = {
        "Authorization": f"Bearer {config.api_key}",
        "Content-Type": "application/json",
        "HTTP-Referer": "https://github.com/your-repo/agent",
        "X-Title": "Agent",
    }

    body = {
        "model": model or config.model,
        "messages": messages,
        "tools": tools,
        "usage": {"include": True},
        "include_reasoning": True,
        "provider": {"allow_fallbacks": False},
    }

    # Handle Google Search Trigger
    force_grounding = False
    if tools:
        for t in tools:
            if t["function"]["name"] == "__google_search_trigger__":
                force_grounding = True
                break

    if force_grounding:
        if not body["model"].endswith(":online"):
            body["model"] += ":online"
        if body.get("tools"):
            body["tools"] = [
                t
                for t in body["tools"]
                if t["function"]["name"] != "__google_search_trigger__"
            ]
            if not body["tools"]:
                del body["tools"]

    MAX_RETRIES = 3
    attempt = 0

    while attempt < MAX_RETRIES:
        try:
            response = await asyncio.to_thread(
                requests.post,
                "https://openrouter.ai/api/v1/chat/completions",
                headers=headers,
                json=body,
                timeout=120,
            )

            if response.status_code != 200:
                error_text = response.text
                if response.status_code >= 500 or response.status_code == 429:
                    logger.warning(
                        f"Attempt {attempt + 1} failed: {response.status_code}. Retrying..."
                    )
                    attempt += 1
                    await asyncio.sleep(1 * (2**attempt))
                    continue
                raise Exception(
                    f"OpenRouter API error: {response.status_code} - {error_text}"
                )

            data = response.json()

            if "usage" in data:
                print_formatted_text(
                    HTML(
                        f"<style fg='#666666'>Token Usage: {html.escape(json.dumps(data['usage'], indent=2))}</style>"
                    )
                )

            choice = data["choices"][0]
            message = choice["message"]

            return {"message": message, "usage": data.get("usage")}

        except requests.exceptions.RequestException as e:
            logger.warning(f"Attempt {attempt + 1} failed: Network error. Retrying...")
            attempt += 1
            await asyncio.sleep(1 * (2**attempt))
            continue

    raise Exception("Failed to call OpenRouter API after retries.")
