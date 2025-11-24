import requests
import json
import time
import asyncio
import random
import logging
from prompt_toolkit import print_formatted_text
from prompt_toolkit.formatted_text import HTML
from ..config import config

logger = logging.getLogger(__name__)


def fix_schema_types(schema):
    if not schema or not isinstance(schema, dict):
        return schema

    new_schema = schema.copy()

    if "type" in new_schema and isinstance(new_schema["type"], str):
        new_schema["type"] = new_schema["type"].upper()

    if "properties" in new_schema:
        new_props = {}
        for key, prop in new_schema["properties"].items():
            new_props[key] = fix_schema_types(prop)
        new_schema["properties"] = new_props

    if "items" in new_schema:
        new_schema["items"] = fix_schema_types(new_schema["items"])

    return new_schema


def map_tools_to_gemini(tools):
    gemini_tools = []

    # We no longer force grounding based on tool definition here,
    # because we handle it dynamically in call_gemini based on the conversation state.
    # However, we still need to filter out google_search from the function declarations
    # if we are NOT in grounding mode, so the model can call it as a function.
    # Actually, we WANT the model to call it as a function first.

    if tools:
        gemini_tools.append(
            {
                "function_declarations": [
                    {
                        "name": t["function"]["name"],
                        "description": t["function"]["description"],
                        "parameters": fix_schema_types(t["function"]["parameters"]),
                    }
                    for t in tools
                ]
            }
        )

    return gemini_tools


def format_gemini_parts(content):
    if not content:
        return []
    if isinstance(content, str):
        return [{"text": content}]
    if isinstance(content, list):
        parts = []
        for part in content:
            if isinstance(part, str):
                parts.append({"text": part})
            elif isinstance(part, dict):
                if part.get("type") == "text":
                    parts.append({"text": part["text"]})
                elif part.get("type") == "image_url":
                    # Handle base64 image
                    url = part["image_url"]["url"]
                    if url.startswith("data:image/"):
                        mime_type = url.split(";")[0].split(":")[1]
                        data = url.split(",")[1]
                        parts.append(
                            {"inline_data": {"mime_type": mime_type, "data": data}}
                        )
        return parts
    return []


def calculate_gemini_cost(model, usage):
    if not usage:
        return 0

    # Strip 'google/' prefix if present for matching
    model_id = model.lower()
    if model_id.startswith("google/"):
        model_id = model_id.replace("google/", "")

    prompt_tokens = usage.get("promptTokenCount", 0)
    output_tokens = usage.get("candidatesTokenCount", 0) + usage.get(
        "thoughtsTokenCount", 0
    )
    cached_tokens = usage.get("cachedContentTokenCount", 0)
    regular_input_tokens = max(0, prompt_tokens - cached_tokens)

    # Pricing per 1M tokens
    pricing = None

    if model_id == "gemini-2.5-pro":
        # Gemini 2.5 Pro
        # Input: $1.25 (<=200k), $2.50 (>200k)
        # Output: $10.00 (<=200k), $15.00 (>200k)
        # Cached: $0.125 (<=200k), $0.25 (>200k)
        if prompt_tokens > 200000:
            pricing = {"input": 2.50, "output": 15.00, "cached": 0.25}
        else:
            pricing = {"input": 1.25, "output": 10.00, "cached": 0.125}

    elif model_id == "gemini-3-pro" or model_id == "gemini-3-pro-preview":
        # Gemini 3 Pro
        # Input: $2.00 (<=200k), $4.00 (>200k)
        # Output: $12.00 (<=200k), $18.00 (>200k)
        # Cached: $0.20 (<=200k), $0.40 (>200k)
        if prompt_tokens > 200000:
            pricing = {"input": 4.00, "output": 18.00, "cached": 0.40}
        else:
            pricing = {"input": 2.00, "output": 12.00, "cached": 0.20}

    elif model_id == "gemini-2.5-flash-lite":
        # Gemini 2.5 Flash-Lite
        # Input: $0.10
        # Output: $0.40
        # Cached: $0.01
        pricing = {"input": 0.10, "output": 0.40, "cached": 0.01}

    elif model_id == "gemini-2.5-flash":
        # Gemini 2.5 Flash
        # Input: $0.30
        # Output: $2.50
        # Cached: $0.03
        pricing = {"input": 0.30, "output": 2.50, "cached": 0.03}

    elif model_id == "gemini-2.0-flash-lite":
        # Gemini 2.0 Flash-Lite
        # Input: $0.075
        # Output: $0.30
        # Cached: N/A (0)
        pricing = {"input": 0.075, "output": 0.30, "cached": 0.0}

    elif model_id == "gemini-2.0-flash":
        # Gemini 2.0 Flash
        # Input: $0.10
        # Output: $0.40
        # Cached: $0.025
        pricing = {"input": 0.10, "output": 0.40, "cached": 0.025}

    if not pricing:
        return 0

    input_cost = (regular_input_tokens / 1_000_000) * pricing["input"]
    output_cost = (output_tokens / 1_000_000) * pricing["output"]
    cached_cost = (cached_tokens / 1_000_000) * pricing["cached"]

    return input_cost + output_cost + cached_cost


