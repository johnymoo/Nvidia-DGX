#!/usr/bin/env bash
set -euo pipefail
umask 077

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ENV_FILE="$SCRIPT_DIR/qwen38.env"
COMPOSE_FILE="$SCRIPT_DIR/compose.yml"
MANIFEST_FILE="$SCRIPT_DIR/model-manifest.sha256"
PROJECT="gb10-qwen38-nvfp4"
SERVICE="server"
OUTER_TIMEOUT_SECONDS=1800
READINESS_DEADLINE_SECONDS=1530
CLEANUP_MARGIN_SECONDS=120

set -a
# shellcheck source=/dev/null
source "$ENV_FILE"
set +a

[[ $((READINESS_DEADLINE_SECONDS + CLEANUP_MARGIN_SECONDS)) -lt $OUTER_TIMEOUT_SECONDS ]]

compose() {
  docker compose -p "$PROJECT" --env-file "$ENV_FILE" -f "$COMPOSE_FILE" "$@"
}

verify_model() {
  [[ "$(sha256sum "$MANIFEST_FILE" | awk '{print $1}')" == "$QWEN38_MODEL_MANIFEST_SHA256" ]]
  local expected_files actual_files
  expected_files="$(awk '{print $2}' "$MANIFEST_FILE" | LC_ALL=C sort)"
  actual_files="$(find "$QWEN38_MODEL_DIR" -maxdepth 1 -type f -printf '%f\n' | LC_ALL=C sort)"
  [[ "$actual_files" == "$expected_files" ]]
  (cd "$QWEN38_MODEL_DIR" && sha256sum --quiet -c "$MANIFEST_FILE")
  [[ "$(jq -r .truncation "$QWEN38_MODEL_DIR/tokenizer.json")" == null ]]
  [[ "$(jq -r .model_max_length "$QWEN38_MODEL_DIR/tokenizer_config.json")" == 262144 ]]
  [[ "$(jq -r .vision_config.model_type "$QWEN38_MODEL_DIR/config.json")" == qwen3_5_vision ]]
}

verify_image() {
  local state_file="$QWEN38_STATE_ROOT/runtime-image.json"
  [[ -r "$state_file" ]]
  [[ "$(stat -c %a "$QWEN38_STATE_ROOT")" == 700 ]]
  [[ "$(jq -r .image "$state_file")" == "$QWEN38_VLLM_IMAGE" ]]
  [[ "$(jq -r .recipe_sha256 "$state_file")" == "$QWEN38_BUILD_RECIPE_SHA256" ]]
  local expected_id actual_id
  expected_id="$(jq -r .image_id "$state_file")"
  [[ "$expected_id" == sha256:* ]]
  actual_id="$(docker image inspect "$QWEN38_VLLM_IMAGE" --format '{{.Id}}')"
  [[ "$actual_id" == "$expected_id" ]]
}

check() {
  verify_model
  verify_image
  compose config --quiet
  if [[ -z "$(compose ps --status running -q "$SERVICE")" ]] &&
     ss -H -ltn "sport = :$QWEN38_PORT" | grep -q .; then
    printf 'port %s is already occupied\n' "$QWEN38_PORT" >&2
    return 1
  fi
}

status() {
  local container state health api=false revision run_id=null
  container="$(compose ps -aq "$SERVICE")"
  if [[ -n "$container" ]]; then
    state="$(docker inspect -f '{{.State.Status}}' "$container")"
    health="$(docker inspect -f '{{if .State.Health}}{{.State.Health.Status}}{{else}}none{{end}}' "$container")"
    revision="$(docker inspect -f '{{index .Config.Labels "io.shili.model-platform.revision"}}' "$container")"
  else
    state=absent
    health=none
    revision=""
  fi
  if curl -fsS --max-time 3 "http://127.0.0.1:$QWEN38_PORT/v1/models" |
    jq -e --arg model "$QWEN38_SERVED_MODEL" '.data[] | select(.id == $model)' >/dev/null 2>&1; then
    api=true
  fi
  if [[ -r "$QWEN38_STATE_ROOT/active.json" ]]; then
    run_id="$(jq -r --arg container "$container" 'select(.container == $container) | .run_id // empty' "$QWEN38_STATE_ROOT/active.json")"
    [[ -n "$run_id" ]] || run_id=null
  fi
  local platform_state=stopped
  if [[ "$state" == running && "$health" == healthy && "$api" == true && "$revision" == 16b6615af3548b88e2d8e382457bc705b00479cf ]]; then
    platform_state=running
  elif [[ "$state" == running ]]; then
    platform_state=degraded
  fi
  jq -n --arg project "$PROJECT" --arg container "$container" --arg state "$platform_state" \
    --arg health "$health" --arg model "$QWEN38_SERVED_MODEL" \
    --arg revision "$revision" --arg run_id "$run_id" --argjson api "$api" \
    '{project:$project,container:$container,state:$state,health:$health,model:$model,revision:$revision,run_id:(if $run_id == "null" then null else $run_id end),api_identity:$api}'
}

