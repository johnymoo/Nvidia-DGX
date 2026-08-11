#!/usr/bin/env bash
set -Eeuo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
RUNNER="$SCRIPT_DIR/benchmarks/claude_code_sandbox_pilot.py"
TASK_MANIFEST="$SCRIPT_DIR/benchmarks/claude-code-sandbox-pilot-tasks.json"
SERVICE_SCRIPT="$SCRIPT_DIR/run-vllm-service.sh"
ACCEPTANCE_SCRIPT="$SCRIPT_DIR/run-vllm-acceptance.sh"
TOOLCHAIN="${CODING_AGENT_TOOLCHAIN:-/Users/chris/project/Shili/workspaces/coding-agent-toolchain}"
CACHE_ROOT="${CLAUDE_PILOT_CACHE:-$SCRIPT_DIR/artifacts/claude-code-pilot/cache}"
ARTIFACT_BASE="${CLAUDE_PILOT_ARTIFACT_ROOT:-$SCRIPT_DIR/artifacts/claude-code-pilot/runs}"
REMOTE_ALIAS="${GB10_HEAD_ALIAS:-gb10}"
REMOTE_ROOT="${GB10_REMOTE_ROOT:-/home/chriswang/gb10-ds4}"
CURRENT_ARTIFACT=""
CURRENT_PHASE="pre-transition"
REVIEW_PID=""

usage() {
  echo "Usage: $0 {--preflight|--run|--resume-run ARTIFACT|--status|--restore-qwen}" >&2
}

log() {
  printf '[%s] %s\n' "$(date -u +%Y-%m-%dT%H:%M:%SZ)" "$*"
}

require_command() {
  command -v "$1" >/dev/null 2>&1 || { echo "missing command: $1" >&2; return 1; }
}

runner() {
  python3 "$RUNNER" --cache "$CACHE_ROOT" --toolchain "$TOOLCHAIN" "$@"
}

sync_service_script() {
  local name local_path local_sha remote_sha
  for local_path in "$SERVICE_SCRIPT" "$ACCEPTANCE_SCRIPT"; do
    name="$(basename "$local_path")"
    rsync -az --checksum "$local_path" "$REMOTE_ALIAS:$REMOTE_ROOT/execution/$name"
    ssh "$REMOTE_ALIAS" "chmod 0755 '$REMOTE_ROOT/execution/$name'"
    local_sha="$(shasum -a 256 "$local_path" | awk '{print $1}')"
    remote_sha="$(ssh "$REMOTE_ALIAS" "sha256sum '$REMOTE_ROOT/execution/$name'")"
    remote_sha="${remote_sha%% *}"
    [ "$local_sha" = "$remote_sha" ] || { echo "remote $name SHA mismatch" >&2; return 1; }
  done
}

static_checks() {
  local command
  for command in bash codex git jq python3 shasum ssh rsync; do
    require_command "$command"
  done
  [ -x "$TOOLCHAIN/bin/claude" ] || { echo "toolchain Claude shim missing" >&2; return 1; }
  [ -s "$TASK_MANIFEST" ] || { echo "task manifest missing" >&2; return 1; }
  jq -e '.schema_version == 3 and .baseline_revision == "claude-ds-pilot-r2" and (.tasks | length == 7) and (.treatments | keys == ["offline_ds", "online_ds", "qwen_local"])' "$TASK_MANIFEST" >/dev/null
  bash -n "$SERVICE_SCRIPT" "$ACCEPTANCE_SCRIPT" "$0"
  python3 -m py_compile "$RUNNER"
  "$SCRIPT_DIR/benchmarks/test-run-vllm-acceptance.sh" >/dev/null
  python3 "$SCRIPT_DIR/benchmarks/test-claude-code-sandbox-pilot.py" >/dev/null
  "$SCRIPT_DIR/benchmarks/test-run-claude-code-flash-pilot.sh" >/dev/null
  "$SCRIPT_DIR/benchmarks/test-run-vllm-service.sh" >/dev/null
  if command -v shellcheck >/dev/null 2>&1; then
    shellcheck "$SERVICE_SCRIPT" "$ACCEPTANCE_SCRIPT" "$0"
  fi
  git -C "$PROJECT_ROOT" diff --check
}

