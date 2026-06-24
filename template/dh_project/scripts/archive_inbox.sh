#!/usr/bin/env bash
# Document orphan files in scratch/_inbox with llm_archivist (Ollama required).
set -euo pipefail
INBOX="${1:-/Volumes/Extreme SSD/scratch/_inbox}"
MODEL="${2:-qwen2.5-coder:latest}"
uv run archive-scan "$INBOX" --model "$MODEL"
