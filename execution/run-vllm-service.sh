#!/usr/bin/env bash
set -Eeuo pipefail

SERVICE_SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=run-vllm-acceptance.sh
source "$SERVICE_SCRIPT_DIR/run-vllm-acceptance.sh"

SERVICE_ARTIFACT_ROOT="${SERVICE_ARTIFACT_ROOT:-$DEPLOY_ROOT/artifacts/service}"
SERVICE_ACTIVE_STATE="${SERVICE_ACTIVE_STATE:-$SERVICE_ARTIFACT_ROOT/active.json}"
SERVICE_START_COMPLETE=0
SERVICE_RECEIPT=""

service_usage() {
  echo "Usage: $0 {--check|--start|--status|--stop --restore-qwen}" >&2
}

service_write_receipt() {
  local state="$1" exit_code="$2" ended_at receipt
  ended_at="$(date -u +%Y-%m-%dT%H:%M:%SZ)"
  receipt="$ARTIFACT_DIR/service-receipt.json"
  "$JQ_BIN" -n \
    --arg state "$state" --arg failure "$FAILURE_REASON" \
    --arg run_id "$RUN_ID" --arg started "$RUN_START_ISO" --arg ended "$ended_at" \
    --arg revision "$EXPECTED_REVISION" --arg image "$EXPECTED_IMAGE" \
    --arg fingerprint "$EXPECTED_FINGERPRINT" --arg model "$EXPECTED_API_MODEL" \
    --arg head "$(hostname -s)" --arg worker "$EXPECTED_WORKER_HOST" \
    --arg artifact "$ARTIFACT_DIR" --arg worker_artifact "$WORKER_ARTIFACT_DIR" \
    --arg head_container "$HEAD_CONTAINER_ID" --arg worker_container "$WORKER_CONTAINER_ID" \
    --argjson exit_code "$exit_code" \
    --argjson qwen_was_running "$QWEN_WAS_RUNNING" \
    --argjson qwen_stopped "$QWEN_STOPPED" \
    --argjson qwen_restore_attempted "$QWEN_RESTORE_ATTEMPTED" \
    --argjson qwen_restored "$QWEN_RESTORED" \
    --argjson pdf_was_running "$PDF_WAS_RUNNING" \
    --argjson trading_was_running "$TRADING_WAS_RUNNING" \
    --arg lexdata_before "$LEXDATA_STATUS_BEFORE" \
    '{schema_version:1,state:$state,failure_reason:$failure,run_id:$run_id,
      started_at:$started,ended_at:$ended,exit_code:$exit_code,
      release:{revision:$revision,image:$image,fingerprint:$fingerprint,model:$model,patch4:true},
      topology:{head:$head,worker:$worker,tp:2,nnodes:2,head_container:$head_container,worker_container:$worker_container},
      qwen:{was_running:($qwen_was_running==1),stopped:($qwen_stopped==1),restore_attempted:($qwen_restore_attempted==1),restored:($qwen_restored==1)},
      protected:{pdf2md_was_running:($pdf_was_running==1),trading_was_running:($trading_was_running==1),lexdata_before:$lexdata_before},
      evidence:{head:$artifact,worker:$worker_artifact}}' >"$receipt"
  SERVICE_RECEIPT="$receipt"
}

service_write_active_state() {
  local tmp="$SERVICE_ACTIVE_STATE.tmp.$$"
  mkdir -p "$(dirname "$SERVICE_ACTIVE_STATE")"
  "$JQ_BIN" -n \
    --arg run_id "$RUN_ID" --arg started "$RUN_START_ISO" \
    --arg artifact "$ARTIFACT_DIR" --arg worker_artifact "$WORKER_ARTIFACT_DIR" \
    --arg receipt "$SERVICE_RECEIPT" \
    --arg head_container "$HEAD_CONTAINER_ID" --arg worker_container "$WORKER_CONTAINER_ID" \
    --arg revision "$EXPECTED_REVISION" --arg fingerprint "$EXPECTED_FINGERPRINT" \
    --arg model "$EXPECTED_API_MODEL" \
    --argjson qwen_was_running "$QWEN_WAS_RUNNING" \
    --argjson qwen_stopped "$QWEN_STOPPED" \
    --argjson pdf_was_running "$PDF_WAS_RUNNING" \
    --argjson trading_was_running "$TRADING_WAS_RUNNING" \
    --arg lexdata_before "$LEXDATA_STATUS_BEFORE" \
    '{schema_version:1,state:"running",run_id:$run_id,started_at:$started,
      artifact:$artifact,worker_artifact:$worker_artifact,receipt:$receipt,
      release:{revision:$revision,fingerprint:$fingerprint,model:$model,patch4:true},
      containers:{head:$head_container,worker:$worker_container},
      qwen:{was_running:($qwen_was_running==1),stopped:($qwen_stopped==1)},
      protected:{pdf2md_was_running:($pdf_was_running==1),trading_was_running:($trading_was_running==1),lexdata_before:$lexdata_before}}' >"$tmp"
  mv "$tmp" "$SERVICE_ACTIVE_STATE"
}

