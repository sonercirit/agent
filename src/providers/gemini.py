import requests
import json
import time
import asyncio
import random
import logging
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

    force_grounding = False
    if tools:
        for t in tools:
            if t["function"]["name"] == "__google_search_trigger__":
                force_grounding = True
                break

    if force_grounding:
        gemini_tools.append({"googleSearch": {}})
        return gemini_tools

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

    body = {
        "contents": gemini_messages,
        "tools": map_tools_to_gemini(tools),
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
                logger.debug(
                    f"Token Usage: {json.dumps(data['usageMetadata'], indent=2)}"
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