capture_and_stop_failed_start() {
  local reason="$1" run_id artifact cleanup_ok=true
  trap - HUP INT TERM
  run_id="$(date -u +%Y%m%dT%H%M%SZ)-failed-start"
  artifact="$QWEN38_STATE_ROOT/artifacts/$run_id"
  mkdir -p "$artifact"
  chmod 700 "$QWEN38_STATE_ROOT" "$QWEN38_STATE_ROOT/artifacts" "$artifact"
  printf '%s\n' "$reason" >"$artifact/reason.txt"
  compose ps --all --format json >"$artifact/compose-ps.json" || true
  compose logs --no-color "$SERVICE" >"$artifact/server.log" 2>&1 || true
  if ! compose stop --timeout 30 "$SERVICE" >"$artifact/cleanup.log" 2>&1; then
    cleanup_ok=false
  fi
  if [[ -n "$(compose ps --status running -q "$SERVICE")" ]] || ss -H -ltn "sport = :$QWEN38_PORT" | grep -q .; then
    cleanup_ok=false
  fi
  jq -n --arg reason "$reason" --arg artifact "$artifact" --argjson cleanup_ok "$cleanup_ok" \
    '{status:"failed",reason:$reason,artifact:$artifact,cleanup_ok:$cleanup_ok}' >"$artifact/receipt.json"
  if [[ "$cleanup_ok" != true ]]; then
    printf 'Qwen3.8 cleanup failed; evidence=%s\n' "$artifact" >&2
    return 2
  fi
  printf 'Qwen3.8 failed readiness and was stopped; evidence=%s\n' "$artifact" >&2
  return 1
}

start() {
  local controller_started deadline run_id container
  controller_started="$(date +%s)"
  deadline=$((controller_started + READINESS_DEADLINE_SECONDS))
  trap 'capture_and_stop_failed_start signal-HUP; exit $?' HUP
  trap 'capture_and_stop_failed_start signal-INT; exit $?' INT
  trap 'capture_and_stop_failed_start signal-TERM; exit $?' TERM
  check
  mkdir -p "$QWEN38_CACHE_DIR" "$QWEN38_STATE_ROOT/artifacts"
  chmod 700 "$QWEN38_STATE_ROOT" "$QWEN38_STATE_ROOT/artifacts"
  compose up -d "$SERVICE"
  while (( $(date +%s) < deadline )); do
    if curl -fsS --max-time 3 "http://127.0.0.1:$QWEN38_PORT/v1/models" |
      jq -e --arg model "$QWEN38_SERVED_MODEL" '.data[] | select(.id == $model)' >/dev/null 2>&1; then
      container="$(compose ps -q "$SERVICE")"
      run_id="$(date -u +%Y%m%dT%H%M%SZ)"
      jq -n --arg run_id "$run_id" --arg container "$container" --arg model "$QWEN38_SERVED_MODEL" \
        --arg revision 16b6615af3548b88e2d8e382457bc705b00479cf \
        '{run_id:$run_id,container:$container,model:$model,revision:$revision}' >"$QWEN38_STATE_ROOT/active.json.tmp"
      chmod 600 "$QWEN38_STATE_ROOT/active.json.tmp"
      mv "$QWEN38_STATE_ROOT/active.json.tmp" "$QWEN38_STATE_ROOT/active.json"
      trap - HUP INT TERM
      status
      return 0
    fi
    [[ -n "$(compose ps --status running -q "$SERVICE")" ]] || break
    sleep 15
  done
  capture_and_stop_failed_start readiness-timeout
}

stop() {
  local run_id artifact container
  run_id="$(date -u +%Y%m%dT%H%M%SZ)"
  artifact="$QWEN38_STATE_ROOT/artifacts/$run_id"
  mkdir -p "$artifact"
  chmod 700 "$QWEN38_STATE_ROOT" "$QWEN38_STATE_ROOT/artifacts" "$artifact"
  container="$(compose ps -aq "$SERVICE")"
  compose ps --all --format json >"$artifact/compose-ps.json" || true
  compose logs --no-color "$SERVICE" >"$artifact/server.log" 2>&1 || true
  if [[ -n "$container" ]]; then
    docker inspect "$container" >"$artifact/container-inspect.json"
  fi
  compose stop --timeout 30 "$SERVICE"
  [[ -z "$(compose ps --status running -q "$SERVICE")" ]]
  ! ss -H -ltn "sport = :$QWEN38_PORT" | grep -q .
  rm -f "$QWEN38_STATE_ROOT/active.json"
  jq -n --arg run_id "$run_id" --arg artifact "$artifact" \
    '{status:"stopped",run_id:$run_id,artifact:$artifact}'
}

case "${1:-}" in
  check) check ;;
  start) start ;;
  status) status ;;
  stop|rollback) stop ;;
  *) printf 'usage: %s {check|start|status|stop|rollback}\n' "$0" >&2; exit 2 ;;
esac