async def call_gemini(messages, tools, model=None):
    model_id = model or config.model
    if model_id.startswith("google/"):
        model_id = model_id.replace("google/", "")

    url = f"https://generativelanguage.googleapis.com/v1beta/models/{model_id}:generateContent?key={config.gemini_api_key}"

    gemini_messages = []
    system_instruction = None

    for msg in messages:
        if msg["role"] == "system":
            system_instruction = {"parts": format_gemini_parts(msg["content"])}
        elif msg["role"] == "user":
            gemini_messages.append(
                {"role": "user", "parts": format_gemini_parts(msg["content"])}
            )
        elif msg["role"] == "assistant":
            parts = []
            if msg.get("content"):
                parts.extend(format_gemini_parts(msg["content"]))
            if msg.get("tool_calls"):
                for tc in msg["tool_calls"]:
                    part = {
                        "functionCall": {
                            "name": tc["function"]["name"],
                            "args": json.loads(tc["function"]["arguments"]),
                        }
                    }
                    if "thought_signature" in tc["function"]:
                        part["thoughtSignature"] = tc["function"]["thought_signature"]

                    parts.append(part)

            if parts:
                gemini_messages.append({"role": "model", "parts": parts})
        elif msg["role"] == "tool":
            gemini_messages.append(
                {
                    "role": "function",
                    "parts": [
                        {
                            "functionResponse": {
                                "name": msg["name"],
                                "response": {"result": msg["content"]},
                            }
                        }
                    ],
                }
            )

    # Check if the last message is a tool response from google_search
    # If so, we need to enable grounding for this turn
    force_grounding_turn = False
    if (
        messages
        and messages[-1]["role"] == "tool"
        and messages[-1]["name"] == "google_search"
    ):
        force_grounding_turn = True

    body = {
        "contents": gemini_messages,
        "tools": map_tools_to_gemini(tools)
        if not force_grounding_turn
        else [{"googleSearch": {}}],
        "generationConfig": {
            "temperature": 0.0  # Agentic
        },
    }

    if system_instruction:
        body["systemInstruction"] = system_instruction

    MAX_RETRIES = 3
    attempt = 0

    while attempt < MAX_RETRIES:
        try:
            response = await asyncio.to_thread(
                requests.post,
                url,
                headers={"Content-Type": "application/json"},
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
                    f"Gemini API error: {response.status_code} - {error_text}"
                )

            data = response.json()

            if "usageMetadata" in data:
                print_formatted_text(
                    HTML(
                        f"<style fg='#666666'>Token Usage: {json.dumps(data['usageMetadata'], indent=2)}</style>"
                    )
                )
                data["usageMetadata"]["cost"] = calculate_gemini_cost(
                    model_id, data["usageMetadata"]
                )

            if "candidates" not in data or not data["candidates"]:
                if data.get("promptFeedback"):
                    raise Exception(
                        f"Blocked by safety: {json.dumps(data['promptFeedback'])}"
                    )
                raise Exception("No candidates returned")

            candidate = data["candidates"][0]
            content = candidate.get("content", {})
            parts = content.get("parts", [])

            message_content = ""
            tool_calls = []

            for part in parts:
                if "text" in part:
                    message_content += part["text"]
                if "functionCall" in part:
                    fc = part["functionCall"]
                    tool_call = {
                        "id": f"call_{int(time.time())}_{random.randint(1000, 9999)}",  # Gemini doesn't give IDs
                        "type": "function",
                        "function": {
                            "name": fc["name"],
                            "arguments": json.dumps(fc["args"]),
                        },
                    }
                    if "thoughtSignature" in part:
                        tool_call["function"]["thought_signature"] = part[
                            "thoughtSignature"
                        ]

                    tool_calls.append(tool_call)

            return {
                "message": {
                    "role": "assistant",
                    "content": message_content,
                    "tool_calls": tool_calls if tool_calls else None,
                },
                "usage": data.get("usageMetadata"),
            }

        except requests.exceptions.RequestException as e:
            logger.warning(f"Attempt {attempt + 1} failed: Network error. Retrying...")
            attempt += 1
            await asyncio.sleep(1 * (2**attempt))
            continue

    raise Exception("Failed to call Gemini API after retries.")