run_preflight() {
  local run_id artifact
  run_id="preflight-$(date -u +%Y%m%dT%H%M%SZ)"
  artifact="$ARTIFACT_BASE/$run_id"
  mkdir -p "$artifact"
  log "preflight: static, unit, fake, and red/gold calibration"
  static_checks
  log "preflight: Claude Code identity calibration"
  runner --preflight --artifact-root "$artifact" | tee "$artifact/runner-preflight.stdout.json"
  jq -e '.status == "passed" and (.task_ids | length == 7) and (.treatment_contracts | keys == ["offline_ds", "online_ds", "qwen_local"])' "$artifact/preflight-receipt.json" >/dev/null
  log "preflight passed: $artifact/preflight-receipt.json"
}

remote_service() {
  ssh "$REMOTE_ALIAS" "cd '$REMOTE_ROOT' && execution/run-vllm-service.sh $*"
}

recover_on_exit() {
  local original_code=$?
  trap - EXIT ERR INT TERM
  set +e
  if [ "$CURRENT_PHASE" = "pre-transition" ]; then
    log "infrastructure failure before transition: restoring captured Qwen state"
    remote_service "--stop --restore-qwen" >"$CURRENT_ARTIFACT/rollback-receipt.json" 2>"$CURRENT_ARTIFACT/rollback.stderr.log"
  else
    log "infrastructure failure after transition: keeping DeepSeek stopped and retrying Qwen recovery"
    remote_service "--transition-qwen" >"$CURRENT_ARTIFACT/qwen-recovery-receipt.json" 2>"$CURRENT_ARTIFACT/qwen-recovery.stderr.log"
  fi
  exit "$original_code"
}

start_review_server() {
  local review_root="$1" output="$CURRENT_ARTIFACT/review-server.json" deadline review_url
  runner --serve-review --review-root "$review_root" --artifact-root "$CURRENT_ARTIFACT" >"$output" 2>"$CURRENT_ARTIFACT/review-server.stderr.log" &
  REVIEW_PID="$!"
  deadline=$((SECONDS + 15))
  while [ "$SECONDS" -lt "$deadline" ]; do
    if [ -s "$output" ]; then
      review_url="$(jq -r '.url // empty' "$output" 2>/dev/null || true)"
      if [ -n "$review_url" ]; then
        printf '%s\n' "$review_url"
        return 0
      fi
    fi
    kill -0 "$REVIEW_PID" 2>/dev/null || break
    sleep 0.2
  done
  echo "review server did not publish a loopback URL" >&2
  return 1
}

