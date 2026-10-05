#!/bin/zsh
set -e
cd "$(dirname "$0")"
export PATH="/opt/homebrew/bin:$PATH"
exec .venv/bin/python gateway.py
