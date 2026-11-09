#!/bin/bash
set -e
source_folder="$(cd "$(dirname "$0")" && pwd)"
exec "$HOME/LocalAI-Automated/control/.venv/bin/python" "$source_folder/diagnose_captain.py" --root "$HOME/LocalAI-Automated"
