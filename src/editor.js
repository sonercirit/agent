import readline from "readline";
import { saveClipboardImage } from "./tools.js";
import { spawn } from "child_process";
import fs from "fs";
import os from "os";
import path from "path";

export function readMultilineInput() {
  return new Promise((resolve) => {
    const { stdin, stdout } = process;
    let lines = [""];
    let cursor = { x: 0, y: 0 };

    // Track visual height to know how much to move up
    let prevVisualCursorY = 0;

    const getVisualPosition = (lines, cx, cy, width) => {
      let vy = 0;
      let vx = 0;
      for (let i = 0; i < lines.length; i++) {
        const line = lines[i];
        const lineRows = line.length > 0 ? Math.ceil(line.length / width) : 1;

        if (i === cy) {
          const cursorRowInLine = cx === 0 ? 0 : Math.floor((cx - 1) / width);
          vy += cursorRowInLine;
          vx = cx % width;
          if (cx > 0 && vx === 0) vx = width;
          break;
        }
        vy += lineRows;
      }
      return { x: vx, y: vy };
    };

    const render = () => {
      const width = stdout.columns || 80;

      // Move to start of input
      readline.moveCursor(stdout, 0, -prevVisualCursorY);
      readline.cursorTo(stdout, 0);
      readline.clearScreenDown(stdout);

      // Print all lines
      const content = lines.join("\n");
      stdout.write(content);

      // Calculate new cursor position
      const visualPos = getVisualPosition(lines, cursor.x, cursor.y, width);
      prevVisualCursorY = visualPos.y;

      // Move cursor to correct position
      // We are currently at the end of the content.
      // We need to calculate the visual height of the whole content to know where we are.

      let totalRows = 0;
      for (let line of lines) {
        totalRows += line.length > 0 ? Math.ceil(line.length / width) : 1;
      }

      // If the last character is at the exact end of the width, does it wrap?
      // It depends on the terminal. Usually it doesn't wrap until next char is printed.
      // But let's assume standard behavior.

      // Move up to the first line
      // If totalRows is 1, we move up 0.
      if (totalRows > 1) {
        readline.moveCursor(stdout, 0, -(totalRows - 1));
      }
      readline.cursorTo(stdout, 0);

      // Now we are at (0,0) of the input block.
      // Move to visualPos
      if (visualPos.y > 0) {
        readline.moveCursor(stdout, 0, visualPos.y);
      }
      readline.cursorTo(stdout, visualPos.x);
    };

    const onKey = async (str, key) => {
      if (!key) return;

      if (key.ctrl && key.name === "e") {
        // Open external editor
        const tmpDir = os.tmpdir();
        const tmpFile = path.join(tmpDir, `agent_input_${Date.now()}.txt`);
        fs.writeFileSync(tmpFile, lines.join("\n"));

        process.stdin.removeListener("keypress", onKey);
        process.stdin.setRawMode(false);
        process.stdin.pause();

        const editor = process.env.EDITOR || "vim";
        const child = spawn(editor, [tmpFile], {
          stdio: "inherit",
        });

        child.on("exit", () => {
          process.stdin.setRawMode(true);
          process.stdin.resume();
          process.stdin.on("keypress", onKey);

          if (fs.existsSync(tmpFile)) {
            const content = fs.readFileSync(tmpFile, "utf8");
            // Remove trailing newline if added by editor
            let newContent = content;
            if (newContent.endsWith("\n") && !lines.join("\n").endsWith("\n")) {
              newContent = newContent.slice(0, -1);
            }
            lines = newContent.split("\n");

            // Reset cursor to end
            cursor.y = Math.max(0, lines.length - 1);
            cursor.x = lines[cursor.y].length;

            fs.unlinkSync(tmpFile);
            render();
          }
        });
        return;
      }

      if (key.ctrl && key.name === "v") {
        const imagePath = await saveClipboardImage();
        if (imagePath) {
          const line = lines[cursor.y];
          lines[cursor.y] =
            line.slice(0, cursor.x) + imagePath + line.slice(cursor.x);
          cursor.x += imagePath.length;
          render();
        }
        return;
      }

      if (key.ctrl && key.name === "s") {
        cleanup();
        resolve(lines.join("\n"));
        return;
      }

      if (key.ctrl && key.name === "c") {
        cleanup();
        process.exit(0);
      }

      if (key.name === "return") {
        const currentLine = lines[cursor.y];
        const before = currentLine.slice(0, cursor.x);
        const after = currentLine.slice(cursor.x);
        lines[cursor.y] = before;
        lines.splice(cursor.y + 1, 0, after);
        cursor.y++;
        cursor.x = 0;
      } else if (key.name === "backspace") {
        if (cursor.x > 0) {
          const line = lines[cursor.y];
          lines[cursor.y] = line.slice(0, cursor.x - 1) + line.slice(cursor.x);
          cursor.x--;
        } else if (cursor.y > 0) {
          const curr = lines[cursor.y];
          const prev = lines[cursor.y - 1];
          cursor.x = prev.length;
          lines[cursor.y - 1] = prev + curr;
          lines.splice(cursor.y, 1);
          cursor.y--;
        }
      } else if (key.name === "up") {
        if (cursor.y > 0) {
          cursor.y--;
          cursor.x = Math.min(cursor.x, lines[cursor.y].length);
        }
      } else if (key.name === "down") {
        if (cursor.y < lines.length - 1) {
          cursor.y++;
          cursor.x = Math.min(cursor.x, lines[cursor.y].length);
        }
      } else if (key.name === "left") {
        if (cursor.x > 0) {
          cursor.x--;
        } else if (cursor.y > 0) {
          cursor.y--;
          cursor.x = lines[cursor.y].length;
        }
      } else if (key.name === "right") {
        if (cursor.x < lines[cursor.y].length) {
          cursor.x++;
        } else if (cursor.y < lines.length - 1) {
          cursor.y++;
          cursor.x = 0;
        }
      } else {
        // Regular character
        const line = lines[cursor.y];
        lines[cursor.y] = line.slice(0, cursor.x) + str + line.slice(cursor.x);
        cursor.x += str.length;
      }

      render();
    };

    const cleanup = () => {
      process.stdin.removeListener("keypress", onKey);
      if (process.stdin.isTTY) {
        process.stdin.setRawMode(false);
      }
      // Move cursor to end of output
      readline.moveCursor(stdout, 0, 1);
    };

    // Initial render
    render();

    // Setup key listener
    readline.emitKeypressEvents(process.stdin);
    if (process.stdin.isTTY) {
      process.stdin.setRawMode(true);
    }
    process.stdin.on("keypress", onKey);
  });
}