service_protected_state_ok() {
  local pdf_now trading_now lexdata_now
  pdf_now="$(container_running "$PDF_CONTAINER" && printf 1 || printf 0)"
  trading_now="$(container_running "$TRADING_CONTAINER" && printf 1 || printf 0)"
  lexdata_now="$(remote "docker inspect -f '{{if .State.Health}}{{.State.Health.Status}}{{else}}{{.State.Status}}{{end}}' '$LEXDATA_CONTAINER'")"
  [ "$pdf_now" = "$PDF_WAS_RUNNING" ] || { echo "protected service changed: pdf2md" >&2; return 1; }
  [ "$trading_now" = "$TRADING_WAS_RUNNING" ] || { echo "protected service changed: tradingagents" >&2; return 1; }
  [ "$lexdata_now" = "$LEXDATA_STATUS_BEFORE" ] || { echo "protected service changed: lexdata-ai" >&2; return 1; }
}

service_on_error() {
  local line="$1" code="$2"
  [ -n "$FAILURE_REASON" ] || FAILURE_REASON="service command failed at line $line with exit $code"
  return "$code"
}

service_on_signal() {
  FAILURE_REASON="service received signal $1"
  exit 130
}

service_on_start_exit() {
  local original_code=$? cleanup_code=0
  trap - EXIT ERR INT TERM
  set +e
  stop_monitor
  if [ "$SERVICE_START_COMPLETE" -eq 1 ] && [ "$original_code" -eq 0 ]; then
    exit 0
  fi
  STATUS=failed
  if [ -n "$ARTIFACT_DIR" ] && [ -d "$ARTIFACT_DIR" ]; then
    capture_host_snapshot failed "$ARTIFACT_DIR/failed-head" || true
    capture_worker_snapshot failed "$WORKER_ARTIFACT_DIR/failed-worker" || true
  fi
  restore_services || cleanup_code=1
  if [ -n "$ARTIFACT_DIR" ] && [ -d "$ARTIFACT_DIR" ]; then
    capture_host_snapshot post-rollback "$ARTIFACT_DIR/post-rollback-head" || true
    capture_worker_snapshot post-rollback "$WORKER_ARTIFACT_DIR/post-rollback-worker" || true
    service_write_receipt failed 1 || true
  fi
  [ "$cleanup_code" -eq 0 ] || echo "service rollback failed; inspect $ARTIFACT_DIR" >&2
  exit 1
}

