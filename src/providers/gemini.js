import { config } from "../config.js";

/**
 * Recursively converts schema types to uppercase for Gemini compatibility.
 * @param {Object} schema - The schema object.
 * @returns {Object} The schema with uppercase types.
 */
function fixSchemaTypes(schema) {
  if (!schema || typeof schema !== "object") return schema;

  const newSchema = { ...schema };

  if (newSchema.type && typeof newSchema.type === "string") {
    newSchema.type = newSchema.type.toUpperCase();
  }

  if (newSchema.properties) {
    const newProps = {};
    for (const [key, prop] of Object.entries(newSchema.properties)) {
      newProps[key] = fixSchemaTypes(prop);
    }
    newSchema.properties = newProps;
  }

  if (newSchema.items) {
    newSchema.items = fixSchemaTypes(newSchema.items);
  }

  return newSchema;
}

/**
 * Maps OpenAI tools format to Gemini tools format.
 * @param {Array} tools - OpenAI format tools.
 * @returns {Array} Gemini format tools.
 */
function mapToolsToGemini(tools) {
  const geminiTools = [];

  // Check for our special internal trigger for grounding
  const forceGrounding =
    tools &&
    tools.some(
      (t) => t.function && t.function.name === "__google_search_trigger__",
    );

  if (forceGrounding) {
    // If specifically requested via the special trigger, we ONLY enable Google Search
    // and ignore other function declarations to avoid the "unsupported combination" error.
    geminiTools.push({ googleSearch: {} });
    return geminiTools;
  }

  if (tools && tools.length > 0) {
    geminiTools.push({
      function_declarations: tools.map((t) => ({
        name: t.function.name,
        description: t.function.description,
        parameters: fixSchemaTypes(t.function.parameters),
      })),
    });
  }

  // NOTE: Google Search Grounding and Function Calling cannot be used in the same request
  // for the current Gemini models (as of late 2024/early 2025).
  // We must choose one or the other.
  // Since the user explicitly requested to "enable Grounding with Google Search" and
  // the agent heavily relies on tools (function calling), we are in a bind.
  //
  // However, if we simply remove the function declarations when we want to search,
  // the agent loses its other capabilities.
  //
  // Current workaround:
  // If tools are provided, we prioritize tools (function calling).
  // If we want to use Google Search, we would technically need to disable tools.
  //
  // But the user wants to replace the `web_search` tool with native grounding.
  // This implies the model should decide when to search.
  //
  // Since we can't have both enabled simultaneously in the same request payload:
  // We will ONLY enable function calling if tools are present.
  // We will ONLY enable Google Search if NO tools are present (which is rare for this agent).
  //
  // WAITING FOR GOOGLE TO FIX THIS LIMITATION OR USING LIVE API IS THE LONG TERM FIX.
  //
  // FOR NOW: We will disable Google Search Grounding to restore agent functionality
  // regarding function calls, as breaking the agent is worse.
  // We will add a specific "google_search" tool that the agent can CALL, which then
  // triggers a second request to Gemini with ONLY googleSearch enabled and NO tools.
  // This is the "Sub-agent" or "Two-step" pattern.

  // Reverting to just tools for now to fix the crash.
  // We will implement the "native search tool" pattern in the next step.

  // geminiTools.push({ googleSearch: {} });

  return geminiTools;
}

/**
 * Helper to format content into Gemini parts.
 * Handles string or array of content parts.
 * @param {string|Array} content
 * @returns {Array} Array of Gemini parts
 */
function formatGeminiParts(content) {
  if (!content) return [];
  if (typeof content === "string") {
    return [{ text: content }];
  }
  if (Array.isArray(content)) {
    return content
      .map((part) => {
        if (typeof part === "string") return { text: part };
        if (part.type === "text") return { text: part.text };
        // For now, we skip image_url as we haven't implemented it fully
        // and passing it as text might be confusing.
        // If strictly text needed, we could ignore non-text parts.
        return null;
      })
      .filter(Boolean);
  }
  return [{ text: String(content) }];
}

/**
 * Maps OpenAI messages format to Gemini contents format.
 * @param {Array} messages - OpenAI format messages.
 * @returns {Object} { contents, systemInstruction }
 */
function mapMessagesToGemini(messages) {
  let systemInstruction = undefined;
  const contents = [];

  for (const msg of messages) {
    if (msg.role === "system") {
      systemInstruction = { parts: formatGeminiParts(msg.content) };
    } else if (msg.role === "user") {
      contents.push({
        role: "user",
        parts: formatGeminiParts(msg.content),
      });
    } else if (msg.role === "assistant") {
      // If we have preserved Gemini parts from a previous turn, use them directly
      if (msg.provider_metadata && msg.provider_metadata.gemini_parts) {
        contents.push({
          role: "model",
          parts: msg.provider_metadata.gemini_parts,
        });
      } else {
        // Fallback to reconstruction
        const parts = [];
        if (msg.content) {
          parts.push(...formatGeminiParts(msg.content));
        }
        if (msg.tool_calls) {
          for (const toolCall of msg.tool_calls) {
            parts.push({
              functionCall: {
                name: toolCall.function.name,
                args: JSON.parse(toolCall.function.arguments),
              },
            });
          }
        }
        contents.push({
          role: "model",
          parts: parts,
        });
      }
    } else if (msg.role === "tool") {
      contents.push({
        role: "function", // Internal mapping helper, will be converted to user
        parts: [
          {
            functionResponse: {
              name: msg.name,
              response: { result: msg.content },
            },
          },
        ],
      });
    }
  }

  // Post-processing to merge consecutive roles if necessary
  const finalContents = [];
  for (const item of contents) {
    if (item.role === "function") {
      const last = finalContents[finalContents.length - 1];
      if (last && last.role === "user") {
        last.parts.push(item.parts[0]);
      } else {
        finalContents.push({
          role: "user",
          parts: item.parts,
        });
      }
    } else {
      finalContents.push(item);
    }
  }

  return { contents: finalContents, systemInstruction };
}

