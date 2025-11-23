/**
 * LLM interaction logic using configured provider.
 * @module llm
 */

import { config } from "./config.js";
import { callOpenRouter } from "./providers/openrouter.js";
import { callGemini } from "./providers/gemini.js";

/**
 * Calls the LLM with the given messages and tools.
 * @param {Array} messages - The conversation history.
 * @param {Array} tools - The available tools.
 * @param {string} [model] - Optional model override.
 * @returns {Promise<Object>} The response message.
 */
export async function callLLM(messages, tools, model = null) {
  if (config.provider === "gemini") {
    return await callGemini(messages, tools, model);
  } else {
    return await callOpenRouter(messages, tools, model);
  }
}
