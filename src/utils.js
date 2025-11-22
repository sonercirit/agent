/**
 * Utility functions.
 * @module utils
 */

import { config } from "./config.js";

/**
 * Helper to enforce output limits.
 * @param {string} output - The output string.
 * @param {boolean} isError - Whether the output is an error message.
 * @returns {string} The limited output.
 */
export function limitOutput(output, isError = false) {
  const charLimit = config.toolOutputLimit * 4;
  if (output.length > charLimit) {
    return (
      output.substring(0, charLimit) +
      `\n... (Output truncated. Total length: ${output.length} chars.)`
    );
  }
  return output;
}

/**
 * Asks for user approval.
 * @param {import("readline").Interface} rl - The readline interface.
 * @param {string} question - The question to ask.
 * @returns {Promise<boolean>} True if approved.
 */
export function askApproval(rl, question) {
  return new Promise((resolve) => {
    rl.question(`${question} (y/n): `, (answer) => {
      resolve(answer.toLowerCase() === "y");
    });
  });
}