run_formal() {
  local run_id artifact service_receipt transition_receipt package_receipt final_status review_url
  run_id="$(date -u +%Y%m%dT%H%M%SZ)"
  artifact="$ARTIFACT_BASE/$run_id"
  CURRENT_ARTIFACT="$artifact"
  mkdir -p "$artifact"

  log "run: static freshness checks"
  static_checks
  log "run: synchronize the immutable service controller"
  sync_service_script
  log "run: adopt the exact active Patch4 service or start its validated stopped contract"
  remote_service "--ensure-active" | tee "$artifact/service-deepseek-receipt.json"
  service_receipt="$artifact/service-deepseek-receipt.json"
  jq -e '(.state == "running") or (.service.state == "running")' "$service_receipt" >/dev/null

  trap recover_on_exit EXIT ERR INT TERM
  log "run: execute fourteen frozen DeepSeek attempts"
  runner --phase deepseek --artifact-root "$artifact" | tee "$artifact/runner-deepseek.stdout.json"
  jq -e '.status == "completed" and .attempt_count == 14' "$artifact/phase-deepseek-receipt.json" >/dev/null

  log "run: transition through the active receipt and force-start captured Qwen"
  CURRENT_PHASE="post-transition"
  remote_service "--transition-qwen" | tee "$artifact/service-transition-receipt.json"
  transition_receipt="$artifact/service-transition-receipt.json"
  jq -e '.state == "qwen-running" and .qwen.restored == true' "$transition_receipt" >/dev/null

  log "run: execute seven frozen Qwen attempts"
  runner --phase qwen --artifact-root "$artifact" | tee "$artifact/runner-qwen.stdout.json"
  jq -e '.status == "completed" and .attempt_count == 7' "$artifact/phase-qwen-receipt.json" >/dev/null

  log "run: invoke blind judge and package sealed human review"
  runner --package --artifact-root "$artifact" | tee "$artifact/runner-package.stdout.json"
  package_receipt="$artifact/phase-package-receipt.json"
  jq -e '.status == "ready_for_review" and .task_count == 7 and .human_task_count == 2 and .judge_only_task_count == 5 and .judge_count == 7 and .judge_runtime_contract.model == "gpt-5.6-sol" and .judge_runtime_contract.reasoning_effort == "xhigh" and .judge_runtime_contract.fallback_configured == false and .judge_runtime_contract.validated_calls == 7' "$package_receipt" >/dev/null
  review_url="$(start_review_server "$(jq -r '.review_root' "$package_receipt")")"

  log "run: verify DeepSeek remains stopped and Qwen is healthy"
  remote_service "--status" >"$artifact/service-final-status.json"
  final_status="$artifact/service-final-status.json"
  jq -e '.state == "stopped" and .qwen_health == "healthy"' "$final_status" >/dev/null

  jq -n \
    --arg run_id "$run_id" --arg artifact "$artifact" --arg url "$review_url" \
    --arg service "$service_receipt" --arg transition "$transition_receipt" \
    --arg deepseek "$artifact/phase-deepseek-receipt.json" --arg qwen "$artifact/phase-qwen-receipt.json" \
    --arg package "$package_receipt" --arg final "$final_status" --arg ended "$(date -u +%Y-%m-%dT%H:%M:%SZ)" \
    '{schema_version:1,status:"review_pending",baseline_revision:"claude-ds-pilot-r2",run_id:$run_id,ended_at:$ended,artifact:$artifact,review_url:$url,
      phases:{deepseek_service:$service,deepseek_attempts:$deepseek,transition:$transition,qwen_attempts:$qwen,package:$package,final_service:$final},
      final_state:{deepseek:"stopped",qwen:"healthy"},note:"Human review is pending; no statistical superiority claim."}' \
    >"$artifact/receipt.json"
  CURRENT_PHASE="complete"
  trap - EXIT ERR INT TERM
  log "run passed; DeepSeek is stopped, Qwen is healthy, review URL: $review_url"
  if command -v open >/dev/null 2>&1; then
    open "$review_url" >/dev/null 2>&1 || true
  fi
  cat "$artifact/receipt.json"
}

