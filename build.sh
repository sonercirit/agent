#!/bin/bash
set -e

cd "$(dirname "$0")"

echo "Building binary..."

uv run pyinstaller \
    --clean \
    --noconfirm \
    --onefile \
    --name agent \
    --hidden-import=uvloop \
    --collect-all=prompt_toolkit \
    --log-level=WARN \
    launcher.py

echo "Done. Binary is at dist/agent"
