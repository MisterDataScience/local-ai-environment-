#!/bin/zsh
set -e
export OLLAMA_HOST=127.0.0.1:11434
export OLLAMA_MAX_LOADED_MODELS=1
export OLLAMA_NUM_PARALLEL=1
export OLLAMA_CONTEXT_LENGTH=8192
export OLLAMA_KEEP_ALIVE=5m
exec /Applications/Ollama.app/Contents/Resources/ollama serve
