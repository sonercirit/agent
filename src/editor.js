import readline from 'readline';

export function readMultilineInput() {
  return new Promise((resolve) => {
    const { stdin, stdout } = process;
    let lines = [''];
    let cursor = { x: 0, y: 0 };
    
    // Track visual height to know how much to move up
    let prevVisualCursorY = 0;

    const getVisualPosition = (lines, cx, cy, width) => {
      let vy = 0;
      let vx = 0;
      for (let i = 0; i < lines.length; i++) {
        const line = lines[i];
        const lineRows = Math.floor(line.length / width) + 1;
        
        if (i === cy) {
          const cursorRowInLine = Math.floor(cx / width);
          vy += cursorRowInLine;
          vx = cx % width;
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
      const content = lines.join('\n');
      stdout.write(content);
      
      // Calculate new cursor position
      const visualPos = getVisualPosition(lines, cursor.x, cursor.y, width);
      prevVisualCursorY = visualPos.y;
      
      // Move cursor to correct position
      // We are currently at the end of the content.
      // We need to calculate the visual height of the whole content to know where we are.
      
      let totalVisualHeight = 0;
      for (const line of lines) {
        totalVisualHeight += Math.floor(line.length / width) + 1;
      }
      // The cursor is at the end of the last line printed.
      // Actually, stdout.write leaves cursor at the end.
      // So we are at (end_x, totalVisualHeight - 1).
      
      // Let's move back to start
      // We need to move up by (totalVisualHeight - 1) ?
      // Wait, if totalVisualHeight is 1, we are on the same line.
      // If we printed 3 lines, we are on the 3rd line (index 2).
      // So we move up by (totalVisualHeight - 1).
      
      // However, if the last line wraps exactly to the end, the cursor might be on the next line?
      // No, usually it stays at the end.
      
      // Let's just move to (0,0) relative to start
      // We know we just printed 'content'.
      // We can calculate the visual height of 'content'.
      
      // Actually, simpler:
      // We are at the end.
      // We want to go to visualPos.
      // We can go to start, then to visualPos.
      
      // To go to start from end:
      // We need to know the visual height of the entire block.
      let totalRows = 0;
      for(let line of lines) {
          totalRows += Math.floor(line.length / width) + 1;
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

    const onKey = (str, key) => {
        if (!key) return;

        if (key.ctrl && key.name === 's') {
            cleanup();
            resolve(lines.join('\n'));
            return;
        }
        
        if (key.ctrl && key.name === 'c') {
            cleanup();
            process.exit(0);
        }

        if (key.name === 'return') {
            const currentLine = lines[cursor.y];
            const before = currentLine.slice(0, cursor.x);
            const after = currentLine.slice(cursor.x);
            lines[cursor.y] = before;
            lines.splice(cursor.y + 1, 0, after);
            cursor.y++;
            cursor.x = 0;
        } else if (key.name === 'backspace') {
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
        } else if (key.name === 'up') {
            if (cursor.y > 0) {
                cursor.y--;
                cursor.x = Math.min(cursor.x, lines[cursor.y].length);
            }
        } else if (key.name === 'down') {
            if (cursor.y < lines.length - 1) {
                cursor.y++;
                cursor.x = Math.min(cursor.x, lines[cursor.y].length);
            }
        } else if (key.name === 'left') {
            if (cursor.x > 0) {
                cursor.x--;
            } else if (cursor.y > 0) {
                cursor.y--;
                cursor.x = lines[cursor.y].length;
            }
        } else if (key.name === 'right') {
            if (cursor.x < lines[cursor.y].length) {
                cursor.x++;
            } else if (cursor.y < lines.length - 1) {
                cursor.y++;
                cursor.x = 0;
            }
        } else {
            if (!key.ctrl && !key.meta) {
                const line = lines[cursor.y];
                const char = str || key.sequence;
                if (char && char.length === 1 && char.charCodeAt(0) >= 32) {
                     lines[cursor.y] = line.slice(0, cursor.x) + char + line.slice(cursor.x);
                     cursor.x += char.length;
                }
            }
        }
        render();
    };

    stdin.on('keypress', onKey);
    
    // Setup raw mode
    readline.emitKeypressEvents(stdin);
    if (stdin.isTTY) stdin.setRawMode(true);
    
    const cleanup = () => {
        stdin.removeListener('keypress', onKey);
        if (stdin.isTTY) stdin.setRawMode(false);
        
        // Move to end of input
        const width = stdout.columns || 80;
        let totalRows = 0;
        for(let line of lines) {
            totalRows += Math.floor(line.length / width) + 1;
        }
        
        // We are currently at cursor position.
        // Move to start
        readline.moveCursor(stdout, 0, -prevVisualCursorY);
        readline.cursorTo(stdout, 0);
        
        // Move to end
        if (totalRows > 1) {
             readline.moveCursor(stdout, 0, totalRows - 1);
        }
        // And print newline
        stdout.write('\n');
    };
  });
}
