"""OpenRouter API provider."""

import requests
import json
import asyncio
import logging
import html
from prompt_toolkit import print_formatted_text
from prompt_toolkit.formatted_text import HTML
from ..config import config
from ..cache import apply_anthropic_cache

logger = logging.getLogger(__name__)


def prepare_messages_for_openrouter(messages: list, model: str) -> list:
    """Prepare messages for OpenRouter, including reasoning preservation for Gemini."""
    is_gemini = "gemini" in model.lower()
    prepared = []

    for msg in messages:
        new_msg = {"role": msg["role"]}

        # Handle content
        if "content" in msg:
            new_msg["content"] = msg["content"]

        # Handle tool calls (assistant messages)
        if "tool_calls" in msg:
            new_msg["tool_calls"] = msg["tool_calls"]

        # Handle tool results
        if "tool_call_id" in msg:
            new_msg["tool_call_id"] = msg["tool_call_id"]
        if "name" in msg:
            new_msg["name"] = msg["name"]

        # Preserve reasoning_details for Gemini models (required for tool calling)
        # This contains the encrypted thought signatures needed for multi-turn tool calls
        if is_gemini and "reasoning_details" in msg:
            new_msg["reasoning_details"] = msg["reasoning_details"]

        prepared.append(new_msg)

    return prepared


async def call_openrouter(messages: list, tools: list, model: str = None) -> dict:
    """Call OpenRouter API. Returns dict with 'message' and 'usage'."""
    effective_model = model or config.model

    # Detect provider type for optimizations
    is_anthropic = "anthropic" in effective_model or "claude" in effective_model
    is_openai = any(x in effective_model for x in ["openai", "gpt", "o1", "o3", "o4"])
    is_gemini = "gemini" in effective_model

    # Apply Anthropic caching if applicable
    if is_anthropic:
        apply_anthropic_cache(messages, effective_model)

    # Prepare messages (handles reasoning preservation for Gemini)
    prepared_messages = prepare_messages_for_openrouter(messages, effective_model)

    headers = {
        "Authorization": f"Bearer {config.openrouter_api_key}",
        "Content-Type": "application/json",
        "HTTP-Referer": "https://github.com/sonercirit/agent",
        "X-Title": "Agent",
    }

    body = {
        "model": effective_model,
        "messages": prepared_messages,
        "tools": tools if tools else None,
        "temperature": 0,
        "usage": {"include": True},
        "include_reasoning": True,
        "reasoning": {"effort": "high"},
        "provider": {"allow_fallbacks": False},
    }

    # Remove None values
    body = {k: v for k, v in body.items() if v is not None}

    # Lock to specific providers
    if is_anthropic:
        body["provider"] = {"order": ["Anthropic"], "allow_fallbacks": False}
    elif is_openai:
        body["provider"] = {"order": ["OpenAI"], "allow_fallbacks": False}
    elif is_gemini:
        body["provider"] = {"order": ["Google AI Studio"], "allow_fallbacks": False}

    # Handle Google Search trigger
    if tools and any(t["function"]["name"] == "__google_search_trigger__" for t in tools):
        if not body["model"].endswith(":online"):
            body["model"] += ":online"
        body["tools"] = [t for t in tools if t["function"]["name"] != "__google_search_trigger__"]
        if not body["tools"]:
            body.pop("tools", None)

    # Retry loop
    for attempt in range(3):
        try:
            response = await asyncio.to_thread(
                requests.post, "https://openrouter.ai/api/v1/chat/completions", headers=headers, json=body, timeout=120
            )

            if response.status_code != 200:
                if response.status_code >= 500 or response.status_code == 429:
                    logger.warning(f"Attempt {attempt + 1} failed: {response.status_code}. Retrying...")
                    await asyncio.sleep(2**attempt)
                    continue
                raise Exception(f"OpenRouter API error: {response.status_code} - {response.text}")

            data = response.json()

            if "error" in data:
                logger.warning(f"API error: {data['error']}. Retrying...")
                await asyncio.sleep(2**attempt)
                continue

            if "choices" not in data or not data["choices"]:
                logger.warning("No choices in response. Retrying...")
                await asyncio.sleep(2**attempt)
                continue

            usage = data.get("usage", {})
            if usage:
                print_formatted_text(HTML(f"<style fg='#666666'>Tokens: {html.escape(json.dumps(usage))}</style>"))

            msg = data["choices"][0]["message"]

            # Log reasoning details preservation for debugging
            if is_gemini and msg.get("reasoning_details"):
                logger.debug(f"Response has reasoning_details: {len(msg['reasoning_details'])} items")

            return {"message": msg, "usage": usage}

        except requests.exceptions.RequestException as e:
            logger.warning(f"Attempt {attempt + 1} failed: {e}")
            await asyncio.sleep(2**attempt)

    raise Exception("Failed to call OpenRouter API after 3 retries.")
