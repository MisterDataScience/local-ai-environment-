#!/bin/bash
set -euo pipefail
cd "$(dirname "$0")"
if [ "$(uname -s)" != Darwin ] || [ "$(uname -m)" != arm64 ]; then
  echo "This installer requires a native Apple Silicon Mac. Intel/Rosetta is not supported."
  exit 1
fi
AI_INSTALL_ROOT="$HOME/LocalAI-Automated"
mkdir -p "$AI_INSTALL_ROOT/tools/uv" "$AI_INSTALL_ROOT/logs"
if [ ! -x "$AI_INSTALL_ROOT/tools/uv/uv" ]; then
  echo "Installing the private Python/package manager..."
  /usr/bin/curl -fL --retry 3 --connect-timeout 30 \
    -o "$AI_INSTALL_ROOT/tools/uv-install.sh" https://astral.sh/uv/install.sh
  UV_INSTALL_DIR="$AI_INSTALL_ROOT/tools/uv" UV_NO_MODIFY_PATH=1 \
    /bin/sh "$AI_INSTALL_ROOT/tools/uv-install.sh"
fi
echo "Starting installation. Leave this Terminal open."
"$AI_INSTALL_ROOT/tools/uv/uv" run --python 3.11 --no-project \
  installer.py --root "$AI_INSTALL_ROOT" --uv "$AI_INSTALL_ROOT/tools/uv/uv"
