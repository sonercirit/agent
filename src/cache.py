from .config import config

def manage_cache(messages):
    is_anthropic = "anthropic" in config.model or "claude" in config.model
    
    if not is_anthropic:
        return
        
    # 1. Ensure System Prompt has cache_control
    system_msg = next((m for m in messages if m["role"] == "system"), None)
    if system_msg:
        if isinstance(system_msg["content"], str):
            system_msg["content"] = [
                {
                    "type": "text",
                    "text": system_msg["content"],
                    "cache_control": {"type": "ephemeral"}
                }
            ]
        elif isinstance(system_msg["content"], list):
            has_cache = any(block.get("cache_control") for block in system_msg["content"])
            if not has_cache and system_msg["content"]:
                system_msg["content"][-1]["cache_control"] = {"type": "ephemeral"}
                
    # 2. Manage History Checkpoints
    SYSTEM_AND_TOOLS_CHECKPOINTS = 2
    MAX_CHECKPOINTS = 4
    HISTORY_CHECKPOINTS_QUOTA = MAX_CHECKPOINTS - SYSTEM_AND_TOOLS_CHECKPOINTS
    CHECKPOINT_INTERVAL = 8
    
    candidate_indices = []
    for i, msg in enumerate(messages):
        if msg["role"] == "system": continue
        if i % CHECKPOINT_INTERVAL == 0 and i > 0:
            candidate_indices.append(i)
            
    final_indices = []
    for index in candidate_indices:
        best_index = -1
        search_order = [index, index - 1, index + 1, index - 2, index + 2]
        
        for search_idx in search_order:
            if 0 < search_idx < len(messages):
                m = messages[search_idx]
                has_content = m.get("content") and (isinstance(m["content"], str) or (isinstance(m["content"], list) and len(m["content"]) > 0))
                if has_content:
                    best_index = search_idx
                    break
        
        if best_index != -1 and best_index not in final_indices:
            final_indices.append(best_index)
            
    if len(final_indices) > HISTORY_CHECKPOINTS_QUOTA:
        final_indices = final_indices[-HISTORY_CHECKPOINTS_QUOTA:]
        
    for i, msg in enumerate(messages):
        if msg["role"] == "system": continue
        
        is_desired = i in final_indices
        has_checkpoint = False
        
        if isinstance(msg["content"], list):
            has_checkpoint = any(block.get("cache_control") for block in msg["content"])
        
        if has_checkpoint and not is_desired:
            if isinstance(msg["content"], list):
                for block in msg["content"]:
                    if "cache_control" in block:
                        del block["cache_control"]
            print(f"\x1b[33m[Cache] Checkpoint removed at message {i}\x1b[0m")
            
        elif not has_checkpoint and is_desired:
            if isinstance(msg["content"], str):
                msg["content"] = [
                    {"type": "text", "text": msg["content"], "cache_control": {"type": "ephemeral"}}
                ]
            elif isinstance(msg["content"], list):
                if msg["content"]:
                    msg["content"][-1]["cache_control"] = {"type": "ephemeral"}
            print(f"\x1b[32m[Cache] Checkpoint added at message {i}\x1b[0m")
