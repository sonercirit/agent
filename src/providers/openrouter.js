import { config } from "../config.js";

/**
 * Calls the OpenRouter API with the given messages and tools.
 * @param {Array} messages - The conversation history.
 * @param {Array} tools - The available tools.
 * @returns {Promise<Object>} The response message.
 */
export async function callOpenRouter(messages, tools) {
  const headers = {
    Authorization: `Bearer ${config.apiKey}`,
    "Content-Type": "application/json",
    "HTTP-Referer": "https://github.com/your-repo/agent", // Optional
    "X-Title": "Agent", // Optional
  };

  const body = {
    model: config.model,
    messages: messages,
    tools: tools,
    usage: { include: true },
    provider: {
      allow_fallbacks: false,
    },
  };

  const MAX_RETRIES = 3;
  let attempt = 0;

  while (attempt < MAX_RETRIES) {
    try {
      const response = await fetch(
        "https://openrouter.ai/api/v1/chat/completions",
        {
          method: "POST",
          headers: headers,
          body: JSON.stringify(body),
        },
      );

      if (!response.ok) {
        const errorText = await response.text();

        // Check for specific errors that might be worth retrying
        const isTransient = response.status >= 500 || response.status === 429;
        const isCorruptedThought =
          response.status === 400 &&
          errorText.includes("Corrupted thought signature");

        if (isTransient || isCorruptedThought) {
          console.warn(
            `Attempt ${attempt + 1} failed: ${
              response.status
            } - ${errorText}. Retrying...`,
          );
          attempt++;
          if (attempt < MAX_RETRIES) {
            await new Promise((resolve) =>
              setTimeout(resolve, 1000 * Math.pow(2, attempt)),
            ); // Exponential backoff
            continue;
          }
        }

        throw new Error(
          `OpenRouter API error: ${response.status} ${response.statusText} - ${errorText}`,
        );
      }

      const data = await response.json();

      if (data.usage) {
        console.log("Token Usage:", JSON.stringify(data.usage, null, 2));
      }

      return {
        message: data.choices[0].message,
        usage: data.usage,
      };
    } catch (error) {
      // If it's a network error (fetch failed), retry
      if (error.name === "TypeError" && error.message === "fetch failed") {
        console.warn(
          `Attempt ${attempt + 1} failed: Network error. Retrying...`,
        );
        attempt++;
        if (attempt < MAX_RETRIES) {
          await new Promise((resolve) =>
            setTimeout(resolve, 1000 * Math.pow(2, attempt)),
          );
          continue;
        }
      }
      console.error("Failed to call OpenRouter:", error);
      throw error;
    }
  }
}