/**
 * Calculates the cost of the Gemini API call.
 * @param {string} model - The model name.
 * @param {Object} usage - The usage metadata.
 * @returns {number} The calculated cost in USD.
 */
function calculateGeminiCost(model, usage) {
  if (!usage) return 0;

  const isPro = model.includes("pro");
  const promptTokens = usage.promptTokenCount || 0;
  const outputTokens =
    (usage.candidatesTokenCount || 0) + (usage.thoughtsTokenCount || 0);
  const cachedTokens = usage.cachedContentTokenCount || 0;

  // Effective input tokens (excluding cached which have their own rate)
  // Note: We assume promptTokenCount includes cachedTokens.
  // If it doesn't, this logic might need adjustment, but typically Total = Prompt + Candidates.
  // And Prompt = Uncached + Cached.
  const regularInputTokens = Math.max(0, promptTokens - cachedTokens);

  let inputRate, outputRate, cachedRate;

  if (isPro) {
    // Gemini 3 Pro Pricing
    if (promptTokens > 200000) {
      inputRate = 4.0;
      outputRate = 18.0;
      cachedRate = 0.4;
    } else {
      inputRate = 2.0;
      outputRate = 12.0;
      cachedRate = 0.2;
    }
  } else {
    // Gemini 1.5 Flash Pricing
    if (promptTokens > 128000) {
      inputRate = 0.15;
      outputRate = 0.6;
      cachedRate = 0.0375;
    } else {
      inputRate = 0.075;
      outputRate = 0.3;
      cachedRate = 0.01875;
    }
  }

  const inputCost = (regularInputTokens / 1_000_000) * inputRate;
  const outputCost = (outputTokens / 1_000_000) * outputRate;
  const cachedCost = (cachedTokens / 1_000_000) * cachedRate;

  return inputCost + outputCost + cachedCost;
}

/**
 * Calls the Gemini API.
 * @param {Array} messages - The conversation history.
 * @param {Array} tools - The available tools.
 * @returns {Promise<Object>} The response message.
 */
export async function callGemini(messages, tools) {
  if (!config.geminiApiKey) {
    throw new Error("GEMINI_API_KEY is not set.");
  }

  const { contents, systemInstruction } = mapMessagesToGemini(messages);
  const geminiTools = mapToolsToGemini(tools);

  // Construct URL
  const modelName = config.model.includes("gemini")
    ? config.model
    : "gemini-1.5-flash";
  // Strip 'google/' if present for the API call if usage assumes openrouter naming
  const cleanModelName = modelName.replace("google/", "");

  const url = `https://generativelanguage.googleapis.com/v1beta/models/${cleanModelName}:generateContent?key=${config.geminiApiKey}`;

  const body = {
    contents,
    system_instruction: systemInstruction,
    tools: geminiTools,
    generationConfig: {
      temperature: 0.0, // default
    },
  };

  // console.log("Gemini Request Body:", JSON.stringify(body, null, 2));

  const response = await fetch(url, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });

  if (!response.ok) {
    const text = await response.text();
    throw new Error(`Gemini API Error: ${response.status} - ${text}`);
  }

  const data = await response.json();

  if (data.usageMetadata) {
    console.log("\x1b[2mToken Usage:", JSON.stringify(data.usageMetadata, null, 2), "\x1b[0m");
    data.usageMetadata.cost = calculateGeminiCost(
      cleanModelName,
      data.usageMetadata,
    );
  }

  // Map response back to OpenAI format
  const candidate = data.candidates && data.candidates[0];
  if (!candidate) {
    throw new Error("No candidates returned from Gemini");
  }

  const contentParts = candidate.content.parts || [];
  let content = "";
  let reasoning = "";
  const toolCalls = [];

  for (const part of contentParts) {
    if (part.thought) {
      reasoning += part.text + "\n";
    } else if (part.text) {
      content += part.text;
    }

    if (part.functionCall) {
      toolCalls.push({
        id: `call_${Math.random().toString(36).substr(2, 9)}`,
        type: "function",
        function: {
          name: part.functionCall.name,
          arguments: JSON.stringify(part.functionCall.args),
        },
      });
    }
  }

  const message = {
    role: "assistant",
    content: content || null,
    reasoning: reasoning || null,
    provider_metadata: {
      gemini_parts: contentParts, // Preserve original parts including thoughts/signatures
      grounding_metadata: candidate.groundingMetadata, // Capture grounding metadata
    },
  };
  if (toolCalls.length > 0) {
    message.tool_calls = toolCalls;
  }

  return {
    message,
    usage: data.usageMetadata,
  };
}
