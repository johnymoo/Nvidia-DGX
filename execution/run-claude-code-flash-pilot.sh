#!/usr/bin/env bash
set -Eeuo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
RUNNER="$SCRIPT_DIR/benchmarks/claude_code_sandbox_pilot.py"
TASK_MANIFEST="$SCRIPT_DIR/benchmarks/claude-code-sandbox-pilot-tasks.json"
SERVICE_SCRIPT="$SCRIPT_DIR/run-vllm-service.sh"
TOOLCHAIN="${CODING_AGENT_TOOLCHAIN:-/Users/chris/project/Shili/workspaces/coding-agent-toolchain}"
CACHE_ROOT="${CLAUDE_PILOT_CACHE:-$SCRIPT_DIR/artifacts/claude-code-pilot/cache}"
ARTIFACT_BASE="${CLAUDE_PILOT_ARTIFACT_ROOT:-$SCRIPT_DIR/artifacts/claude-code-pilot/runs}"
REMOTE_ALIAS="${GB10_HEAD_ALIAS:-gb10}"
REMOTE_ROOT="${GB10_REMOTE_ROOT:-/home/chriswang/gb10-ds4}"
ACTIVE_REMOTE_SERVICE=0
CURRENT_ARTIFACT=""

usage() {
  echo "Usage: $0 {--preflight|--run|--status|--restore-qwen}" >&2
}

log() {
  printf '[%s] %s\n' "$(date -u +%Y-%m-%dT%H:%M:%SZ)" "$*"
}

require_command() {
  command -v "$1" >/dev/null 2>&1 || { echo "missing command: $1" >&2; return 1; }
}

runner() {
  python3 "$RUNNER" \
    --cache "$CACHE_ROOT" --toolchain "$TOOLCHAIN" "$@"
}

sync_service_script() {
  rsync -az --checksum "$SERVICE_SCRIPT" "$REMOTE_ALIAS:$REMOTE_ROOT/execution/run-vllm-service.sh"
  ssh "$REMOTE_ALIAS" "chmod 0755 '$REMOTE_ROOT/execution/run-vllm-service.sh'"
  local local_sha remote_sha
  local_sha="$(shasum -a 256 "$SERVICE_SCRIPT" | awk '{print $1}')"
  remote_sha="$(ssh "$REMOTE_ALIAS" "sha256sum '$REMOTE_ROOT/execution/run-vllm-service.sh'")"
  remote_sha="${remote_sha%% *}"
  [ "$local_sha" = "$remote_sha" ] || { echo "remote service script SHA mismatch" >&2; return 1; }
}

static_checks() {
  local command
  for command in bash git jq python3 rsync shasum ssh; do
    require_command "$command"
  done
  [ -x "$TOOLCHAIN/bin/claude" ] || { echo "toolchain Claude shim missing" >&2; return 1; }
  [ -s "$TASK_MANIFEST" ] || { echo "task manifest missing" >&2; return 1; }
  jq -e '.schema_version == 2 and (.tasks | length == 4)' "$TASK_MANIFEST" >/dev/null
  bash -n "$SERVICE_SCRIPT" "$SCRIPT_DIR/run-vllm-acceptance.sh" "$0"
  python3 -m py_compile "$RUNNER"
  "$SCRIPT_DIR/benchmarks/test-run-vllm-acceptance.sh" >/dev/null
  python3 "$SCRIPT_DIR/benchmarks/test-claude-code-sandbox-pilot.py" >/dev/null
  "$SCRIPT_DIR/benchmarks/test-run-claude-code-flash-pilot.sh" >/dev/null
  "$SCRIPT_DIR/benchmarks/test-run-vllm-service.sh" >/dev/null
  if command -v shellcheck >/dev/null 2>&1; then
    shellcheck "$SERVICE_SCRIPT" "$0"
  fi
  git -C "$PROJECT_ROOT" diff --check
}

run_preflight() {
  local run_id artifact
  run_id="preflight-$(date -u +%Y%m%dT%H%M%SZ)"
  artifact="$ARTIFACT_BASE/$run_id"
  mkdir -p "$artifact"
  log "preflight: static and fake checks"
  static_checks
  log "preflight: synchronize immutable service controller"
  sync_service_script
  log "preflight: read-only two-host Patch4/Qwen/fabric checks"
  ssh "$REMOTE_ALIAS" "cd '$REMOTE_ROOT' && execution/run-vllm-service.sh --check" \
    >"$artifact/remote-service-check.json"
  jq -e '.status == "passed" and .mutation == false' "$artifact/remote-service-check.json" >/dev/null
  log "preflight: Claude Code protocol and deterministic sandbox calibration"
  runner --preflight --artifact-root "$artifact" | tee "$artifact/runner-preflight.stdout.json"
  jq -e '.status == "passed"' "$artifact/preflight-receipt.json" >/dev/null
  log "preflight passed: $artifact/preflight-receipt.json"
}

