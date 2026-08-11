#!/usr/bin/env bash
set -Eeuo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
FIXTURE="$(mktemp -d)"
trap 'rm -rf "$FIXTURE"' EXIT
export ACCEPTANCE_TEST_MODE=1
export SERVICE_ARTIFACT_ROOT="$FIXTURE/artifacts"
export SERVICE_ACTIVE_STATE="$FIXTURE/artifacts/active.json"

# shellcheck source=../run-vllm-service.sh
source "$ROOT/execution/run-vllm-service.sh"

MOCK_LOG="$FIXTURE/actions.log"
MOCK_DOCKER="$FIXTURE/docker"
cat >"$MOCK_DOCKER" <<'MOCK'
#!/usr/bin/env bash
case "${1:-}" in
  inspect) printf '[]\n' ;;
  *) : ;;
esac
MOCK
chmod +x "$MOCK_DOCKER"
DOCKER_BIN="$MOCK_DOCKER"
JQ_BIN=jq

load_env() {
  WORKER_SSH=mock-worker
  WORKER_DEPLOY_ROOT="$FIXTURE/worker"
  FABRIC_IFNAME=enp1s0f0np0
  NCCL_IB_HCA=rocep1s0f0
}
run_checks() { :; }
capture_host_snapshot() { mkdir -p "$2"; }
capture_worker_snapshot() { mkdir -p "$2"; }
capture_runtime_diagnostics() { :; }
start_runtime_log_capture() { :; }
start_monitor() { :; }
stop_monitor() { :; }
fabric_error_sum() { printf '0\n'; }
worker_fabric_error_sum() { printf '0\n'; }
wait_port_free() { :; }
wait_ready() { :; }
assert_runtime() { :; }
qwen_contract() {
  printf '%s\n' '{"name":"qwen","running":true,"project":"qwen","service":"vllm","config_files":"/mock/compose.yml","working_dir":"/mock"}'
}
qwen_compose() { printf 'qwen %s\n' "$*" >>"$MOCK_LOG"; }
remote() {
  case "$*" in
    *inspect*) printf 'healthy\n' ;;
    *) : ;;
  esac
}
container_running() {
  case "$1" in
    "$PDF_CONTAINER"|"$TRADING_CONTAINER") return 0 ;;
    "$QWEN_CONTAINER") [ "$QWEN_STOPPED" -eq 0 ] ;;
    *) return 1 ;;
  esac
}
head_compose() {
  printf 'head %s\n' "$*" >>"$MOCK_LOG"
  [ "${1:-}" != ps ] || printf 'head-container\n'
}
worker_compose() {
  printf 'worker %s\n' "$*" >>"$MOCK_LOG"
  [ "${1:-}" != ps ] || printf 'worker-container\n'
}

service_start >"$FIXTURE/start.json"
jq -e '.state == "running" and .release.patch4 == true' "$FIXTURE/start.json" >/dev/null
[ -s "$SERVICE_ACTIVE_STATE" ]
qwen_line="$(grep -n '^qwen stop$' "$MOCK_LOG" | cut -d: -f1)"
worker_line="$(grep -n '^worker up -d vllm-dspark$' "$MOCK_LOG" | cut -d: -f1)"
head_line="$(grep -n '^head up -d vllm-dspark$' "$MOCK_LOG" | cut -d: -f1)"
[ "$qwen_line" -lt "$worker_line" ]
[ "$worker_line" -lt "$head_line" ]

rm -f "$SERVICE_ACTIVE_STATE"
: >"$MOCK_LOG"
wait_ready() { FAILURE_REASON="readiness failed"; return 1; }
restore_services() { printf 'rollback\n' >>"$MOCK_LOG"; }
if (service_start >/dev/null 2>&1); then
  echo "readiness failure unexpectedly passed" >&2
  exit 1
fi
grep -Fxq rollback "$MOCK_LOG"

printf 'service_fake=passed fixture=%s\n' "$FIXTURE"
