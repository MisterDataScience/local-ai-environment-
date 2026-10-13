#!/bin/bash
set -euo pipefail
cd "$(dirname "$0")"
exec ./"Install Local AI.command" --minicpm-captain "$@"
