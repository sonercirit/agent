import os
import copy
import subprocess
import logging

logger = logging.getLogger("UndoManager")

class UndoManager:
    def __init__(self):
        self.history = []
        self.git_available = self._check_git()

    def _check_git(self):
        try:
            subprocess.run(["git", "rev-parse", "--is-inside-work-tree"], 
                         check=True, capture_output=True)
            return True
        except subprocess.CalledProcessError:
            return False
        except FileNotFoundError:
            return False

    def _git_snapshot(self):
        try:
            # Stage everything (including untracked)
            subprocess.run(["git", "add", "-A"], check=True, capture_output=True)
            # Write tree
            result = subprocess.run(["git", "write-tree"], check=True, capture_output=True, text=True)
            tree_hash = result.stdout.strip()
            # Unstage everything to leave user state mostly as is (though staged status is lost)
            subprocess.run(["git", "reset"], check=True, capture_output=True)
            return tree_hash
        except Exception as e:
            logger.error(f"Git snapshot failed: {e}")
            return None

    def _git_restore(self, tree_hash):
        try:
            # Checkout the tree (restores content, updates index)
            subprocess.run(["git", "checkout", tree_hash, "--", "."], check=True, capture_output=True)
            # Remove files that weren't in the tree
            subprocess.run(["git", "clean", "-fd"], check=True, capture_output=True)
            # Unstage everything
            subprocess.run(["git", "reset"], check=True, capture_output=True)
            return True
        except Exception as e:
            logger.error(f"Git restore failed: {e}")
            return False

    def start_turn(self, messages):
        snapshot = {
            "messages": copy.deepcopy(messages),
            "type": "manual",
            "data": {}
        }

        if self.git_available:
            tree_hash = self._git_snapshot()
            if tree_hash:
                snapshot["type"] = "git"
                snapshot["data"] = tree_hash
            else:
                # Fallback to manual if git fails
                snapshot["data"] = {}
        
        self.history.append(snapshot)

    def record_file_change(self, path):
        if not self.history:
            return
            
        current_snapshot = self.history[-1]
        
        # If we are using git, we don't need to record individual files
        if current_snapshot["type"] == "git":
            return

        # Manual tracking logic
        changes = current_snapshot["data"]
        path = os.path.abspath(path)
        
        if path not in changes:
            try:
                if os.path.exists(path):
                    with open(path, 'r', encoding='utf-8') as f:
                        content = f.read()
                    changes[path] = content
                else:
                    changes[path] = None
            except Exception:
                pass

    def undo(self):
        if not self.history:
            return None

        last_state = self.history.pop()
        
        if last_state["type"] == "git":
            success = self._git_restore(last_state["data"])
            if not success:
                print("Error: Git undo failed. State might be inconsistent.")
        else:
            # Manual restore
            for path, content in last_state["data"].items():
                try:
                    if content is None:
                        if os.path.exists(path):
                            os.remove(path)
                    else:
                        os.makedirs(os.path.dirname(path), exist_ok=True)
                        with open(path, 'w', encoding='utf-8') as f:
                            f.write(content)
                except Exception as e:
                    print(f"Error reverting file {path}: {e}")
        
        return last_state["messages"]
