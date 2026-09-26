#!/usr/bin/env bash
# Document orphan files via sibling llm-archivist (Ollama required).
set -euo pipefail
REPO_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
ARCHIVIST_ROOT="${LLM_ARCHIVIST_ROOT:-$REPO_ROOT/../llm-archivist}"
INBOX="${1:-/Volumes/Extreme SSD/scratch/_inbox}"
MODEL="${2:-qwen2.5-coder:latest}"

if [[ ! -d "$ARCHIVIST_ROOT" ]]; then
  echo "Error: llm-archivist not found at $ARCHIVIST_ROOT" >&2
  exit 1
fi

mkdir -p "$INBOX"
(cd "$ARCHIVIST_ROOT" && uv run archive-scan "$INBOX" --model "$MODEL")
