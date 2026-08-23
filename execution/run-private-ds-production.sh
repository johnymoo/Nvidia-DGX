#!/usr/bin/env bash
set -Eeuo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

export ACCEPTANCE_COMPOSE_EXTRA_FILE="${SCRIPT_DIR}/docker-compose.thinking-on.yml"
export ACCEPTANCE_EXPECTED_THINKING=true

exec "${SCRIPT_DIR}/run-vllm-service.sh" "$@"
