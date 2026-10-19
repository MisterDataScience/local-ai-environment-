#!/bin/bash
set -euo pipefail
cd "$(dirname "$0")"
if [ "$(uname -s)" != Darwin ] || [ "$(uname -m)" != arm64 ]; then
  echo "This installer requires a native Apple Silicon Mac. Intel/Rosetta is not supported."
  exit 1
fi
AI_INSTALL_ROOT="$HOME/LocalAI-Automated"
mkdir -p "$AI_INSTALL_ROOT/tools/uv" "$AI_INSTALL_ROOT/logs"
UV_VERSION="0.12.20"
UV_ARCHIVE_SHA256="848fdeb602ff1a1baacd4f6c8b7bdc6cf1ad026a6d9cf59475fda17c179743ca"
UV_ARCHIVE="$AI_INSTALL_ROOT/tools/uv/uv-aarch64-apple-darwin-$UV_VERSION.tar.gz"
UV_BINARY="$AI_INSTALL_ROOT/tools/uv/uv"

# A signed-off, immutable release asset replaces the upstream installer script.
# Never execute an unverified download or accept a floating bootstrap URL.
if [ -L "$UV_ARCHIVE" ] || [ -L "$UV_BINARY" ] || [ -L "$UV_ARCHIVE.part" ] || [ -L "$UV_BINARY.verified" ]; then
  echo "Refusing a symbolic-link bootstrap target."
  exit 1
fi
if [ ! -x "$UV_BINARY" ] || [ "$("$UV_BINARY" --version 2>/dev/null | awk '{print $1 " " $2}')" != "uv $UV_VERSION" ]; then
  echo "Installing verified uv $UV_VERSION for native Apple Silicon..."
  if [ -f "$UV_ARCHIVE" ] && [ "$(shasum -a 256 "$UV_ARCHIVE" | awk '{print $1}')" != "$UV_ARCHIVE_SHA256" ]; then
    mv "$UV_ARCHIVE" "$UV_ARCHIVE.invalid-$$"
  fi
  if [ ! -f "$UV_ARCHIVE" ]; then
    /usr/bin/curl -fL --proto '=https' --proto-redir '=https' --retry 3 --connect-timeout 30 \
      -o "$UV_ARCHIVE.part" "https://github.com/astral-sh/uv/releases/download/$UV_VERSION/uv-aarch64-apple-darwin.tar.gz"
    if [ "$(shasum -a 256 "$UV_ARCHIVE.part" | awk '{print $1}')" != "$UV_ARCHIVE_SHA256" ]; then
      mv "$UV_ARCHIVE.part" "$UV_ARCHIVE.invalid-$$"
      echo "The downloaded uv archive did not match the pinned SHA-256. Installation stopped."
      exit 1
    fi
    mv "$UV_ARCHIVE.part" "$UV_ARCHIVE"
  fi
  # Read ONLY the exact release binary entry from the verified archive.
  # Do not unpack archive paths, symlinks, or other untrusted contents.
  /usr/bin/tar -xOzf "$UV_ARCHIVE" "uv-aarch64-apple-darwin/uv" > "$UV_BINARY.verified"
  chmod 700 "$UV_BINARY.verified"
  if [ "$("$UV_BINARY.verified" --version 2>/dev/null | awk '{print $1 " " $2}')" != "uv $UV_VERSION" ]; then
    echo "Verified uv binary reported an unexpected version. Installation stopped."
    exit 1
  fi
  mv -f "$UV_BINARY.verified" "$UV_BINARY"
fi
# Package environments use complete hashed release locks. Keep the release
# cutoff as an additional guard for any bootstrap resolver invocation.
export UV_EXCLUDE_NEWER="2026-10-16T11:00:00Z"
echo "Starting Captain installation with verified dependency locks. Leave this Terminal open."
"$AI_INSTALL_ROOT/tools/uv/uv" run --python 3.11 --no-project \
  installer.py --root "$AI_INSTALL_ROOT" --uv "$AI_INSTALL_ROOT/tools/uv/uv" --minicpm-captain "$@"
