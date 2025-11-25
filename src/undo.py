"""Undo manager with Git and manual file tracking support."""

import os
import copy
import subprocess
import logging

logger = logging.getLogger(__name__)


class UndoManager:
    """Manages undo history using Git snapshots or manual file tracking."""

    def __init__(self):
        self.history = []
        self.git_available = self._check_git()

    def _check_git(self) -> bool:
        """Check if we're inside a git repository."""
        try:
            subprocess.run(["git", "rev-parse", "--is-inside-work-tree"], check=True, capture_output=True)
            return True
        except (subprocess.CalledProcessError, FileNotFoundError):
            return False

    def _git_snapshot(self) -> str | None:
        """Create a git tree snapshot. Returns tree hash or None."""
        try:
            subprocess.run(["git", "add", "-A"], check=True, capture_output=True)
            result = subprocess.run(["git", "write-tree"], check=True, capture_output=True, text=True)
            tree_hash = result.stdout.strip()
            subprocess.run(["git", "reset"], check=True, capture_output=True)
            return tree_hash
        except Exception as e:
            logger.error(f"Git snapshot failed: {e}")
            return None

    def _git_restore(self, tree_hash: str) -> bool:
        """Restore working directory from a git tree hash."""
        try:
            subprocess.run(["git", "checkout", tree_hash, "--", "."], check=True, capture_output=True)
            subprocess.run(["git", "clean", "-fd"], check=True, capture_output=True)
            subprocess.run(["git", "reset"], check=True, capture_output=True)
            return True
        except Exception as e:
            logger.error(f"Git restore failed: {e}")
            return False

    def start_turn(self, messages: list):
        """Snapshot state at the start of a turn."""
        snapshot = {"messages": copy.deepcopy(messages), "type": "manual", "data": {}}

        if self.git_available:
            tree_hash = self._git_snapshot()
            if tree_hash:
                snapshot["type"] = "git"
                snapshot["data"] = tree_hash

        self.history.append(snapshot)

    def record_file_change(self, path: str):
        """Record file state before modification (for manual tracking)."""
        if not self.history or self.history[-1]["type"] == "git":
            return

        path = os.path.abspath(path)
        changes = self.history[-1]["data"]

        if path not in changes:
            try:
                changes[path] = open(path, "r", encoding="utf-8").read() if os.path.exists(path) else None
            except Exception:
                pass

    def undo(self) -> list | None:
        """Undo the last turn. Returns restored messages or None."""
        if not self.history:
            return None

        state = self.history.pop()

        if state["type"] == "git":
            if not self._git_restore(state["data"]):
                print("Error: Git undo failed. State might be inconsistent.")
        else:
            # Manual file restore
            for path, content in state["data"].items():
                try:
                    if content is None:
                        if os.path.exists(path):
                            os.remove(path)
                    else:
                        os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
                        with open(path, "w", encoding="utf-8") as f:
                            f.write(content)
                except Exception as e:
                    print(f"Error reverting file {path}: {e}")

        return state["messages"]