service_start() {
  local artifact_root contract
  [ ! -e "$SERVICE_ACTIVE_STATE" ] || die "active service state already exists: $SERVICE_ACTIVE_STATE"
  run_checks >/dev/null
  load_env

  RUN_ID="$(date -u +%Y%m%dT%H%M%SZ)"
  RUN_START_ISO="$(date -u +%Y-%m-%dT%H:%M:%SZ)"
  artifact_root="$SERVICE_ARTIFACT_ROOT"
  ARTIFACT_DIR="$artifact_root/$RUN_ID"
  WORKER_ARTIFACT_DIR="$WORKER_DEPLOY_ROOT/artifacts/service/$RUN_ID"
  mkdir -p "$ARTIFACT_DIR"
  KEEP_QWEN_STOPPED_ON_FAILURE=0
  RESTORE_QWEN_ON_SUCCESS=0
  PRESERVE_DEEPSEEK_CONTAINERS=1

  trap 'service_on_error "$LINENO" "$?"' ERR
  trap 'service_on_signal INT' INT
  trap 'service_on_signal TERM' TERM
  trap service_on_start_exit EXIT

  capture_host_snapshot baseline "$ARTIFACT_DIR/baseline-head"
  capture_worker_snapshot baseline "$WORKER_ARTIFACT_DIR/baseline-worker"
  contract="$(qwen_contract)"
  printf '%s\n' "$contract" >"$ARTIFACT_DIR/qwen-contract.json"
  QWEN_CONTRACT_CAPTURED=1
  QWEN_WAS_RUNNING="$("$JQ_BIN" -r 'if .running then 1 else 0 end' <<<"$contract")"
  container_running "$PDF_CONTAINER" && PDF_WAS_RUNNING=1
  container_running "$TRADING_CONTAINER" && TRADING_WAS_RUNNING=1
  "$DOCKER_BIN" inspect "$QWEN_CONTAINER" "$PDF_CONTAINER" "$TRADING_CONTAINER" >"$ARTIFACT_DIR/head-services-before.json"
  remote "docker inspect '$LEXDATA_CONTAINER'" >"$ARTIFACT_DIR/worker-lexdata-before.json"
  LEXDATA_STATUS_BEFORE="$(remote "docker inspect -f '{{if .State.Health}}{{.State.Health.Status}}{{else}}{{.State.Status}}{{end}}' '$LEXDATA_CONTAINER'")"
  SERVICE_STATE_CAPTURED=1

  if [ "$QWEN_WAS_RUNNING" -eq 1 ]; then
    log "service: stopping only Qwen" >&2
    qwen_compose stop >&2
    QWEN_STOPPED=1
    wait_port_free 8004 180 || die "Qwen port 8004 did not release"
  fi
  service_protected_state_ok || die "protected service state changed while stopping Qwen"

  DEEPSEEK_TOUCHED=1
  log "service: starting worker DeepSeek" >&2
  worker_compose up -d "$COMPOSE_SERVICE" >&2
  WORKER_CONTAINER_ID="$(worker_compose ps -q "$COMPOSE_SERVICE")"
  [ -n "$WORKER_CONTAINER_ID" ] || die "worker container ID is empty"
  log "service: starting head DeepSeek" >&2
  head_compose up -d "$COMPOSE_SERVICE" >&2
  HEAD_CONTAINER_ID="$(head_compose ps -q "$COMPOSE_SERVICE")"
  [ -n "$HEAD_CONTAINER_ID" ] || die "head container ID is empty"

  HEAD_FABRIC_ERRORS="$(fabric_error_sum)"
  WORKER_FABRIC_ERRORS="$(worker_fabric_error_sum)"
  start_runtime_log_capture
  start_monitor
  wait_ready || { die "$FAILURE_REASON"; return 1; }
  assert_runtime
  service_protected_state_ok || die "protected service state changed during DeepSeek startup"
  if [ "$QWEN_WAS_RUNNING" -eq 1 ]; then
    ! container_running "$QWEN_CONTAINER" || die "Qwen restarted during DeepSeek startup"
  fi
  stop_monitor
  capture_host_snapshot running "$ARTIFACT_DIR/running-head"
  capture_worker_snapshot running "$WORKER_ARTIFACT_DIR/running-worker"
  STATUS=passed
  service_write_receipt running 0
  service_write_active_state
  SERVICE_START_COMPLETE=1
  trap - EXIT ERR INT TERM
  "$JQ_BIN" . "$SERVICE_RECEIPT"
}

