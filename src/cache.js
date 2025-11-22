/**
 * Cache management logic.
 * @module cache
 */

import { config } from "./config.js";

/**
 * Manages cache control headers in messages.
 * Adds explicit cache checkpoints to the system prompt and periodically in the history.
 * Implements a rolling window of checkpoints to stay within the 4-checkpoint limit.
 * @param {Array} messages
 */
export function manageCache(messages) {
  const isAnthropic =
    config.model.includes("anthropic") || config.model.includes("claude");

  // Only apply caching for supported models
  // Gemini: Disable explicit caching (checkpoints) to avoid paid cache usage and rely on free implicit caching
  if (!isAnthropic) {
    return;
  }

  // 1. Ensure System Prompt has cache_control
  const systemMsg = messages.find((m) => m.role === "system");
  if (systemMsg) {
    if (typeof systemMsg.content === "string") {
      systemMsg.content = [
        {
          type: "text",
          text: systemMsg.content,
          cache_control: { type: "ephemeral" },
        },
      ];
    } else if (Array.isArray(systemMsg.content)) {
      // Check if already has cache_control
      const hasCache = systemMsg.content.some((block) => block.cache_control);
      if (!hasCache && systemMsg.content.length > 0) {
        // Add to the last block
        systemMsg.content[systemMsg.content.length - 1].cache_control = {
          type: "ephemeral",
        };
      }
    }
  }

  // 2. Manage History Checkpoints
  // Anthropic: Can use up to 4 checkpoints total

  if (isAnthropic) {
    // Anthropic: Use rolling window with multiple checkpoints
    const SYSTEM_AND_TOOLS_CHECKPOINTS = 2;
    const MAX_CHECKPOINTS = 4;
    const HISTORY_CHECKPOINTS_QUOTA =
      MAX_CHECKPOINTS - SYSTEM_AND_TOOLS_CHECKPOINTS; // 2
    const CHECKPOINT_INTERVAL = 8;

    // Calculate desired checkpoint indices based on interval
    const candidateIndices = [];

    // Identify potential candidates (Every Nth message)
    for (let i = 0; i < messages.length; i++) {
      const msg = messages[i];
      if (msg.role === "system") continue;

      if (i % CHECKPOINT_INTERVAL === 0 && i > 0) {
        candidateIndices.push(i);
      }
    }

    // Resolve candidates to actual valid cacheable messages
    let finalIndices = [];

    for (const index of candidateIndices) {
      let bestIndex = -1;
      const searchOrder = [index, index - 1, index + 1, index - 2, index + 2];

      for (const searchIdx of searchOrder) {
        if (searchIdx > 0 && searchIdx < messages.length) {
          const m = messages[searchIdx];
          const hasContent =
            m.content &&
            (typeof m.content === "string" ||
              (Array.isArray(m.content) && m.content.length > 0));
          if (hasContent) {
            bestIndex = searchIdx;
            break;
          }
        }
      }

      if (bestIndex !== -1) {
        if (!finalIndices.includes(bestIndex)) {
          finalIndices.push(bestIndex);
        }
      }
    }

    // Keep only the last N desired indices
    if (finalIndices.length > HISTORY_CHECKPOINTS_QUOTA) {
      finalIndices = finalIndices.slice(-HISTORY_CHECKPOINTS_QUOTA);
    }

    // Apply changes to messages
    for (let i = 0; i < messages.length; i++) {
      const msg = messages[i];
      if (msg.role === "system") continue;

      const isDesired = finalIndices.includes(i);
      let hasCheckpoint = false;

      if (Array.isArray(msg.content)) {
        hasCheckpoint = msg.content.some((block) => block.cache_control);
      } else if (typeof msg.content === "string") {
        hasCheckpoint = false;
      }

      if (hasCheckpoint && !isDesired) {
        // Remove checkpoint
        if (Array.isArray(msg.content)) {
          msg.content.forEach((block) => {
            if (block.cache_control) delete block.cache_control;
          });
        }
        console.log(
          `\x1b[33m[Cache] Checkpoint removed at message ${i}\x1b[0m`,
        );
      } else if (!hasCheckpoint && isDesired) {
        // Add checkpoint
        if (typeof msg.content === "string") {
          msg.content = [{ type: "text", text: msg.content }];
        }

        if (Array.isArray(msg.content) && msg.content.length > 0) {
          msg.content[msg.content.length - 1].cache_control = {
            type: "ephemeral",
          };
          console.log(
            `\x1b[32m[Cache] Checkpoint added at message ${i} (Role: ${msg.role})\x1b[0m`,
          );
        }
      }
    }
  }
}
