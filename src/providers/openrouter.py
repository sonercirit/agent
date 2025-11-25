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
    effective_model = model or config.model
    is_anthropic = "anthropic" in effective_model or "claude" in effective_model
    
    headers = {
        "Authorization": f"Bearer {config.api_key}",
        "Content-Type": "application/json",
        "HTTP-Referer": "https://github.com/your-repo/agent",
        "X-Title": "Agent",
    }

    body = {
        "model": effective_model,
        "messages": messages,
        "tools": tools,
        "temperature": 0,
        "usage": {"include": True},
        "include_reasoning": True,
        "provider": {"allow_fallbacks": False},
        "reasoning": {"effort": "high"},
    }
    
    # Enable prompt caching for Anthropic models
    if is_anthropic:
        # OpenRouter passes through Anthropic beta headers
        # headers["anthropic-beta"] = "prompt-caching-2024-07-31"
        # Force Anthropic as provider (not Google Vertex) to enable caching
        body["provider"] = {"order": ["Anthropic"], "allow_fallbacks": False}

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

            # Check for API error in response body
            if "error" in data:
                error_msg = data["error"]
                if isinstance(error_msg, dict):
                    error_msg = error_msg.get("message", str(error_msg))
                logger.warning(f"Attempt {attempt + 1} failed: API error - {error_msg}. Retrying...")
                attempt += 1
                await asyncio.sleep(1 * (2**attempt))
                continue

            if "choices" not in data or not data["choices"]:
                logger.warning(f"Attempt {attempt + 1} failed: No choices in response. Data: {data}. Retrying...")
                attempt += 1
                await asyncio.sleep(1 * (2**attempt))
                continue

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