rollback_on_exit() {
  local original_code=$?
  trap - EXIT ERR INT TERM
  set +e
  rollback_active_service
  exit "$original_code"
}

rollback_active_service() {
  if [ "$ACTIVE_REMOTE_SERVICE" -eq 1 ]; then
    log "infrastructure failure: stopping DeepSeek and restoring captured Qwen state"
    ssh "$REMOTE_ALIAS" "cd '$REMOTE_ROOT' && execution/run-vllm-service.sh --stop --restore-qwen" \
      >"${CURRENT_ARTIFACT:-/tmp}/rollback-receipt.json" 2>"${CURRENT_ARTIFACT:-/tmp}/rollback.stderr.log"
  fi
}

run_formal() {
  local run_id artifact service_status result_file
  run_id="$(date -u +%Y%m%dT%H%M%SZ)"
  artifact="$ARTIFACT_BASE/$run_id"
  CURRENT_ARTIFACT="$artifact"
  mkdir -p "$artifact"

  log "run: static freshness checks"
  static_checks
  sync_service_script
  log "run: remote read-only prestart check"
  ssh "$REMOTE_ALIAS" "cd '$REMOTE_ROOT' && execution/run-vllm-service.sh --check" \
    >"$artifact/remote-prestart-check.json"
  jq -e '.status == "passed" and .mutation == false' "$artifact/remote-prestart-check.json" >/dev/null

  trap rollback_on_exit EXIT ERR INT TERM
  log "run: offloading Qwen and starting two-host Patch4 DeepSeek"
  ACTIVE_REMOTE_SERVICE=1
  ssh "$REMOTE_ALIAS" "cd '$REMOTE_ROOT' && execution/run-vllm-service.sh --start" \
    | tee "$artifact/service-start-receipt.json"
  jq -e '.state == "running" and .release.patch4 == true and .release.model == "deepseek-v4-flash-0731"' \
    "$artifact/service-start-receipt.json" >/dev/null
  log "run: executing the frozen Claude Code sandbox task loop and deterministic grading"
  runner --run --artifact-root "$artifact" | tee "$artifact/runner.stdout.json"
  result_file="$artifact/result.json"
  jq -e '.status == "completed"' "$result_file" >/dev/null

  log "run: final DeepSeek/protected-service status"
  ssh "$REMOTE_ALIAS" "cd '$REMOTE_ROOT' && execution/run-vllm-service.sh --status" \
    >"$artifact/service-final-status.json"
  service_status="$(jq -r '.state' "$artifact/service-final-status.json")"
  [ "$service_status" = "running" ] || { echo "final service state is $service_status" >&2; return 1; }

  jq -n \
    --arg run_id "$run_id" --arg artifact "$artifact" \
    --arg result "$result_file" --arg service_receipt "$artifact/service-start-receipt.json" \
    --arg status_receipt "$artifact/service-final-status.json" \
    --arg started "$(jq -r '.started_at' "$artifact/service-start-receipt.json")" \
    --arg ended "$(date -u +%Y-%m-%dT%H:%M:%SZ)" \
    --argjson online_passed "$(jq '.passed.online' "$result_file")" \
    --argjson private_passed "$(jq '.passed.private' "$result_file")" \
    '{schema_version:1,status:"passed",run_id:$run_id,started_at:$started,ended_at:$ended,
      baseline_revision:"claude-ds-pilot-r1",artifact:$artifact,
      results:{path:$result,online_passed:$online_passed,private_passed:$private_passed,total_tasks:4},
      service:{state:"running",deepseek_model:"deepseek-v4-flash-0731",qwen_state:"stopped",start_receipt:$service_receipt,status_receipt:$status_receipt},
      rollback:{command:"execution/run-claude-code-flash-pilot.sh --restore-qwen",performed:false}}' \
    >"$artifact/receipt.json"

  ACTIVE_REMOTE_SERVICE=0
  trap - EXIT ERR INT TERM
  log "run passed; DeepSeek remains running and Qwen remains stopped"
  cat "$artifact/receipt.json"
}

status() {
  sync_service_script
  ssh "$REMOTE_ALIAS" "cd '$REMOTE_ROOT' && execution/run-vllm-service.sh --status"
}

restore_qwen() {
  sync_service_script
  ssh "$REMOTE_ALIAS" "cd '$REMOTE_ROOT' && execution/run-vllm-service.sh --stop --restore-qwen"
}

main() {
  [ "$#" -eq 1 ] || { usage; return 64; }
  case "$1" in
    --preflight) run_preflight ;;
    --run) run_formal ;;
    --status) status ;;
    --restore-qwen) restore_qwen ;;
    *) usage; return 64 ;;
  esac
}

if [ "${BASH_SOURCE[0]}" = "$0" ]; then
  main "$@"
fi
