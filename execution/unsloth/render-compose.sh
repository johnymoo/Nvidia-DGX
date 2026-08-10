#!/usr/bin/env bash
set -euo pipefail

if [ "$#" -lt 2 ] || [ "$#" -gt 3 ]; then
  echo "Usage: $0 COMMON_ENV NODE_ENV [target|dspark]" >&2
  exit 1
fi

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
MODE="${3:-target}"

case "$MODE" in
  target|dspark) ;;
  *)
    echo "Mode must be target or dspark, got: $MODE" >&2
    exit 1
    ;;
esac

docker compose \
  --env-file "$1" \
  --env-file "$2" \
  -f "$SCRIPT_DIR/docker-compose.yml" \
  --profile "$MODE" \
  config
