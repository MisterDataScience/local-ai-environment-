#!/bin/bash
set -euo pipefail
AI_FEATURE_ROOT="$HOME/LocalAI-Automated"
if [ ! -x "$AI_FEATURE_ROOT/control/.venv/bin/python" ]; then
  echo "Core installation missing. Run Install LOCAL AI Core.command first."
  exit 1
fi
exec "$AI_FEATURE_ROOT/control/.venv/bin/python" "$AI_FEATURE_ROOT/control/feature_install.py" --root "$AI_FEATURE_ROOT" --status
