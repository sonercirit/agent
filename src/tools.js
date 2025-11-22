/**
 * Tools available to the agent.
 * @module tools
 */

import { exec } from "child_process";
import { promisify } from "util";
import fs from "fs/promises";
import path from "path";
import { limitOutput } from "./utils.js";
import { callGemini } from "./providers/gemini.js";

const execAsync = promisify(exec);

/**
 * Executes a bash command.
 */
async function bash({ command }) {
  try {
    // Added timeout of 30 seconds
    const { stdout, stderr } = await execAsync(command, {
      maxBuffer: 10 * 1024 * 1024,
      timeout: 30000,
    });
    let output = stdout + (stderr ? `\nSTDERR:\n${stderr}` : "");

    if (!output.trim()) {
      return "(Command executed successfully with no output)";
    }
    return limitOutput(output);
  } catch (error) {
    return limitOutput(
      `Error executing command:\n${error.message}\nSTDERR:\n${
        error.stderr || ""
      }`,
      true
    );
  }
}

/**
 * Search for files by name pattern, respecting .gitignore.
 */
async function search_files({ pattern }) {
  if (!pattern) return "Error: 'pattern' is required.";
  return await bash({ command: `fd "${pattern}"` });
}

/**
 * Search for a string in files, respecting .gitignore.
 */
async function search_string({ query }) {
  if (!query) return "Error: 'query' is required.";
  // Explicitly search the current directory to ensure it doesn't wait for stdin
  // -- is used to stop argument parsing, ensuring 'query' isn't interpreted as a flag
  return await bash({ command: `rg -n -- "${query}" .` });
}

/**
 * Reads a file or a specific line range.
 * Enforces a maximum of 500 lines per read.
 */
async function read_file({ path: filePath, start_line, end_line }) {
  if (!filePath) return "Error: 'path' is required.";
  try {
    const content = await fs.readFile(filePath, "utf8");
    const lines = content.split("\n");

    let start = 0;
    let end = lines.length;

    if (start_line !== undefined) {
      start = parseInt(start_line) - 1; // 1-based to 0-based
      if (isNaN(start) || start < 0) start = 0;
    }

    if (end_line !== undefined) {
      end = parseInt(end_line);
      if (isNaN(end)) end = lines.length;
    }

    // Enforce 500 line limit
    const MAX_LINES = 500;

    if (end - start > MAX_LINES) {
      end = start + MAX_LINES;
    }

    if (start >= lines.length) return "";
    if (end > lines.length) end = lines.length;
    if (start < 0) start = 0;

    const selectedLines = lines.slice(start, end);

    return limitOutput(
      `(Total lines: ${lines.length})\n` + selectedLines.join("\n")
    );
  } catch (error) {
    return `Error reading file: ${error.message}`;
  }
}

/**
 * Updates (or creates) a file.
 * Supports full overwrite or partial search-and-replace.
 */
async function update_file({ path: filePath, content, old_content }) {
  if (!filePath || content === undefined)
    return "Error: 'path' and 'content' are required.";

  try {
    if (old_content) {
      // Partial update mode
      let currentFileContent;
      try {
        currentFileContent = await fs.readFile(filePath, "utf8");
      } catch (err) {
        return `Error reading file for partial update: ${err.message}. (File must exist for partial updates)`;
      }

      if (!currentFileContent.includes(old_content)) {
        return "Error: 'old_content' text block not found in file. Please ensure exact match (including whitespace/indentation).";
      }

      const newFileContent = currentFileContent.replace(old_content, content);

      await fs.writeFile(filePath, newFileContent, "utf8");
      return `Successfully updated ${filePath} (partial replace).`;
    } else {
      // Full overwrite mode
      await fs.mkdir(path.dirname(filePath), { recursive: true });
      await fs.writeFile(filePath, content, "utf8");
      return `Successfully updated ${filePath} (full overwrite).`;
    }
  } catch (error) {
    return `Error updating file: ${error.message}`;
  }
}

/**
 * Search the web using Gemini's Grounding feature.
 * This is a special tool that triggers a secondary LLM call with grounding enabled.
 */
async function google_search({ query }) {
  if (!query) return "Error: 'query' is required.";

  try {
    // We create a temporary message history for this search query
    const searchMessages = [{ role: "user", content: query }];

    // We pass a special "dummy" tool that triggers the grounding logic in mapToolsToGemini
    const groundingTool = {
      function: {
        name: "__google_search_trigger__", // Internal signal
        description: "Internal trigger",
        parameters: {},
      },
    };

    const { message } = await callGemini(searchMessages, [groundingTool]);

    let result = message.content;

    // Append grounding metadata if available
    if (
      message.provider_metadata &&
      message.provider_metadata.grounding_metadata
    ) {
      const metadata = message.provider_metadata.grounding_metadata;
      if (
        metadata.searchEntryPoint &&
        metadata.searchEntryPoint.renderedContent
      ) {
        result += `\n\n[Grounding]: ${metadata.searchEntryPoint.renderedContent}`;
      } else if (metadata.groundingChunks) {
        result += `\n\n(Verified with Google Search)`;
      }
    }

    return result;
  } catch (error) {
    return `Error performing Google Search: ${error.message}`;
  }
}

export const tools = [
  {
    type: "function",
    function: {
      name: "google_search",
      description:
        "Perform a web search using Google Search Grounding. Use this to get up-to-date information from the internet.",
      parameters: {
        type: "object",
        properties: {
          query: { type: "string", description: "The search query." },
        },
        required: ["query"],
      },
    },
  },
  {
    type: "function",
    function: {
      name: "bash",
      description:
        "Execute a bash command. Use this for all system operations, file manipulation, and information retrieval.",
      parameters: {
        type: "object",
        properties: {
          command: {
            type: "string",
            description: "The bash command to execute.",
          },
        },
        required: ["command"],
      },
    },
  },
  {
    type: "function",
    function: {
      name: "search_files",
      description: "Search for files by name pattern, respecting .gitignore.",
      parameters: {
        type: "object",
        properties: {
          pattern: {
            type: "string",
            description: "The filename pattern to search for.",
          },
        },
        required: ["pattern"],
      },
    },
  },
  {
    type: "function",
    function: {
      name: "search_string",
      description: "Search for a string in files, respecting .gitignore.",
      parameters: {
        type: "object",
        properties: {
          query: { type: "string", description: "The string to search for." },
        },
        required: ["query"],
      },
    },
  },
  {
    type: "function",
    function: {
      name: "read_file",
      description: "Read the content of a file. Returns up to 100 lines.",
      parameters: {
        type: "object",
        properties: {
          path: { type: "string", description: "The path to the file." },
          start_line: {
            type: "integer",
            description: "Start line number (1-based, inclusive).",
          },
          end_line: {
            type: "integer",
            description: "End line number (1-based, inclusive).",
          },
        },
        required: ["path"],
      },
    },
  },
  {
    type: "function",
    function: {
      name: "update_file",
      description:
        "Update a file. You can overwrite the entire file or perform a partial find-and-replace.",
      parameters: {
        type: "object",
        properties: {
          path: { type: "string", description: "The path to the file." },
          content: {
            type: "string",
            description: "The new content to write or to substitute.",
          },
          old_content: {
            type: "string",
            description:
              "Optional. If provided, this specific text block will be replaced by 'content' in the file. If omitted, the entire file is overwritten.",
          },
        },
        required: ["path", "content"],
      },
    },
  },
];

export const toolImplementations = {
  google_search,
  bash,
  search_files,
  search_string,
  read_file,
  update_file,
};
