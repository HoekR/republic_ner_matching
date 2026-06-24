#!/usr/bin/env bash
# Fast inventory of orphan files (no Ollama). LLM enrichment: archive_inbox.sh
set -euo pipefail
INBOX="${1:-/Volumes/Extreme SSD/scratch/_inbox}"
uv run archive-inventory "$INBOX" "${@:2}"
