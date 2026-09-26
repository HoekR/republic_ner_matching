#!/usr/bin/env bash
# Deprecated: forwards to dighum_template.
#
# Usage:
#   ./scripts/bootstrap_dh_project.sh /path/to/NewProject [python-package-name]

set -euo pipefail

REPO_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
DIGHUM_TEMPLATE="${DIGHUM_TEMPLATE:-$REPO_ROOT/../dighum_template}"
BOOTSTRAP="$DIGHUM_TEMPLATE/scripts/bootstrap.sh"

if [[ ! -x "$BOOTSTRAP" ]]; then
  echo "Error: dighum_template bootstrap not found at $BOOTSTRAP" >&2
  echo "Clone dighum_template as a sibling repo or set DIGHUM_TEMPLATE." >&2
  exit 1
fi

echo "Note: bootstrap moved to dighum_template — forwarding to $BOOTSTRAP" >&2
exec "$BOOTSTRAP" "$@"
