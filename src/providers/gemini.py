"""Gemini API provider."""

import requests
import json
import time
import asyncio
import random
import logging
import html
from prompt_toolkit import print_formatted_text
from prompt_toolkit.formatted_text import HTML
from ..config import config

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Pricing (per 1M tokens)
# ---------------------------------------------------------------------------

PRICING = {
    "gemini-2.5-pro": {
        "input": 1.25,
        "output": 10.00,
        "cached": 0.125,
        "high_input": 2.50,
        "high_output": 15.00,
        "high_cached": 0.25,
    },
    "gemini-3-pro": {
        "input": 2.00,
        "output": 12.00,
        "cached": 0.20,
        "high_input": 4.00,
        "high_output": 18.00,
        "high_cached": 0.40,
    },
    "gemini-3-pro-preview": {
        "input": 2.00,
        "output": 12.00,
        "cached": 0.20,
        "high_input": 4.00,
        "high_output": 18.00,
        "high_cached": 0.40,
    },
    "gemini-2.5-flash": {"input": 0.30, "output": 2.50, "cached": 0.03},
    "gemini-2.5-flash-lite": {"input": 0.10, "output": 0.40, "cached": 0.01},
    "gemini-2.0-flash": {"input": 0.10, "output": 0.40, "cached": 0.025},
    "gemini-2.0-flash-lite": {"input": 0.075, "output": 0.30, "cached": 0.0},
}


def calculate_cost(model: str, usage: dict) -> float:
    """Calculate cost from usage metadata."""
    if not usage:
        return 0

    model_id = model.lower().replace("google/", "")
    pricing = PRICING.get(model_id)
    if not pricing:
        return 0

    prompt = usage.get("promptTokenCount", 0)
    output = usage.get("candidatesTokenCount", 0) + usage.get("thoughtsTokenCount", 0)
    cached = usage.get("cachedContentTokenCount", 0)

    # Use high-volume pricing if > 200k tokens
    if prompt > 200000 and "high_input" in pricing:
        return (
            ((prompt - cached) / 1e6) * pricing["high_input"]
            + (output / 1e6) * pricing["high_output"]
            + (cached / 1e6) * pricing["high_cached"]
        )

    return (
        ((prompt - cached) / 1e6) * pricing["input"]
        + (output / 1e6) * pricing["output"]
        + (cached / 1e6) * pricing["cached"]
    )


# ---------------------------------------------------------------------------
# Message/Schema Conversion
# ---------------------------------------------------------------------------


def to_gemini_schema(schema: dict) -> dict:
    """Convert OpenAI schema types to Gemini (uppercase)."""
    if not schema or not isinstance(schema, dict):
        return schema
    result = schema.copy()
    if "type" in result and isinstance(result["type"], str):
        result["type"] = result["type"].upper()
    if "properties" in result:
        result["properties"] = {k: to_gemini_schema(v) for k, v in result["properties"].items()}
    if "items" in result:
        result["items"] = to_gemini_schema(result["items"])
    return result


def to_gemini_parts(content) -> list:
    """Convert OpenAI content format to Gemini parts."""
    if not content:
        return []
    if isinstance(content, str):
        return [{"text": content}]
    if isinstance(content, list):
        parts = []
        for item in content:
            if isinstance(item, str):
                parts.append({"text": item})
            elif isinstance(item, dict):
                if item.get("type") == "text":
                    parts.append({"text": item["text"]})
                elif item.get("type") == "image_url":
                    url = item["image_url"]["url"]
                    if url.startswith("data:image/"):
                        mime, data = url.split(";")[0].split(":")[1], url.split(",")[1]
                        parts.append({"inline_data": {"mime_type": mime, "data": data}})
        return parts
    return []


def to_gemini_messages(messages: list) -> tuple[list, dict | None]:
    """Convert OpenAI messages to Gemini format. Returns (contents, system_instruction)."""
    contents = []
    system_instruction = None

    for msg in messages:
        if msg["role"] == "system":
            system_instruction = {"parts": to_gemini_parts(msg["content"])}
        elif msg["role"] == "user":
            contents.append({"role": "user", "parts": to_gemini_parts(msg["content"])})
        elif msg["role"] == "assistant":
            parts = to_gemini_parts(msg.get("content"))
            for tc in msg.get("tool_calls") or []:
                part = {
                    "functionCall": {"name": tc["function"]["name"], "args": json.loads(tc["function"]["arguments"])}
                }
                if "thought_signature" in tc["function"]:
                    part["thoughtSignature"] = tc["function"]["thought_signature"]
                parts.append(part)
            if parts:
                contents.append({"role": "model", "parts": parts})
        elif msg["role"] == "tool":
            contents.append(
                {
                    "role": "function",
                    "parts": [{"functionResponse": {"name": msg["name"], "response": {"result": msg["content"]}}}],
                }
            )

    return contents, system_instruction


