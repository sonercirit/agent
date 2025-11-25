#!/bin/bash

# Change to the script's directory so it can run from anywhere
cd "$(dirname "$0")"

# Ensure uv is installed or use it if available
if ! command -v uv &> /dev/null; then
    echo "uv is not installed. Please install it: curl -LsSf https://astral.sh/uv/install.sh | sh"
    exit 1
fi

uv run python -m src.agent "$@"
