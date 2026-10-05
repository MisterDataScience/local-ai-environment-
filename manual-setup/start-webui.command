#!/bin/zsh
set -e
cd "$HOME/LocalAI/webui"
export DATA_DIR="$HOME/LocalAI/webui/data"
export ENABLE_OLLAMA_API=false
export ENABLE_OPENAI_API=true
export HF_HUB_DISABLE_TELEMETRY=1
export DO_NOT_TRACK=true
export CUDA_VISIBLE_DEVICES=""
export PYTORCH_ENABLE_MPS_FALLBACK=1
exec .venv/bin/open-webui serve --host 127.0.0.1 --port 8080
