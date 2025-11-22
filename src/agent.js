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
import { readMultilineInput } from "./editor.js";

const colors = {
  reset: "\x1b[0m",
  red: "\x1b[31m",
  green: "\x1b[32m",
  yellow: "\x1b[33m",
  blue: "\x1b[34m",
  magenta: "\x1b[35m",
  cyan: "\x1b[36m",
  white: "\x1b[37m",
  gray: "\x1b[90m",
  bold: "\x1b[1m",
  dim: "\x1b[2m",
};

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
    `${colors.cyan}Agent started in ${config.mode} mode using model ${config.model}${colors.reset}`,
  );
  console.log(`${colors.dim}Type 'exit' to quit.${colors.reset}`);

  while (true) {
    console.log(
      `\n${colors.bold}${colors.white}User (Ctrl+S to send):${colors.reset}`,
    );
    const content = await readMultilineInput();

    if (content.trim().toLowerCase() === "exit") {
      process.exit(0);
    }

    if (!content.trim()) {
      continue;
    }

    messages.push({ role: "user", content });
    await processTurn();
  }
}

/**
 * Processes a single turn of the agent.
 */
async function processTurn() {
  let turnFinished = false;
  let interrupted = false;

  const onKey = (str, key) => {
    if (key.ctrl && key.name === "w") {
      interrupted = true;
      process.stdout.write(
        `\n${colors.red}User requested interrupt. Stopping after current step...${colors.reset}\n`,
      );
    }
    if (key.ctrl && key.name === "c") {
      process.exit(0);
    }
  };

  // Setup key listener
  readline.emitKeypressEvents(process.stdin);
  if (process.stdin.isTTY) {
    process.stdin.setRawMode(true);
  }
  process.stdin.on("keypress", onKey);

  try {
    while (!turnFinished && !interrupted) {
      console.log(
        `${colors.dim}Thinking... (Ctrl+W to interrupt)${colors.reset}`,
      );
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
          tools,
        );
        lastRequestTime = Date.now();

        if (usage) {
          handleUsage(usage, elapsedMinutes);
        }

        // Add assistant message to history
        messages.push(responseMessage);

        if (interrupted) {
          break;
        }

        // Show thinking tokens if available
        if (responseMessage.reasoning || responseMessage.reasoning_content) {
          const thinking =
            responseMessage.reasoning || responseMessage.reasoning_content;
          console.log(
            `\n${colors.gray}=== Thinking Process ===${colors.reset}`,
          );
          console.log(`${colors.gray}${thinking}${colors.reset}`);
          console.log(
            `${colors.gray}========================${colors.reset}\n`,
          );
        }

        if (responseMessage.tool_calls) {
          await handleToolCalls(responseMessage.tool_calls);
          // Loop continues to let the model respond to the tool output
        } else if (responseMessage.content && responseMessage.content.trim()) {
          console.log(
            `${colors.green}Agent:${colors.reset} ${responseMessage.content}`,
          );
          turnFinished = true;
        }
      } catch (error) {
        console.error(
          `\n${colors.red}Error during agent execution:${colors.reset}`,
          error.message,
        );
        console.log(
          `${colors.yellow}The current turn has been aborted due to an error. You can try again or enter a new command.${colors.reset}`,
        );
        turnFinished = true;
      }
    }
  } finally {
    // Cleanup key listener
    process.stdin.removeListener("keypress", onKey);
    if (process.stdin.isTTY) {
      process.stdin.setRawMode(false);
    }
  }
}

function handleUsage(usage, elapsedMinutes) {
  if (usage.cost) {
    totalCost += usage.cost;
    console.log(
      `${colors.cyan}Cost: $${usage.cost.toFixed(
        6,
      )} | Total Session Cost: $${totalCost.toFixed(6)}${colors.reset}`,
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
      `${colors.red}WARNING: Cached tokens dropped to 0! (Elapsed: ${elapsedMinutes.toFixed(
        1,
      )} minutes). Cause: ${reason}.${colors.reset}`,
    );
  }
}

async function handleToolCalls(toolCalls) {
  for (const toolCall of toolCalls) {
    const functionName = toolCall.function.name;
    const args = JSON.parse(toolCall.function.arguments);
    const toolFunc = toolImplementations[functionName];

    if (toolFunc) {
      console.log(
        `${colors.yellow}Tool Call: ${functionName}(${JSON.stringify(args)})${colors.reset}`,
      );

      let approved = true;
      if (config.mode === "manual") {
        const wasRaw = process.stdin.isRaw;
        if (wasRaw && process.stdin.setRawMode) {
          process.stdin.setRawMode(false);
        }

        const rl = readline.createInterface({
          input: process.stdin,
          output: process.stdout,
        });
        approved = await askApproval(
          rl,
          `${colors.yellow}Execute this command?${colors.reset}`,
        );
        rl.close();

        if (wasRaw && process.stdin.setRawMode) {
          process.stdin.setRawMode(true);
        }
      }

      let result;
      if (approved) {
        console.log(`${colors.dim}Executing...${colors.reset}`);
        result = await toolFunc(args);
      } else {
        result = "User denied execution of this command.";
      }

      console.log(
        `${colors.blue}Result: ${result.substring(0, 100)}...${colors.reset}`,
      ); // Log brief result

      messages.push({
        role: "tool",
        tool_call_id: toolCall.id,
        name: functionName,
        content: result,
      });
    }
  }
}