def to_gemini_tools(tools: list) -> list:
    """Convert OpenAI tools format to Gemini."""
    if not tools:
        return []
    return [
        {
            "function_declarations": [
                {
                    "name": t["function"]["name"],
                    "description": t["function"]["description"],
                    "parameters": to_gemini_schema(t["function"]["parameters"]),
                }
                for t in tools
            ]
        }
    ]


# ---------------------------------------------------------------------------
# API Call
# ---------------------------------------------------------------------------


async def call_gemini(messages: list, tools: list, model: str = None) -> dict:
    """Call Gemini API. Returns dict with 'message' and 'usage'."""
    model_id = (model or config.model).replace("google/", "")
    url = f"https://generativelanguage.googleapis.com/v1beta/models/{model_id}:generateContent?key={config.gemini_api_key}"

    contents, system_instruction = to_gemini_messages(messages)

    # Check for google search trigger
    use_grounding = any(t["function"]["name"] == "__google_search_trigger__" for t in tools) if tools else False

    body = {
        "contents": contents,
        "tools": [{"googleSearch": {}}] if use_grounding else to_gemini_tools(tools),
        "generationConfig": {"temperature": 0.0},
    }

    # Enable thinking for pro models
    if "pro" in model_id.lower():
        body["generationConfig"]["thinkingConfig"] = {"includeThoughts": True}
        body["generationConfig"]["maxOutputTokens"] = 64000

    if system_instruction:
        body["systemInstruction"] = system_instruction

    # Retry loop
    for attempt in range(3):
        try:
            response = await asyncio.to_thread(
                requests.post, url, headers={"Content-Type": "application/json"}, json=body, timeout=120
            )

            # Handle thinkingConfig not supported
            if response.status_code == 400 and "thinkingConfig" in response.text:
                logger.warning("Model doesn't support thinkingConfig, retrying without it.")
                body["generationConfig"].pop("thinkingConfig", None)
                response = await asyncio.to_thread(
                    requests.post, url, headers={"Content-Type": "application/json"}, json=body, timeout=120
                )

            if response.status_code != 200:
                if response.status_code >= 500 or response.status_code == 429:
                    logger.warning(f"Attempt {attempt + 1} failed: {response.status_code}. Retrying...")
                    await asyncio.sleep(2**attempt)
                    continue
                raise Exception(f"Gemini API error: {response.status_code} - {response.text}")

            data = response.json()

            # Process usage
            usage = data.get("usageMetadata", {})
            if usage:
                print_formatted_text(HTML(f"<style fg='#666666'>Tokens: {html.escape(json.dumps(usage))}</style>"))
                usage["cost"] = calculate_cost(model_id, usage)

            if "candidates" not in data or not data["candidates"]:
                raise Exception(f"No candidates: {json.dumps(data.get('promptFeedback', data))}")

            # Parse response
            parts = data["candidates"][0].get("content", {}).get("parts", [])
            content, reasoning, tool_calls = "", "", []

            for part in parts:
                if part.get("thought"):
                    reasoning += (part.get("text", "") if isinstance(part["thought"], bool) else part["thought"]) + "\n"
                elif "text" in part:
                    content += part["text"]
                if "functionCall" in part:
                    tc = {
                        "id": f"call_{int(time.time())}_{random.randint(1000, 9999)}",
                        "type": "function",
                        "function": {
                            "name": part["functionCall"]["name"],
                            "arguments": json.dumps(part["functionCall"]["args"]),
                        },
                    }
                    if "thoughtSignature" in part:
                        tc["function"]["thought_signature"] = part["thoughtSignature"]
                    tool_calls.append(tc)

            return {
                "message": {
                    "role": "assistant",
                    "content": content,
                    "reasoning": reasoning.strip() or None,
                    "tool_calls": tool_calls or None,
                },
                "usage": usage,
            }

        except requests.exceptions.RequestException as e:
            logger.warning(f"Attempt {attempt + 1} failed: {e}")
            await asyncio.sleep(2**attempt)

    raise Exception("Failed to call Gemini API after 3 retries.")
