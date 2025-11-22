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
import { config } from "./config.js";

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
      true,
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
  return await bash({ command: `rg -n -C 5 -- "${query}" .` });
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
      `(Total lines: ${lines.length})\n` + selectedLines.join("\n"),
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
 * Search the web using Google Search Grounding.
 * Use this to get up-to-date information from the internet.
 */
async function google_search({ query }) {
  // This is a placeholder. The actual implementation is handled by the
  // "googleSearch" tool declaration in the Gemini API request itself.
  // However, since we are using the "Sub-agent" pattern where the agent calls this tool,
  // and then we trigger a NEW Gemini request with grounding enabled,
  // we need to implement that logic here or in the agent loop.

  // Actually, looking at the agent loop, it just calls the tool implementation.
  // So we need to perform the "grounded request" here.

  if (!query) return "Error: 'query' is required.";

  try {
    // We create a temporary message history for the search
    const searchMessages = [{ role: "user", content: query }];

    // We call Gemini with the special "googleSearch" tool enabled
    // We need to bypass the standard tool map and force the googleSearch tool.
    // Since we can't easily change the `callGemini` signature, we might need to
    // rely on the `mapToolsToGemini` logic which checks for a special trigger.
    // But `mapToolsToGemini` checks the *input* tools.

    // Let's look at `mapToolsToGemini` in `src/providers/gemini.js` again.
    // It checks: `tools.some(t => t.function && t.function.name === "__google_search_trigger__")`

    // So if we pass this special tool, it will enable grounding.
    const specialTool = [
      {
        type: "function",
        function: {
          name: "__google_search_trigger__",
          description: "Trigger Google Search Grounding",
          parameters: { type: "object", properties: {} },
        },
      },
    ];

    const { message } = await callGemini(searchMessages, specialTool);

    return message.content || "No results found.";
  } catch (error) {
    return `Error performing Google Search: ${error.message}`;
  }
}

/**
 * Describes an image using Gemini 3 Pro Preview.
 */
async function describe_image({ path: imagePath }) {
  if (!imagePath) return "Error: 'path' is required.";

  let tempFilePath = null;

  try {
    if (imagePath === "clipboard") {
      tempFilePath = path.join("/tmp", `clipboard_${Date.now()}.png`);
      try {
        // Try wl-paste first (Wayland)
        await execAsync(`wl-paste -t image/png > "${tempFilePath}"`);
      } catch (err) {
        try {
          // Try xclip (X11)
          await execAsync(
            `xclip -selection clipboard -t image/png -o > "${tempFilePath}"`,
          );
        } catch (err2) {
          // Try pngpaste (MacOS)
          try {
            await execAsync(`pngpaste "${tempFilePath}"`);
          } catch (err3) {
            return `Error reading from clipboard: Could not find wl-paste, xclip, or pngpaste, or failed to get image.`;
          }
        }
      }
      imagePath = tempFilePath;
    }

    const imageBuffer = await fs.readFile(imagePath);
    const base64Image = imageBuffer.toString("base64");
    const ext = path.extname(imagePath).toLowerCase();

    let mimeType = "image/jpeg";
    if (ext === ".png") mimeType = "image/png";
    if (ext === ".webp") mimeType = "image/webp";
    if (ext === ".heic") mimeType = "image/heic";
    if (ext === ".heif") mimeType = "image/heif";

    const apiKey = config.geminiApiKey;
    if (!apiKey) return "Error: GEMINI_API_KEY is not set.";

    const model = "gemini-3-pro-preview";
    const url = `https://generativelanguage.googleapis.com/v1beta/models/${model}:generateContent?key=${apiKey}`;

    const payload = {
      contents: [
        {
          parts: [
            {
              text: "Describe this image in detail. Identify objects, colors, text, and the overall scene.",
            },
            {
              inline_data: {
                mime_type: mimeType,
                data: base64Image,
              },
            },
          ],
        },
      ],
    };

    const response = await fetch(url, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    });

    if (tempFilePath) {
      await fs.unlink(tempFilePath).catch(() => {});
    }

    if (!response.ok) {
      const text = await response.text();
      return `Error from Gemini API: ${response.status} - ${text}`;
    }

    const data = await response.json();
    const text = data.candidates?.[0]?.content?.parts?.[0]?.text;

    if (!text) return "Error: No description returned from API.";

    return text;
  } catch (error) {
    if (tempFilePath) {
      await fs.unlink(tempFilePath).catch(() => {});
    }
    return `Error describing image: ${error.message}`;
  }
}

export const tools = [
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
      description:
        "Search for a string in files, respecting .gitignore. Returns 5 lines of context around matches.",
      parameters: {
        type: "object",
        properties: {
          query: {
            type: "string",
            description: "The string to search for.",
          },
        },
        required: ["query"],
      },
    },
  },
  {
    type: "function",
    function: {
      name: "read_file",
      description:
        "Read the content of a file. Returns up to 100 lines.",
      parameters: {
        type: "object",
        properties: {
          path: {
            type: "string",
            description: "The path to the file.",
          },
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
          path: {
            type: "string",
            description: "The path to the file.",
          },
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
  {
    type: "function",
    function: {
      name: "google_search",
      description:
        "Perform a web search using Google Search Grounding. Use this to get up-to-date information from the internet.",
      parameters: {
        type: "object",
        properties: {
          query: {
            type: "string",
            description: "The search query.",
          },
        },
        required: ["query"],
      },
    },
  },
  {
    type: "function",
    function: {
      name: "describe_image",
      description:
        "Describe an image file on disk using Gemini 3 Pro Preview. Returns a detailed text description. Can also read from clipboard by passing 'clipboard' as path.",
      parameters: {
        type: "object",
        properties: {
          path: {
            type: "string",
            description: "The path to the image file, or 'clipboard' to read from system clipboard.",
          },
        },
        required: ["path"],
      },
    },
  },
];

export const toolImplementations = {
  bash,
  search_files,
  search_string,
  read_file,
  update_file,
  google_search,
  describe_image,
};
