#!/usr/bin/env bash
set -euo pipefail

ROOT=$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)
ENV_FILE=${DEEPSEEK_ENV:-$ROOT/.env}
ACTION=${1:-}
COMPOSE=(docker compose --env-file "$ENV_FILE" -f "$ROOT/docker-compose.yml" -f "$ROOT/docker-compose.thinking-on.yml")

require_env() {
  [[ -f "$ENV_FILE" ]] || { echo "Missing $ENV_FILE; copy .env.example and set local fabric values" >&2; exit 2; }
}

render_and_verify() {
  local rendered
  rendered=$(mktemp)
  trap 'rm -f "$rendered"' RETURN
  "${COMPOSE[@]}" config --format json >"$rendered"
  python3 "$ROOT/scripts/verify_thinking.py" compose "$rendered"
}

case "$ACTION" in
  prepare)
    require_env
    render_and_verify
    ;;
  start)
    require_env
    [[ ${DEEPSEEK_ALLOW_LIVE:-0} == 1 ]] || { echo "Set DEEPSEEK_ALLOW_LIVE=1 after reviewing the exact host role" >&2; exit 2; }
    render_and_verify
    "${COMPOSE[@]}" up -d vllm-dspark
    ;;
  status)
    require_env
    "${COMPOSE[@]}" ps vllm-dspark
    curl -fsS http://127.0.0.1:8890/health
    ;;
  accept)
    require_env
    render_and_verify
    curl -fsS http://127.0.0.1:8890/health
    curl -fsS http://127.0.0.1:8890/v1/models
    ;;
  stop)
    require_env
    [[ ${DEEPSEEK_ALLOW_LIVE:-0} == 1 ]] || { echo "Set DEEPSEEK_ALLOW_LIVE=1 and stop head before worker" >&2; exit 2; }
    "${COMPOSE[@]}" stop vllm-dspark
    ;;
  *)
    echo "usage: lifecycle.sh {prepare|start|status|accept|stop}" >&2
    exit 2
    ;;
esac
