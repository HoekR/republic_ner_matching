#!/usr/bin/env bash
# Fast inventory via sibling llm-archivist (no Ollama).
set -euo pipefail
REPO_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
ARCHIVIST_ROOT="${LLM_ARCHIVIST_ROOT:-$REPO_ROOT/../llm-archivist}"
INBOX="${1:-/Volumes/Extreme SSD/scratch/_inbox}"

if [[ ! -d "$ARCHIVIST_ROOT" ]]; then
  echo "Error: llm-archivist not found at $ARCHIVIST_ROOT" >&2
  exit 1
fi

mkdir -p "$INBOX"
(cd "$ARCHIVIST_ROOT" && uv run archive-inventory "$INBOX" "${@:2}")