service_load_active() {
  [ -s "$SERVICE_ACTIVE_STATE" ] || die "no active DeepSeek service state: $SERVICE_ACTIVE_STATE"
  "$JQ_BIN" -e '
    .schema_version == 1 and .state == "running" and
    .release.revision == "f277b3dfa718a5962bed64e69e7e640a5384ec2f" and
    .release.fingerprint == "36adbf92fe8cdd5c57609b2c5ccfa8e2fc32a340c9ee3d727be538143dda74db" and
    .release.model == "deepseek-v4-flash-0731" and .release.patch4 == true
  ' "$SERVICE_ACTIVE_STATE" >/dev/null || die "active service state contract mismatch"
  RUN_ID="$("$JQ_BIN" -r '.run_id' "$SERVICE_ACTIVE_STATE")"
  RUN_START_ISO="$("$JQ_BIN" -r '.started_at' "$SERVICE_ACTIVE_STATE")"
  ARTIFACT_DIR="$("$JQ_BIN" -r '.artifact' "$SERVICE_ACTIVE_STATE")"
  WORKER_ARTIFACT_DIR="$("$JQ_BIN" -r '.worker_artifact' "$SERVICE_ACTIVE_STATE")"
  HEAD_CONTAINER_ID="$("$JQ_BIN" -r '.containers.head' "$SERVICE_ACTIVE_STATE")"
  WORKER_CONTAINER_ID="$("$JQ_BIN" -r '.containers.worker' "$SERVICE_ACTIVE_STATE")"
  QWEN_WAS_RUNNING="$("$JQ_BIN" -r 'if .qwen.was_running then 1 else 0 end' "$SERVICE_ACTIVE_STATE")"
  QWEN_STOPPED="$("$JQ_BIN" -r 'if .qwen.stopped then 1 else 0 end' "$SERVICE_ACTIVE_STATE")"
  PDF_WAS_RUNNING="$("$JQ_BIN" -r 'if .protected.pdf2md_was_running then 1 else 0 end' "$SERVICE_ACTIVE_STATE")"
  TRADING_WAS_RUNNING="$("$JQ_BIN" -r 'if .protected.trading_was_running then 1 else 0 end' "$SERVICE_ACTIVE_STATE")"
  LEXDATA_STATUS_BEFORE="$("$JQ_BIN" -r '.protected.lexdata_before' "$SERVICE_ACTIVE_STATE")"
  QWEN_CONTRACT_CAPTURED=1
  SERVICE_STATE_CAPTURED=1
}

service_status() {
  local ids head_running worker_running qwen_running protected_ok=true
  load_env
  if [ ! -s "$SERVICE_ACTIVE_STATE" ]; then
    "$JQ_BIN" -n --arg qwen_health "$(container_health "$QWEN_CONTAINER")" \
      '{schema_version:1,state:"stopped",qwen_health:$qwen_health}'
    return 0
  fi
  service_load_active
  head_running="$("$DOCKER_BIN" inspect -f '{{.State.Running}}' "$HEAD_CONTAINER_ID" 2>/dev/null || printf false)"
  worker_running="$(remote "docker inspect -f '{{.State.Running}}' '$WORKER_CONTAINER_ID' 2>/dev/null || printf false")"
  ids="$("$CURL_BIN" -fsS --max-time 15 "$API_BASE/v1/models" 2>/dev/null | "$JQ_BIN" -r '.data[].id' 2>/dev/null || true)"
  qwen_running="$(container_running "$QWEN_CONTAINER" && printf true || printf false)"
  service_protected_state_ok || protected_ok=false
  "$JQ_BIN" -n \
    --arg run_id "$RUN_ID" --arg model "$EXPECTED_API_MODEL" \
    --argjson head_running "$head_running" --argjson worker_running "$worker_running" \
    --argjson qwen_running "$qwen_running" --argjson protected_ok "$protected_ok" \
    --argjson model_ok "$(grep -Fxq "$EXPECTED_API_MODEL" <<<"$ids" && printf true || printf false)" \
    '{schema_version:1,state:(if $head_running and $worker_running and $model_ok and $protected_ok and ($qwen_running|not) then "running" else "degraded" end),
      run_id:$run_id,model:$model,head_running:$head_running,worker_running:$worker_running,
      model_ok:$model_ok,qwen_running:$qwen_running,protected_services_ok:$protected_ok}'
}

service_stop_restore() {
  load_env
  service_load_active
  DEEPSEEK_TOUCHED=1
  STATUS=failed
  KEEP_QWEN_STOPPED_ON_FAILURE=0
  RESTORE_QWEN_ON_SUCCESS=0
  PRESERVE_DEEPSEEK_CONTAINERS=1
  if ! restore_services; then
    FAILURE_REASON="DeepSeek stop or Qwen restore failed"
    service_write_receipt degraded 1
    "$JQ_BIN" . "$SERVICE_RECEIPT"
    return 1
  fi
  capture_host_snapshot restored "$ARTIFACT_DIR/restored-head"
  capture_worker_snapshot restored "$WORKER_ARTIFACT_DIR/restored-worker"
  service_write_receipt stopped 0
  rm -f "$SERVICE_ACTIVE_STATE"
  "$JQ_BIN" . "$SERVICE_RECEIPT"
}

service_main() {
  case "$#:$1:${2:-}" in
    1:--check:) run_checks ;;
    1:--start:) service_start ;;
    1:--status:) service_status ;;
    2:--stop:--restore-qwen) service_stop_restore ;;
    *) service_usage; return 64 ;;
  esac
}

if [ "${BASH_SOURCE[0]}" = "$0" ]; then
  service_main "$@"
fi
