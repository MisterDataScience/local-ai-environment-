#!/bin/bash
set -e
HERE="$(cd "$(dirname "$0")" && pwd)"
ROOT="${LOCAL_AI_ROOT:-$HOME/LocalAI-Automated}"
if [ ! -x "$ROOT/control/.venv/bin/python" ]; then
  echo "Captain installation is incomplete at: $ROOT"
  echo 'Run Install LOCAL AI Core.command from this extracted folder first.'
  exit 1
fi
export PYTHONPATH="$HERE/payload:$ROOT/control"
exec "$ROOT/control/.venv/bin/python" "$HERE/turnkey_install.py" --root "$ROOT"
