#!/bin/bash

# Save the current directory as the target working directory
TARGET_DIR="$(pwd)"

# Change to the script's directory so it can run from anywhere
cd "$(dirname "$0")"

# Ensure uv is installed or use it if available
if ! command -v uv &> /dev/null; then
    echo "uv is not installed. Please install it: curl -LsSf https://astral.sh/uv/install.sh | sh"
    exit 1
fi

AGENT_WORK_DIR="$TARGET_DIR" uv run python -m src.agent "$@"
