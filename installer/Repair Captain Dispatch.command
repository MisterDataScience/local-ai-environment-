#!/bin/bash
set -euo pipefail
source_folder="$(cd "$(dirname "$0")" && pwd)"
exec "$HOME/LocalAI-Automated/control/.venv/bin/python" "$source_folder/repair_captain.py" \
  --root "$HOME/LocalAI-Automated" --output "$HOME/Downloads/LOCAL-AI-Diagnostic.json" "$@"
