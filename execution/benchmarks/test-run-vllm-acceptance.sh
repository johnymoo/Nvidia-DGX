#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
ACCEPTANCE_SCRIPT="$(cd "$SCRIPT_DIR/.." && pwd)/run-vllm-acceptance.sh"
FIXTURE="$(mktemp -d)"
MOCK_BIN="$FIXTURE/mock-bin"
MOCK_LOG="$FIXTURE/mock.log"
mkdir -p "$MOCK_BIN"
: >"$MOCK_LOG"

make_mock() {
  local name="$1" body="$2"
  printf '#!/usr/bin/env bash\nset -eu\nprintf "%%s %%s\\n" "%s" "$*" >>"$MOCK_LOG"\n%s\n' "$name" "$body" >"$MOCK_BIN/$name"
  chmod +x "$MOCK_BIN/$name"
}

export MOCK_LOG
make_mock ssh '
case "$*" in
  *"hostname -s"*) echo spark-3345 ;;
  *"uname -r"*) echo 6.17.0-1014-nvidia ;;
  *"nvidia-smi --query-gpu=driver_version"*) echo 580.142 ;;
  *"lexdata-ai"*) echo healthy ;;
esac'
make_mock docker ':'
make_mock curl 'printf "{\"data\":[{\"id\":\"qwen3.6-35b-fp8\"}]}\\n"'
make_mock nvidia-smi 'echo 580.142'
make_mock hostname 'echo mock-head'
make_mock uname 'echo 6.17.0-1014-nvidia'
make_mock ss ':'
make_mock timeout 'exit 124'

export PATH="$MOCK_BIN:$PATH"
export ACCEPTANCE_TEST_MODE=1
# shellcheck source=../run-vllm-acceptance.sh
source "$ACCEPTANCE_SCRIPT"

load_env() {
  WORKER_SSH=mock-worker
  WORKER_DEPLOY_ROOT=/mock/worker/gb10-ds4
  WORKER_MODEL_ROOT=/mock/worker/model
  MODEL_ROOT=/mock/head/model
  DSPARK_MODEL=/models/DeepSeek-V4-Flash-0731
  DSPARK_VLLM_IMAGE=gb10-ds4-vllm:f277b3d-nvfp4
  FABRIC_IFNAME=enp1s0f0np0
  NCCL_IB_HCA=rocep1s0f0
  ROLE=head
  NODE_RANK=0
}
run_host_preflights() { :; }
check_runtime_sources() { :; }
check_manifest() { :; }
check_images() { :; }
check_qwen_contract() { printf '%s\n' '{"running":true,"project":"qwen","service":"vllm","config_files":"/mock/compose.yml","working_dir":"/mock"}'; }
head_rendered_config() { printf '%s\n' '{}'; }
worker_rendered_config() { printf '%s\n' '{}'; }
assert_rendered_config() { :; }
port_free() { :; }
worker_port_free() { :; }

main --check >"$FIXTURE/check.json"
jq -e '.status == "passed" and .mode == "check" and .mutation == false and .formal_soak_minutes == 40' "$FIXTURE/check.json" >/dev/null
if grep -Eq ' compose (up|stop|start|rm|down)( |$)' "$MOCK_LOG"; then
  echo "mock --check attempted mutation" >&2
  exit 1
fi

: >"$MOCK_LOG"
DEEPSEEK_TOUCHED=1
QWEN_WAS_RUNNING=1
QWEN_STOPPED=1
QWEN_CONTRACT_CAPTURED=1
PDF_WAS_RUNNING=1
TRADING_WAS_RUNNING=1
head_compose() { printf 'head-compose %s\n' "$*" >>"$MOCK_LOG"; }
worker_compose() { printf 'worker-compose %s\n' "$*" >>"$MOCK_LOG"; }
qwen_compose() { printf 'qwen-compose %s\n' "$*" >>"$MOCK_LOG"; }
wait_qwen() { :; }
container_running() {
  case "$1" in
    "$PDF_CONTAINER"|"$TRADING_CONTAINER"|"$QWEN_CONTAINER") return 0 ;;
    *) return 1 ;;
  esac
}
remote() { printf 'healthy\n'; }
restore_services
grep -Fq 'head-compose stop vllm-dspark' "$MOCK_LOG"
grep -Fq 'worker-compose stop vllm-dspark' "$MOCK_LOG"
! grep -Fq 'compose rm -f vllm-dspark' "$MOCK_LOG"
grep -Fq 'qwen-compose start' "$MOCK_LOG"

 : >"$MOCK_LOG"
QWEN_RESTORE_ATTEMPTED=0
QWEN_RESTORED=0
QWEN_RESTORE_DEFERRED=0
KEEP_QWEN_STOPPED_ON_FAILURE=1
STATUS=failed
restore_services
[ "$QWEN_RESTORE_DEFERRED" -eq 1 ]
! grep -Fq 'qwen-compose start' "$MOCK_LOG"
KEEP_QWEN_STOPPED_ON_FAILURE=0

qwen_compose() { return 1; }
if restore_services 2>"$FIXTURE/rollback-failure.log"; then
  echo "rollback failure path unexpectedly passed" >&2
  exit 1
fi
grep -Fq '!!! ROLLBACK FAILURE: Qwen failed to return healthy' "$FIXTURE/rollback-failure.log"

runtime_safety_check() { :; }
CURL_BIN=false
READINESS_TIMEOUT=1
POLL_SECONDS=0.1
FAILURE_REASON=""
SECONDS=0
if wait_ready; then
  echo "readiness timeout path unexpectedly passed" >&2
  exit 1
fi
[ "$FAILURE_REASON" = 'readiness timeout after 1s' ]

port_free() { :; }
wait_port_free 8004 1
port_free() { return 1; }
if wait_port_free 8004 0; then
  echo "wait_port_free timeout path unexpectedly passed" >&2
  exit 1
fi

printf 'mock_harness=passed fixture=%s\n' "$FIXTURE"
