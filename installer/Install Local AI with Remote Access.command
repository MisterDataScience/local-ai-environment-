#!/bin/bash
set -euo pipefail
cd "$(dirname "$0")"
exec /bin/bash './Install Local AI.command' --remote-access "$@"
