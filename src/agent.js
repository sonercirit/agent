/**
 * Main agent logic.
 * @module agent
 */

import readline from "readline";
import { config } from "./config.js";
import { callLLM } from "./llm.js";
import { tools, toolImplementations } from "./tools.js";
import { manageCache } from "./cache.js";
import { askApproval } from "./utils.js";

const rl = readline.createInterface({
  input: process.stdin,
  output: process.stdout,
});

const systemPrompt = `You are a powerful agentic AI assistant.
You have access to a bash tool which allows you to do almost anything on the system.
You should use this tool to accomplish the user's requests.
You are optimized for high reasoning and complex tasks.
Always verify your actions and output.
If you need to run a command, just do it.
The user has set a strict output limit of 1k tokens per tool call. If you see truncated output, refine your command (e.g., use grep, head, tail) to get the specific information you need.`;

let messages = [{ role: "system", content: systemPrompt }];

let totalCost = 0;
let hasSeenCachedTokens = false;
let lastRequestTime = 0;

/**
 * Main agent loop.
 */
export async function startAgent() {
  console.log(
    `Agent started in ${config.mode} mode using model ${config.model}`
  );
  console.log("Type 'exit' to quit.");

  const askUser = () => {
    rl.question("User: ", async (input) => {
      if (input.toLowerCase() === "exit") {
        rl.close();
        return;
      }

      messages.push({ role: "user", content: input });

      await processTurn();

      askUser();
    });
  };

  askUser();
}

/**
 * Processes a single turn of the agent.
 */
async function processTurn() {
  let turnFinished = false;

  while (!turnFinished) {
    console.log("Thinking...");
    try {
      // Manage cache checkpoints before calling LLM
      manageCache(messages);

      const currentTime = Date.now();
      let elapsedMinutes = 0;
      if (lastRequestTime > 0) {
        elapsedMinutes = (currentTime - lastRequestTime) / 60000;
      }
      
      const { message: responseMessage, usage } = await callLLM(
        messages,
        tools
      );
      lastRequestTime = Date.now();

      if (usage) {
        handleUsage(usage, elapsedMinutes);
      }

      // Add assistant message to history
      messages.push(responseMessage);

      if (responseMessage.tool_calls) {
        await handleToolCalls(responseMessage.tool_calls);
        // Loop continues to let the model respond to the tool output
      } else {
        console.log(`Agent: ${responseMessage.content}`);
        turnFinished = true;
      }
    } catch (error) {
      console.error(
        "\n\x1b[31mError during agent execution:\x1b[0m",
        error.message
      );
      console.log(
        "The current turn has been aborted due to an error. You can try again or enter a new command."
      );
      turnFinished = true;
    }
  }
}

function handleUsage(usage, elapsedMinutes) {
  if (usage.cost) {
    totalCost += usage.cost;
    console.log(
      `Cost: $${usage.cost.toFixed(
        6
      )} | Total Session Cost: $${totalCost.toFixed(6)}`
    );
  }

  const cachedTokens =
    usage.prompt_tokens_details?.cached_tokens ||
    usage.cachedContentTokenCount ||
    0;
  if (cachedTokens > 0) {
    hasSeenCachedTokens = true;
  }

  if (hasSeenCachedTokens && cachedTokens === 0) {
    // Gemini cache TTL is 60 minutes (default), Anthropic is 5 minutes
    const isGemini =
      config.provider === "gemini" || config.model.includes("gemini");

    // For Gemini, we use implicit caching. If we've seen cached tokens before and now see 0,
    // it likely means the prefix changed or TTL expired.
    const cacheTTL = isGemini ? 60.0 : 5.0;
    const reason =
      elapsedMinutes < cacheTTL - 1
        ? "Prefix mismatch or Checkpoint limit"
        : "Cache TTL expired";
    console.log(
      `\x1b[31mWARNING: Cached tokens dropped to 0! (Elapsed: ${elapsedMinutes.toFixed(
        1
      )} minutes). Cause: ${reason}.\x1b[0m`
    );
  }
}

async function handleToolCalls(toolCalls) {
  for (const toolCall of toolCalls) {
    const functionName = toolCall.function.name;
    const args = JSON.parse(toolCall.function.arguments);
    const toolFunc = toolImplementations[functionName];

    if (toolFunc) {
      console.log(`Tool Call: ${functionName}(${JSON.stringify(args)})`);

      let approved = true;
      if (config.mode === "manual") {
        approved = await askApproval(rl, "Execute this command?");
      }

      let result;
      if (approved) {
        console.log("Executing...");
        result = await toolFunc(args);
      } else {
        result = "User denied execution of this command.";
      }

      console.log(`Result: ${result.substring(0, 100)}...`); // Log brief result

      messages.push({
        role: "tool",
        tool_call_id: toolCall.id,
        name: functionName,
        content: result,
      });
    }
  }
}
