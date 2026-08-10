#!/usr/bin/env bash
set -euo pipefail

if [ "$#" -ne 2 ]; then
  echo "Usage: $0 COMMON_ENV NODE_ENV" >&2
  exit 1
fi

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
docker compose \
  --env-file "$1" \
  --env-file "$2" \
  -f "$SCRIPT_DIR/docker-compose.yml" \
  config
