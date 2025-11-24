import requests
import json
import time
from ..config import config

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
        gemini_tools.append({
            "function_declarations": [
                {
                    "name": t["function"]["name"],
                    "description": t["function"]["description"],
                    "parameters": fix_schema_types(t["function"]["parameters"])
                }
                for t in tools
            ]
        })
        
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
                        parts.append({
                            "inline_data": {
                                "mime_type": mime_type,
                                "data": data
                            }
                        })
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
            gemini_messages.append({
                "role": "user",
                "parts": format_gemini_parts(msg["content"])
            })
        elif msg["role"] == "assistant":
            parts = []
            if msg.get("content"):
                parts.extend(format_gemini_parts(msg["content"]))
            if msg.get("tool_calls"):
                for tc in msg["tool_calls"]:
                    parts.append({
                        "function_call": {
                            "name": tc["function"]["name"],
                            "args": json.loads(tc["function"]["arguments"])
                        }
                    })
            gemini_messages.append({
                "role": "model",
                "parts": parts
            })
        elif msg["role"] == "tool":
            # Gemini expects tool responses in a specific way
            # We need to find the last function call to match? 
            # Actually Gemini just needs the function response part.
            # But we need to be careful about the order.
            # The current agent structure pushes tool outputs as separate messages.
            # We need to group them if possible or just send them as 'function_response' parts.
            
            # For simplicity, we assume the previous message was a model message with function calls.
            # We need to map the tool_call_id if possible, but Gemini uses function name.
            
            gemini_messages.append({
                "role": "function", # Gemini uses 'function' role for responses? No, it uses 'user' role with 'function_response' part usually, or 'function' role in v1beta?
                # v1beta: role: "function" is deprecated or not standard?
                # Standard is: role: "user", parts: [{function_response: ...}]
                # Let's check the docs or existing code.
                # Existing code used: role: "function", parts: [{functionResponse: ...}]
                "parts": [{
                    "functionResponse": {
                        "name": msg["name"],
                        "response": {"content": msg["content"]}
                    }
                }]
            })

    body = {
        "contents": gemini_messages,
        "tools": map_tools_to_gemini(tools),
        "generationConfig": {
            "temperature": 0.7,
            "maxOutputTokens": 8192
        }
    }
    
    if system_instruction:
        body["systemInstruction"] = system_instruction

    MAX_RETRIES = 3
    attempt = 0
    
    while attempt < MAX_RETRIES:
        try:
            response = requests.post(
                url,
                headers={"Content-Type": "application/json"},
                json=body,
                timeout=120
            )
            
            if response.status_code != 200:
                error_text = response.text
                if response.status_code >= 500 or response.status_code == 429:
                    print(f"Attempt {attempt + 1} failed: {response.status_code}. Retrying...")
                    attempt += 1
                    time.sleep(1 * (2 ** attempt))
                    continue
                raise Exception(f"Gemini API error: {response.status_code} - {error_text}")
                
            data = response.json()
            
            if "usageMetadata" in data:
                print(f"\x1b[2mToken Usage: {json.dumps(data['usageMetadata'], indent=2)}\x1b[0m")
                
            if "candidates" not in data or not data["candidates"]:
                # Safety block?
                if data.get("promptFeedback"):
                    raise Exception(f"Blocked by safety: {json.dumps(data['promptFeedback'])}")
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
                    tool_calls.append({
                        "id": f"call_{int(time.time())}_{random.randint(1000,9999)}", # Gemini doesn't give IDs
                        "type": "function",
                        "function": {
                            "name": part["functionCall"]["name"],
                            "arguments": json.dumps(part["functionCall"]["args"])
                        }
                    })
            
            return {
                "message": {
                    "role": "assistant",
                    "content": message_content,
                    "tool_calls": tool_calls if tool_calls else None
                },
                "usage": data.get("usageMetadata")
            }
            
        except requests.exceptions.RequestException as e:
            print(f"Attempt {attempt + 1} failed: Network error. Retrying...")
            attempt += 1
            time.sleep(1 * (2 ** attempt))
            continue
            
    raise Exception("Failed to call Gemini API after retries.")

import random
