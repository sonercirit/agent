"""Anthropic prompt caching management for OpenRouter."""

import logging

logger = logging.getLogger(__name__)


def apply_anthropic_cache(messages: list, model: str):
    """Apply Anthropic cache_control markers to messages (mutates in-place)."""
    if "anthropic" not in model.lower() and "claude" not in model.lower():
        return

    # Cache system prompt
    for msg in messages:
        if msg["role"] == "system":
            if isinstance(msg["content"], str):
                msg["content"] = [{"type": "text", "text": msg["content"], "cache_control": {"type": "ephemeral"}}]
            elif isinstance(msg["content"], list) and msg["content"]:
                if not any(b.get("cache_control") for b in msg["content"]):
                    msg["content"][-1]["cache_control"] = {"type": "ephemeral"}
            break

    # Add checkpoints every N messages (max 2 for history, keeping 2 for system+tools)
    CHECKPOINT_INTERVAL = 8
    MAX_HISTORY_CHECKPOINTS = 2

    candidates = [i for i, m in enumerate(messages) if m["role"] != "system" and i > 0 and i % CHECKPOINT_INTERVAL == 0]

    # Find valid checkpoint indices (messages with content)
    checkpoints = []
    for idx in candidates:
        for offset in [0, -1, 1, -2, 2]:
            check_idx = idx + offset
            if 0 < check_idx < len(messages):
                m = messages[check_idx]
                has_content = m.get("content") and (
                    isinstance(m["content"], str) or (isinstance(m["content"], list) and m["content"])
                )
                if has_content and check_idx not in checkpoints:
                    checkpoints.append(check_idx)
                    break

    checkpoints = checkpoints[-MAX_HISTORY_CHECKPOINTS:]

    # Apply/remove cache markers
    for i, msg in enumerate(messages):
        if msg["role"] == "system":
            continue

        is_checkpoint = i in checkpoints
        has_cache = isinstance(msg["content"], list) and any(b.get("cache_control") for b in msg["content"])

        if has_cache and not is_checkpoint:
            for block in msg["content"]:
                block.pop("cache_control", None)
        elif not has_cache and is_checkpoint:
            if isinstance(msg["content"], str):
                msg["content"] = [{"type": "text", "text": msg["content"], "cache_control": {"type": "ephemeral"}}]
            elif isinstance(msg["content"], list) and msg["content"]:
                msg["content"][-1]["cache_control"] = {"type": "ephemeral"}
