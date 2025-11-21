/**
 * Main agent logic.
 * @module agent
 */

import readline from 'readline';
import { config } from './config.js';
import { callLLM } from './llm.js';
import { tools, toolImplementations } from './tools.js';

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

let messages = [
  { role: "system", content: systemPrompt },
];

let totalCost = 0;
let hasSeenCachedTokens = false;
let lastRequestTime = 0;

/**
 * Asks for user approval.
 * @param {string} question - The question to ask.
 * @returns {Promise<boolean>} True if approved.
 */
function askApproval(question) {
  return new Promise((resolve) => {
    rl.question(`${question} (y/n): `, (answer) => {
      resolve(answer.toLowerCase() === 'y');
    });
  });
}

/**
 * Main agent loop.
 */
export async function startAgent() {
  console.log(`Agent started in ${config.mode} mode using model ${config.model}`);
  console.log("Type 'exit' to quit.");

  const askUser = () => {
    rl.question('User: ', async (input) => {
      if (input.toLowerCase() === 'exit') {
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
      const { message: responseMessage, usage } = await callLLM(messages, tools);
      lastRequestTime = Date.now();
      
      if (usage) {
        if (usage.cost) {
          totalCost += usage.cost;
          console.log(`Total Session Cost: $${totalCost.toFixed(6)}`);
        }

        const cachedTokens = usage.prompt_tokens_details?.cached_tokens || 0;
        if (cachedTokens > 0) {
          hasSeenCachedTokens = true;
        }

        if (hasSeenCachedTokens && cachedTokens === 0) {
          const reason = elapsedMinutes < 4.0 ? "Prefix mismatch or Checkpoint limit" : "Cache TTL expired";
          console.log(`\x1b[31mWARNING: Cached tokens dropped to 0! (Elapsed: ${elapsedMinutes.toFixed(1)} minutes). Cause: ${reason}.\x1b[0m`);
        }
      }
      
      // Add assistant message to history
      messages.push(responseMessage);

      if (responseMessage.tool_calls) {
        for (const toolCall of responseMessage.tool_calls) {
          const functionName = toolCall.function.name;
          const args = JSON.parse(toolCall.function.arguments);
          const toolFunc = toolImplementations[functionName];

          if (toolFunc) {
            console.log(`Tool Call: ${functionName}(${JSON.stringify(args)})`);
            
            let approved = true;
            if (config.mode === 'manual') {
              approved = await askApproval("Execute this command?");
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
        // Loop continues to let the model respond to the tool output
      } else {
        console.log(`Agent: ${responseMessage.content}`);
        turnFinished = true;
      }
    } catch (error) {
      console.error("\n\x1b[31mError during agent execution:\x1b[0m", error.message);
      console.log("The current turn has been aborted due to an error. You can try again or enter a new command.");
      turnFinished = true;
    }
  }
}

/**
 * Manages cache control headers in messages.
 * Adds explicit cache checkpoints to the system prompt and periodically in the history.
 * @param {Array} messages 
 */
function manageCache(messages) {
  // Only apply Anthropic-style caching for Anthropic models
  if (!config.model.includes('anthropic') && !config.model.includes('claude')) {
    return;
  }

  // 1. Ensure System Prompt has cache_control
  const systemMsg = messages.find(m => m.role === 'system');
  if (systemMsg) {
    if (typeof systemMsg.content === 'string') {
      systemMsg.content = [{ type: "text", text: systemMsg.content, cache_control: { type: "ephemeral" } }];
    } else if (Array.isArray(systemMsg.content)) {
      // Check if already has cache_control
      const hasCache = systemMsg.content.some(block => block.cache_control);
      if (!hasCache && systemMsg.content.length > 0) {
        // Add to the last block
        systemMsg.content[systemMsg.content.length - 1].cache_control = { type: "ephemeral" };
      }
    }
  }

  // 2. Add checkpoints every N messages
  // Limit is 4 checkpoints total. 
  // - System Prompt: 1
  // - Tools definitions (always sent): 1
  // - History: 2 remaining slots.
  // We start count at 2 to account for System and Tools.
  
  let checkpointsUsed = 2; 
  const CHECKPOINT_INTERVAL = 8; // Reduced from 25 to ensure we use checkpoints earlier

  for (let i = 0; i < messages.length; i++) {
    const msg = messages[i];
    if (msg.role === 'system') continue;

    // Check if this message already has a checkpoint
    let hasCheckpoint = false;
    if (Array.isArray(msg.content)) {
      hasCheckpoint = msg.content.some(block => block.cache_control);
    }

    if (hasCheckpoint) {
      checkpointsUsed++;
      continue;
    }

    // If we have budget and it's time to add a checkpoint
    if (checkpointsUsed < 4 && i > 0 && i % CHECKPOINT_INTERVAL === 0) {
      // Convert content to array if string
      if (typeof msg.content === 'string') {
        msg.content = [{ type: "text", text: msg.content }];
      }
      
      // Add cache_control to the last block
      if (Array.isArray(msg.content) && msg.content.length > 0) {
        msg.content[msg.content.length - 1].cache_control = { type: "ephemeral" };
        checkpointsUsed++;
        console.log(`\x1b[32m[Cache] Checkpoint added at message ${i} (Total: ${checkpointsUsed})\x1b[0m`);
      }
    }
  }
}
