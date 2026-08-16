#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)
# shellcheck source=common.sh
source "${SCRIPT_DIR}/common.sh"

if docker container inspect "${CONTAINER_NAME}" >/dev/null 2>&1; then
  mkdir -p "${STATE_ROOT}/logs"
  docker logs "${CONTAINER_NAME}" >"${STATE_ROOT}/logs/${CONTAINER_NAME}-last.log" 2>&1 || true
  docker rm -f "${CONTAINER_NAME}"
fi

if ss -H -ltn "sport = :${PORT}" | grep -q .; then
  echo "Port ${PORT} remains occupied after stop" >&2
  exit 1
fi
