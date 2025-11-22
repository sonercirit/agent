#!/usr/bin/env node

/**
 * Entry point for the agent.
 * @module index
 */

import { startAgent } from "./agent.js";

startAgent().catch((err) => {
  console.error("Fatal error:", err);
  process.exit(1);
});
