#!/usr/bin/env bash
set -euo pipefail

RECIPE_DIR=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
ROOT=$RECIPE_DIR
while [[ ! -x "$ROOT/lab" && "$ROOT" != "/" ]]; do
  ROOT=$(dirname "$ROOT")
done
[[ -x "$ROOT/lab" ]] || { echo "Repository lab command not found" >&2; exit 2; }
RECIPE_ID=$(python3 -c 'import json,sys; print(json.load(open(sys.argv[1]))["id"])' "$RECIPE_DIR/recipe.yaml")
if [[ $# -eq 0 || "${1:-}" == "--help" ]]; then
  echo "supported: none"
  echo "unsupported operations return non-zero; this is an Archived control profile"
  exit 0
fi
exec "$ROOT/lab" run "$RECIPE_ID" "$@"
