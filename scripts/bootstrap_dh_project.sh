#!/usr/bin/env bash
# Bootstrap a new DH project from template/dh_project + live data_io + llm_archivist.
#
# Usage:
#   ./scripts/bootstrap_dh_project.sh /path/to/NewProject [python-package-name]
#
# Environment:
#   LLM_ARCHIVIST_SRC  Path to llm_archivist package (default: ../llm-archivist/src/llm_archivist)
#
# Example:
#   ./scripts/bootstrap_dh_project.sh ~/develop/GNBanalysis gnb-analysis

set -euo pipefail

REPO_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
TARGET="${1:?Usage: bootstrap_dh_project.sh <target_dir> [package_name]}"
PKG_NAME="${2:-$(basename "$TARGET" | tr '[:upper:]' '[:lower:]' | tr ' _' '-')}"
LLM_ARCHIVIST_SRC="${LLM_ARCHIVIST_SRC:-$REPO_ROOT/../llm-archivist/src/llm_archivist}"

if [[ -e "$TARGET" && "$(ls -A "$TARGET" 2>/dev/null)" ]]; then
  echo "Error: target directory exists and is not empty: $TARGET" >&2
  exit 1
fi

if [[ ! -d "$LLM_ARCHIVIST_SRC" ]]; then
  echo "Error: llm_archivist not found at $LLM_ARCHIVIST_SRC" >&2
  echo "Set LLM_ARCHIVIST_SRC to the package directory." >&2
  exit 1
fi

mkdir -p "$TARGET/tests" "$TARGET/scripts" "$TARGET/docs"

echo "Copying template → $TARGET"
rsync -a "$REPO_ROOT/template/dh_project/" "$TARGET/"

echo "Copying data_io package"
rsync -a "$REPO_ROOT/data_io/" "$TARGET/data_io/"

echo "Copying llm_archivist package from $LLM_ARCHIVIST_SRC"
rsync -a "$LLM_ARCHIVIST_SRC/" "$TARGET/llm_archivist/"

echo "Copying tests"
cp "$REPO_ROOT/tests/test_data_io.py" "$TARGET/tests/"
if [[ -f "$REPO_ROOT/../llm-archivist/tests/test_scanners.py" ]]; then
  cp "$REPO_ROOT/../llm-archivist/tests/test_scanners.py" "$TARGET/tests/test_llm_archivist.py"
fi
if [[ -f "$REPO_ROOT/../llm-archivist/tests/test_inventory.py" ]]; then
  cp "$REPO_ROOT/../llm-archivist/tests/test_inventory.py" "$TARGET/tests/test_inventory.py"
fi

cp "$TARGET/data_manifest.toml.example" "$TARGET/data_manifest.toml"

if [[ "$(uname)" == "Darwin" ]]; then
  sed -i '' "s/PROJECT_NAME/$PKG_NAME/g" "$TARGET/pyproject.toml"
else
  sed -i "s/PROJECT_NAME/$PKG_NAME/g" "$TARGET/pyproject.toml"
fi

chmod +x "$TARGET/scripts"/*.sh 2>/dev/null || true

cat <<EOF

Created: $TARGET

Next steps:
  cd $TARGET
  uv sync
  # Edit data_manifest.toml (tier roots + datasets)
  uv run python -m data_io.check

Document legacy/orphan files:
  uv run archive-inventory /path/to/scratch/_inbox     # fast, no Ollama
  uv run archive-scan /path/to/folder --model ...      # LLM enrichment (Ollama)

For LLM coding: open AGENTS.md and .cursorrules in the new repo.

EOF
