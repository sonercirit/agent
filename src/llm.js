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
 * @returns {Promise<Object>} The response message.
 */
export async function callLLM(messages, tools) {
  if (config.provider === "gemini") {
    return await callGemini(messages, tools);
  } else {
    return await callOpenRouter(messages, tools);
  }
}
