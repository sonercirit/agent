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

        const cachedTokens = usage.prompt_tokens_details?.cached_tokens || usage.cachedContentTokenCount || 0;
        if (cachedTokens > 0) {
          hasSeenCachedTokens = true;
        }

        if (hasSeenCachedTokens && cachedTokens === 0) {
          // Gemini cache TTL is 60 minutes (default), Anthropic is 5 minutes
          const isGemini = config.provider === 'gemini' || config.model.includes('gemini');
          const cacheTTL = isGemini ? 60.0 : 5.0;
          const reason = elapsedMinutes < (cacheTTL - 1) ? "Prefix mismatch or Checkpoint limit" : "Cache TTL expired";
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
 * Implements a rolling window of checkpoints to stay within the 4-checkpoint limit.
 * @param {Array} messages 
 */
function manageCache(messages) {
  const isAnthropic = config.model.includes('anthropic') || config.model.includes('claude');
  const isGemini = config.model.includes('gemini');
  
  // Only apply caching for supported models
  if (!isAnthropic && !isGemini) {
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

  // 2. Manage History Checkpoints
  // Gemini: Only uses the LAST cache_control breakpoint (OpenRouter limitation)
  // Anthropic: Can use up to 4 checkpoints total
  
  if (isGemini) {
    // For Gemini: Only add cache_control to the most recent cacheable message
    // This ensures we cache the longest possible prefix
    // Remove all existing cache_control from non-system messages first
    for (let i = 0; i < messages.length; i++) {
      const msg = messages[i];
      if (msg.role === 'system') continue;
      
      if (Array.isArray(msg.content)) {
        msg.content.forEach(block => {
          if (block.cache_control) delete block.cache_control;
        });
      }
    }
    
    // Find the last cacheable message (must have content)
    let lastCacheableIndex = -1;
    for (let i = messages.length - 1; i >= 0; i--) {
      const msg = messages[i];
      if (msg.role === 'system') continue;
      
      const hasContent = msg.content && (typeof msg.content === 'string' || (Array.isArray(msg.content) && msg.content.length > 0));
      if (hasContent) {
        lastCacheableIndex = i;
        break;
      }
    }
    
    // Add cache_control to the last cacheable message
    if (lastCacheableIndex !== -1) {
      const msg = messages[lastCacheableIndex];
      if (typeof msg.content === 'string') {
        msg.content = [{ type: "text", text: msg.content, cache_control: { type: "ephemeral" } }];
      } else if (Array.isArray(msg.content) && msg.content.length > 0) {
        msg.content[msg.content.length - 1].cache_control = { type: "ephemeral" };
      }
      console.log(`\x1b[32m[Cache] Gemini checkpoint set at message ${lastCacheableIndex} (Role: ${msg.role})\x1b[0m`);
    }
    
  } else if (isAnthropic) {
    // Anthropic: Use rolling window with multiple checkpoints
    const SYSTEM_AND_TOOLS_CHECKPOINTS = 2;
    const MAX_CHECKPOINTS = 4;
    const HISTORY_CHECKPOINTS_QUOTA = MAX_CHECKPOINTS - SYSTEM_AND_TOOLS_CHECKPOINTS; // 2
    const CHECKPOINT_INTERVAL = 8; 

    // Calculate desired checkpoint indices based on interval
    const candidateIndices = [];

    // Identify potential candidates (Every Nth message)
    for (let i = 0; i < messages.length; i++) {
      const msg = messages[i];
      if (msg.role === 'system') continue;

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
           const hasContent = m.content && (typeof m.content === 'string' || (Array.isArray(m.content) && m.content.length > 0));
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
      if (msg.role === 'system') continue;

      const isDesired = finalIndices.includes(i);
      let hasCheckpoint = false;
      
      if (Array.isArray(msg.content)) {
        hasCheckpoint = msg.content.some(block => block.cache_control);
      } else if (typeof msg.content === 'string') {
        hasCheckpoint = false;
      }

      if (hasCheckpoint && !isDesired) {
        // Remove checkpoint
        if (Array.isArray(msg.content)) {
          msg.content.forEach(block => {
            if (block.cache_control) delete block.cache_control;
          });
        }
        console.log(`\x1b[33m[Cache] Checkpoint removed at message ${i}\x1b[0m`);
      } else if (!hasCheckpoint && isDesired) {
        // Add checkpoint
        if (typeof msg.content === 'string') {
          msg.content = [{ type: "text", text: msg.content }];
        }
        
        if (Array.isArray(msg.content) && msg.content.length > 0) {
          msg.content[msg.content.length - 1].cache_control = { type: "ephemeral" };
          console.log(`\x1b[32m[Cache] Checkpoint added at message ${i} (Role: ${msg.role})\x1b[0m`);
        }
      }
    }
  }
}