resume_formal() {
  local artifact="$1" artifact_base run_id service_receipt transition_receipt package_receipt final_status review_url
  artifact="$(cd "$artifact" && pwd)"
  artifact_base="$(mkdir -p "$ARTIFACT_BASE" && cd "$ARTIFACT_BASE" && pwd)"
  case "$artifact/" in
    "$artifact_base"/*/) ;;
    *) echo "resume artifact is outside the benchmark run root" >&2; return 64 ;;
  esac
  [ -f "$artifact/benchmark-state.json" ] || { echo "resume benchmark state missing" >&2; return 1; }
  [ -f "$artifact/resume-source-preflight-receipt.json" ] || { echo "resume source preflight missing" >&2; return 1; }
  jq -e '.status == "completed" and .attempt_count == 14' "$artifact/phase-deepseek-receipt.json" >/dev/null
  jq -e '.state == "qwen-running" and .qwen.restored == true' "$artifact/service-transition-receipt.json" >/dev/null
  [ ! -e "$artifact/receipt.json" ] || { echo "resume artifact already has a final receipt" >&2; return 1; }

  CURRENT_ARTIFACT="$artifact"
  CURRENT_PHASE="post-transition"
  run_id="$(basename "$artifact")"
  service_receipt="$artifact/service-deepseek-receipt.json"
  transition_receipt="$artifact/service-transition-receipt.json"

  log "resume: static checks and frozen checkpoint validation"
  static_checks
  remote_service "--status" >"$artifact/service-resume-status.json"
  jq -e '.state == "stopped" and .qwen_health == "healthy"' "$artifact/service-resume-status.json" >/dev/null
  trap recover_on_exit EXIT ERR INT TERM
  runner --rebind-preflight --old-preflight "$artifact/resume-source-preflight-receipt.json" --artifact-root "$artifact" | tee "$artifact/runner-resume-rebind.stdout.json"

  log "resume: execute only missing Qwen attempts"
  runner --phase qwen --artifact-root "$artifact" | tee "$artifact/runner-qwen-resume.stdout.json"
  jq -e '.status == "completed" and .attempt_count == 7' "$artifact/phase-qwen-receipt.json" >/dev/null

  log "resume: invoke blind judge and package sealed human review"
  runner --package --artifact-root "$artifact" | tee "$artifact/runner-package.stdout.json"
  package_receipt="$artifact/phase-package-receipt.json"
  jq -e '.status == "ready_for_review" and .task_count == 7 and .human_task_count == 2 and .judge_only_task_count == 5 and .judge_count == 7 and .judge_runtime_contract.model == "gpt-5.6-sol" and .judge_runtime_contract.reasoning_effort == "xhigh" and .judge_runtime_contract.fallback_configured == false and .judge_runtime_contract.validated_calls == 7' "$package_receipt" >/dev/null
  review_url="$(start_review_server "$(jq -r '.review_root' "$package_receipt")")"

  remote_service "--status" >"$artifact/service-final-status.json"
  final_status="$artifact/service-final-status.json"
  jq -e '.state == "stopped" and .qwen_health == "healthy"' "$final_status" >/dev/null
  jq -n \
    --arg run_id "$run_id" --arg artifact "$artifact" --arg url "$review_url" \
    --arg service "$service_receipt" --arg transition "$transition_receipt" \
    --arg deepseek "$artifact/phase-deepseek-receipt.json" --arg qwen "$artifact/phase-qwen-receipt.json" \
    --arg package "$package_receipt" --arg final "$final_status" --arg ended "$(date -u +%Y-%m-%dT%H:%M:%SZ)" \
    '{schema_version:1,status:"review_pending",baseline_revision:"claude-ds-pilot-r2",run_id:$run_id,ended_at:$ended,artifact:$artifact,review_url:$url,resumed:true,
      phases:{deepseek_service:$service,deepseek_attempts:$deepseek,transition:$transition,qwen_attempts:$qwen,package:$package,final_service:$final},
      final_state:{deepseek:"stopped",qwen:"healthy"},note:"Human review is pending; no statistical superiority claim."}' \
    >"$artifact/receipt.json"
  CURRENT_PHASE="complete"
  trap - EXIT ERR INT TERM
  log "resume passed; DeepSeek is stopped, Qwen is healthy, review URL: $review_url"
  if command -v open >/dev/null 2>&1; then
    open "$review_url" >/dev/null 2>&1 || true
  fi
  cat "$artifact/receipt.json"
}

status() {
  remote_service "--status"
}

restore_qwen() {
  remote_service "--stop --restore-qwen"
}

main() {
  [ "$#" -ge 1 ] || { usage; return 64; }
  case "$1" in
    --preflight) [ "$#" -eq 1 ] || { usage; return 64; }; run_preflight ;;
    --run) [ "$#" -eq 1 ] || { usage; return 64; }; run_formal ;;
    --resume-run) [ "$#" -eq 2 ] || { usage; return 64; }; resume_formal "$2" ;;
    --status) [ "$#" -eq 1 ] || { usage; return 64; }; status ;;
    --restore-qwen) [ "$#" -eq 1 ] || { usage; return 64; }; restore_qwen ;;
    *) usage; return 64 ;;
  esac
}

if [ "${BASH_SOURCE[0]}" = "$0" ]; then
  main "$@"
fi
