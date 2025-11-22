/**
 * Configuration for the agent.
 * @module config
 */

import dotenv from "dotenv";
import yargs from "yargs";
import { hideBin } from "yargs/helpers";

dotenv.config();

const argv = yargs(hideBin(process.argv))
  .option("mode", {
    alias: "m",
    describe: "Operation mode",
    choices: ["auto", "manual"],
    default: "manual",
  })
  .option("model", {
    describe: "Model to use",
    default: "google/gemini-3-pro-preview", // Defaulting to a valid one, but user asked for Gemini 3 Pro
  })
  .option("provider", {
    describe: "LLM Provider",
    choices: ["openrouter", "gemini"],
    default: "openrouter",
  })
  .help()
  .parse();

/**
 * @typedef {Object} Config
 * @property {string} apiKey - OpenRouter API Key.
 * @property {string} geminiApiKey - Gemini API Key.
 * @property {string} model - Model identifier.
 * @property {string} provider - 'openrouter' or 'gemini'.
 * @property {string} mode - 'auto' or 'manual'.
 * @property {number} contextLimit - Context window limit in tokens.
 * @property {number} toolOutputLimit - Tool output limit in tokens (approx).
 */

/** @type {Config} */
export const config = {
  apiKey: process.env.OPENROUTER_API_KEY,
  geminiApiKey: process.env.GEMINI_API_KEY,
  model:
    argv.model === "google/gemini-3-pro-preview" && process.env.DEFAULT_MODEL
      ? process.env.DEFAULT_MODEL
      : argv.model,
  provider: argv.provider,
  mode: argv.mode,
  contextLimit: 50000,
  toolOutputLimit: 1000, // Approx 4000 chars
};
