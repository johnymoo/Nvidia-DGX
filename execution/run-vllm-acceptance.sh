#!/usr/bin/env bash
set -Eeuo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
DEPLOY_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
BENCHMARK_DIR="$SCRIPT_DIR/benchmarks"
COMMON_ENV="${ACCEPTANCE_COMMON_ENV:-$SCRIPT_DIR/env/common.env}"
NODE_ENV="${ACCEPTANCE_NODE_ENV:-$SCRIPT_DIR/env/node.env}"
SSH_BIN="${SSH_BIN:-ssh}"
DOCKER_BIN="${DOCKER_BIN:-docker}"
CURL_BIN="${CURL_BIN:-curl}"
JQ_BIN="${JQ_BIN:-jq}"
PYTHON_BIN="${PYTHON_BIN:-python3}"

readonly EXPECTED_HEAD_HOST="fusionxparkgb10-3e23"
readonly EXPECTED_WORKER_HOST="spark-3345"
readonly EXPECTED_KERNEL="6.17.0-1014-nvidia"
readonly EXPECTED_DRIVER="580.142"
readonly EXPECTED_REVISION="f277b3dfa718a5962bed64e69e7e640a5384ec2f"
readonly EXPECTED_IMAGE="gb10-ds4-vllm:f277b3d-nvfp4"
readonly EXPECTED_FINGERPRINT="36adbf92fe8cdd5c57609b2c5ccfa8e2fc32a340c9ee3d727be538143dda74db"
readonly EXPECTED_MODEL_DIR="DeepSeek-V4-Flash-0731"
readonly EXPECTED_API_MODEL="deepseek-v4-flash-0731"
readonly EXPECTED_QWEN_MODEL="qwen3.6-35b-fp8"
readonly EXPECTED_MANIFEST_FILES=74
readonly EXPECTED_MANIFEST_SHA="50fe8ca783b4b394a357b0a3952fcedd71d4fca56ef49c5c159e10710b790faa"
readonly EXPECTED_MODEL_BYTES=166898658872
readonly EXPECTED_CONFIG_SHA="6c8f3d2d3b48707541b88f32f22ef3f0f8a6b57d8523281e2b8d3cdb0ae9a023"
readonly EXPECTED_INDEX_SHA="98efab455cf08dfbbbaaba6f570e1bf10bf927d2b4c3c453a59c2f6f0e3be92b"
readonly EXPECTED_SHARD_001_SHA="f3668ba4cccf1ca6a7eb84e888fb92c1cdc7204d472ba9db771e6fd3abf6b874"
readonly EXPECTED_SHARD_024_SHA="fc27aeb4233534f6f7781dcfe57127a3908ae10fc025c5d86dc0682057f8b2fe"
readonly EXPECTED_SHARD_048_SHA="cc43742bd24ae6bcdea343a91442f6f66aed2cfebcc6b235470204851ce2f8a9"
readonly COMPOSE_PROJECT="gb10-deepseek-v4"
readonly COMPOSE_SERVICE="vllm-dspark"
readonly QWEN_CONTAINER="vllm-qwen36-nvfp4-nightly-aarch64"
readonly PDF_CONTAINER="pdf2md-api"
readonly TRADING_CONTAINER="tradingagents-ashare"
readonly LEXDATA_CONTAINER="lexdata-ai"
readonly API_BASE="http://127.0.0.1:8890"
readonly QWEN_BASE="http://127.0.0.1:8004"
readonly COMPOSE_OVERRIDE_FILE="$SCRIPT_DIR/docker-compose.f277b3d-timeout.yml"

MODE=""
TEST_MODE="${ACCEPTANCE_TEST_MODE:-0}"
READINESS_TIMEOUT=3600
QWEN_TIMEOUT=900
SOAK_MINUTES=40
POLL_SECONDS=10
CHECK_TIMEOUT_SECONDS="${ACCEPTANCE_CHECK_TIMEOUT_SECONDS:-300}"
KEEP_QWEN_STOPPED_ON_FAILURE="${ACCEPTANCE_KEEP_QWEN_STOPPED_ON_FAILURE:-0}"
RESTORE_QWEN_ON_SUCCESS="${ACCEPTANCE_RESTORE_QWEN_ON_SUCCESS:-0}"
PRESERVE_DEEPSEEK_CONTAINERS="${ACCEPTANCE_PRESERVE_DEEPSEEK_CONTAINERS:-1}"
SKIP_PRESTART_CHECK="${ACCEPTANCE_SKIP_PRESTART_CHECK:-0}"
if [ "$TEST_MODE" = "1" ]; then
  READINESS_TIMEOUT="${ACCEPTANCE_TEST_READINESS_TIMEOUT:-2}"
  QWEN_TIMEOUT="${ACCEPTANCE_TEST_QWEN_TIMEOUT:-2}"
  SOAK_MINUTES="${ACCEPTANCE_TEST_SOAK_MINUTES:-0.001}"
  POLL_SECONDS=0.1
fi

RUN_ID=""
RUN_START_ISO=""
ARTIFACT_DIR=""
WORKER_ARTIFACT_DIR=""
STATUS="failed"
FAILURE_REASON=""
ROLLBACK_STATUS="not-required"
QWEN_WAS_RUNNING=0
QWEN_STOPPED=0
QWEN_RESTORE_ATTEMPTED=0
QWEN_RESTORED=0
QWEN_RESTORE_DEFERRED=0
QWEN_CONTRACT_CAPTURED=0
DEEPSEEK_TOUCHED=0
DEEPSEEK_STOPPED=0
SERVICE_STATE_CAPTURED=0
CLEANUP_DONE=0
MONITOR_PID=""
MONITOR_STOP_FILE=""
HEAD_CONTAINER_ID=""
WORKER_CONTAINER_ID=""
HEAD_FABRIC_ERRORS=0
WORKER_FABRIC_ERRORS=0
PDF_WAS_RUNNING=0
TRADING_WAS_RUNNING=0
LEXDATA_STATUS_BEFORE="not-captured"
PDF_STATUS_AFTER="not-captured"
TRADING_STATUS_AFTER="not-captured"
LEXDATA_STATUS_AFTER="not-captured"
RUNTIME_DIAGNOSTICS_CAPTURED=0
HEAD_LOG_PID=""
WORKER_LOG_PID=""
MAIN_PID="${BASHPID:-$$}"
NVRM_WARNING_REPORTED=0

usage() {
  echo "Usage: $0 {--check|--run}" >&2
}

log() {
  printf '[%s] %s\n' "$(date -u +%Y-%m-%dT%H:%M:%SZ)" "$*"
}

die() {
  echo "ERROR: $*" >&2
  return 1
}

require_command() {
  command -v "$1" >/dev/null 2>&1 || die "missing command: $1"
}

safe_value() {
  [[ "$1" =~ ^[A-Za-z0-9_./@:-]+$ ]]
}

load_env() {
  [ -f "$COMMON_ENV" ] || die "missing common env: $COMMON_ENV"
  [ -f "$NODE_ENV" ] || die "missing node env: $NODE_ENV"
  set -a
  # shellcheck disable=SC1090
  source "$COMMON_ENV"
  # shellcheck disable=SC1090
  source "$NODE_ENV"
  set +a
  : "${WORKER_SSH:?WORKER_SSH is required in head env}"
  : "${WORKER_DEPLOY_ROOT:?WORKER_DEPLOY_ROOT is required in head env}"
  : "${WORKER_MODEL_ROOT:?WORKER_MODEL_ROOT is required in head env}"
  : "${MODEL_ROOT:?MODEL_ROOT is required}"
  : "${DSPARK_MODEL:?DSPARK_MODEL is required}"
  : "${DSPARK_VLLM_IMAGE:?DSPARK_VLLM_IMAGE is required}"
  : "${FABRIC_IFNAME:?FABRIC_IFNAME is required}"
  : "${NCCL_IB_HCA:?NCCL_IB_HCA is required}"
  safe_value "$WORKER_SSH" || die "unsafe WORKER_SSH"
  safe_value "$WORKER_DEPLOY_ROOT" || die "unsafe WORKER_DEPLOY_ROOT"
  [ "$ROLE" = "head" ] || die "run from the head env only"
  [ "$NODE_RANK" = "0" ] || die "head NODE_RANK must be 0"
  [ "$(basename "$DSPARK_MODEL")" = "$EXPECTED_MODEL_DIR" ] || die "unexpected model: $DSPARK_MODEL"
  [ "$DSPARK_VLLM_IMAGE" = "$EXPECTED_IMAGE" ] || die "unexpected image: $DSPARK_VLLM_IMAGE"
  [ "$KEEP_QWEN_STOPPED_ON_FAILURE" = "0" ] || [ "$KEEP_QWEN_STOPPED_ON_FAILURE" = "1" ] || die "ACCEPTANCE_KEEP_QWEN_STOPPED_ON_FAILURE must be 0 or 1"
  [ "$RESTORE_QWEN_ON_SUCCESS" = "0" ] || [ "$RESTORE_QWEN_ON_SUCCESS" = "1" ] || die "ACCEPTANCE_RESTORE_QWEN_ON_SUCCESS must be 0 or 1"
  [ "$PRESERVE_DEEPSEEK_CONTAINERS" = "0" ] || [ "$PRESERVE_DEEPSEEK_CONTAINERS" = "1" ] || die "ACCEPTANCE_PRESERVE_DEEPSEEK_CONTAINERS must be 0 or 1"
  [ "$SKIP_PRESTART_CHECK" = "0" ] || [ "$SKIP_PRESTART_CHECK" = "1" ] || die "ACCEPTANCE_SKIP_PRESTART_CHECK must be 0 or 1"
}

remote() {
  "$SSH_BIN" -o BatchMode=yes -o ConnectTimeout=15 "$WORKER_SSH" "$@"
}

head_compose() {
  NCCL_DEBUG=INFO "$DOCKER_BIN" compose \
    --env-file "$COMMON_ENV" --env-file "$NODE_ENV" \
    -f "$SCRIPT_DIR/docker-compose.yml" -f "$COMPOSE_OVERRIDE_FILE" -p "$COMPOSE_PROJECT" "$@"
}

worker_compose() {
  local command_string
  printf -v command_string 'cd %q && NCCL_DEBUG=INFO docker compose --env-file execution/env/common.env --env-file execution/env/node.env -f execution/docker-compose.yml -f execution/docker-compose.f277b3d-timeout.yml -p %q' \
    "$WORKER_DEPLOY_ROOT" "$COMPOSE_PROJECT"
  local argument
  for argument in "$@"; do
    printf -v command_string '%s %q' "$command_string" "$argument"
  done
  remote "$command_string"
}

image_fingerprint() {
  "$DOCKER_BIN" image inspect "$1" \
    | "$JQ_BIN" -S -c '.[0] | {Architecture,Os,Created,Author,Config,RootFS,History}' \
    | sha256sum | awk '{print $1}'
}

remote_image_fingerprint() {
  remote "docker image inspect '$1'" \
    | "$JQ_BIN" -S -c '.[0] | {Architecture,Os,Created,Author,Config,RootFS,History}' \
    | sha256sum | awk '{print $1}'
}

port_free() {
  local port="$1"
  ! ss -ltnH | awk -v port=":$port" '$4 ~ (port "$") { found=1 } END { exit !found }'
}

worker_port_free() {
  local port="$1"
  remote "! ss -ltnH | awk -v port=':$port' '\$4 ~ (port \"\$\") { found=1 } END { exit !found }'"
}

container_running() {
  [ "$("$DOCKER_BIN" inspect -f '{{.State.Running}}' "$1" 2>/dev/null || true)" = "true" ]
}

container_health() {
  "$DOCKER_BIN" inspect -f '{{if .State.Health}}{{.State.Health.Status}}{{else}}{{.State.Status}}{{end}}' "$1" 2>/dev/null || printf absent
}

assert_rendered_config() {
  local config="$1" role="$2"
  "$JQ_BIN" -e --arg role "$role" '
    .services["vllm-dspark"] as $s
    | ($s.command | join(" ")) as $c
    | $s.image == "gb10-ds4-vllm:f277b3d-nvfp4"
      and $s.environment.NCCL_NET == "IB"
      and $s.environment.NCCL_IB_DISABLE == "0"
      and $s.environment.NCCL_IB_GID_INDEX == "3"
      and $s.environment.NCCL_DEBUG == "INFO"
      and $s.environment.VLLM_ENGINE_READY_TIMEOUT_S == "3600"
      and $s.environment.PYTHONUNBUFFERED == "1"
      and $s.environment.VLLM_MEMORY_PROFILER_ESTIMATE_CUDAGRAPHS == "0"
      and $s.environment.MTP_NUM_TOKENS == "5"
      and $s.environment.NODE_RANK == (if $role == "head" then "0" else "1" end)
      and ($c | contains("DeepSeek-V4-Flash-0731"))
      and ($c | contains("--tensor-parallel-size 2"))
      and ($c | contains("--nnodes 2"))
      and ($c | contains("--max-model-len 1048576"))
      and ($c | contains("--max-num-seqs 6"))
      and ($c | contains("--max-num-batched-tokens 8192"))
      and ($c | contains("--gpu-memory-utilization 0.78"))
      and ($c | contains("--kv-cache-dtype nvfp4_ds_mla"))
      and ($c | contains("--speculative-config"))
  ' <<<"$config" >/dev/null
}

check_manifest() {
  local manifest="$DEPLOY_ROOT/artifacts/$EXPECTED_MODEL_DIR.sha256" model_dir files bytes manifest_sha worker_manifest_sha
  model_dir="$MODEL_ROOT/$EXPECTED_MODEL_DIR"
  [ -s "$manifest" ] || die "missing model manifest: $manifest"
  [ "$(timeout --foreground "$CHECK_TIMEOUT_SECONDS" wc -l <"$manifest" | tr -d ' ')" = "$EXPECTED_MANIFEST_FILES" ] || die "manifest is not $EXPECTED_MANIFEST_FILES files"
  manifest_sha="$(timeout --foreground "$CHECK_TIMEOUT_SECONDS" sha256sum "$manifest" | awk '{print $1}')"
  [ "$manifest_sha" = "$EXPECTED_MANIFEST_SHA" ] || die "head manifest SHA mismatch: $manifest_sha"
  read -r files bytes < <(
    timeout --foreground "$CHECK_TIMEOUT_SECONDS" find "$model_dir" -type f ! -name .msc ! -name .mv -printf '%s\n' \
      | awk '{bytes += $1; files++} END {printf "%d %d\n", files, bytes}'
  )
  [ "$files" = "$EXPECTED_MANIFEST_FILES" ] || die "head model file count mismatch: $files"
  [ "$bytes" = "$EXPECTED_MODEL_BYTES" ] || die "head model byte count mismatch: $bytes"
  printf '%s  %s\n' "$EXPECTED_CONFIG_SHA" "$model_dir/config.json" \
    | timeout --foreground "$CHECK_TIMEOUT_SECONDS" sha256sum --check --status || die "head config.json SHA mismatch"
  printf '%s  %s\n' "$EXPECTED_INDEX_SHA" "$model_dir/model.safetensors.index.json" \
    | timeout --foreground "$CHECK_TIMEOUT_SECONDS" sha256sum --check --status || die "head model index SHA mismatch"
  printf '%s  %s\n%s  %s\n%s  %s\n' \
    "$EXPECTED_SHARD_001_SHA" "$model_dir/model-00001-of-00048.safetensors" \
    "$EXPECTED_SHARD_024_SHA" "$model_dir/model-00024-of-00048.safetensors" \
    "$EXPECTED_SHARD_048_SHA" "$model_dir/model-00048-of-00048.safetensors" \
    | timeout --foreground "$CHECK_TIMEOUT_SECONDS" sha256sum --check --status || die "head fixed shard sample SHA mismatch"
  worker_manifest_sha="$(remote bash -s -- \
    "$WORKER_MODEL_ROOT/$EXPECTED_MODEL_DIR" \
    "$WORKER_DEPLOY_ROOT/artifacts/$EXPECTED_MODEL_DIR.sha256" \
    "$EXPECTED_MANIFEST_FILES" "$EXPECTED_MANIFEST_SHA" "$EXPECTED_MODEL_BYTES" \
    "$EXPECTED_CONFIG_SHA" "$EXPECTED_INDEX_SHA" \
    "$EXPECTED_SHARD_001_SHA" "$EXPECTED_SHARD_024_SHA" "$EXPECTED_SHARD_048_SHA" "$CHECK_TIMEOUT_SECONDS" <<'REMOTE_MANIFEST_CHECK'
set -euo pipefail
model_dir="$1"; manifest="$2"; expected_files="$3"; expected_manifest="$4"; expected_bytes="$5"
config_sha="$6"; index_sha="$7"; shard1_sha="$8"; shard24_sha="$9"; shard48_sha="${10}"; timeout_seconds="${11}"
[ -s "$manifest" ]
[ "$(timeout --foreground "$timeout_seconds" wc -l <"$manifest" | tr -d ' ')" = "$expected_files" ]
manifest_sha="$(timeout --foreground "$timeout_seconds" sha256sum "$manifest" | awk '{print $1}')"
[ "$manifest_sha" = "$expected_manifest" ]
read -r files bytes < <(timeout --foreground "$timeout_seconds" find "$model_dir" -type f ! -name .msc ! -name .mv -printf '%s\n' | awk '{bytes += $1; files++} END {printf "%d %d\n", files, bytes}')
[ "$files" = "$expected_files" ]
[ "$bytes" = "$expected_bytes" ]
printf '%s  %s\n' "$config_sha" "$model_dir/config.json" | timeout --foreground "$timeout_seconds" sha256sum --check --status
printf '%s  %s\n' "$index_sha" "$model_dir/model.safetensors.index.json" | timeout --foreground "$timeout_seconds" sha256sum --check --status
printf '%s  %s\n%s  %s\n%s  %s\n' \
  "$shard1_sha" "$model_dir/model-00001-of-00048.safetensors" \
  "$shard24_sha" "$model_dir/model-00024-of-00048.safetensors" \
  "$shard48_sha" "$model_dir/model-00048-of-00048.safetensors" \
  | timeout --foreground "$timeout_seconds" sha256sum --check --status
printf '%s\n' "$manifest_sha"
REMOTE_MANIFEST_CHECK
  )"
  [ "$worker_manifest_sha" = "$manifest_sha" ] || die "two-host manifest SHA mismatch: head=$manifest_sha worker=$worker_manifest_sha"
}

check_images() {
  local local_revision worker_revision local_fingerprint worker_fingerprint
  local_revision="$("$DOCKER_BIN" image inspect "$EXPECTED_IMAGE" --format '{{index .Config.Labels "org.opencontainers.image.revision"}}')"
  worker_revision="$(remote "docker image inspect '$EXPECTED_IMAGE' --format '{{index .Config.Labels \"org.opencontainers.image.revision\"}}'")"
  [ "$local_revision" = "$EXPECTED_REVISION" ] || die "head image revision mismatch: $local_revision"
  [ "$worker_revision" = "$EXPECTED_REVISION" ] || die "worker image revision mismatch: $worker_revision"
  local_fingerprint="$(image_fingerprint "$EXPECTED_IMAGE")"
  worker_fingerprint="$(remote_image_fingerprint "$EXPECTED_IMAGE")"
  [ "$local_fingerprint" = "$EXPECTED_FINGERPRINT" ] || die "head image fingerprint mismatch: $local_fingerprint"
  [ "$worker_fingerprint" = "$EXPECTED_FINGERPRINT" ] || die "worker image fingerprint mismatch: $worker_fingerprint"
}

check_qwen_contract() {
  local contract running model_ids
  contract="$("$DOCKER_BIN" inspect "$QWEN_CONTAINER" | "$JQ_BIN" -c '.[0] | {
    name:(.Name|ltrimstr("/")), running:.State.Running,
    project:.Config.Labels["com.docker.compose.project"],
    service:.Config.Labels["com.docker.compose.service"],
    config_files:.Config.Labels["com.docker.compose.project.config_files"],
    working_dir:.Config.Labels["com.docker.compose.project.working_dir"]
  }' 2>/dev/null || true)"
  [ -n "$contract" ] || die "Qwen container/restore contract is missing"
  "$JQ_BIN" -e '.project and .service and .config_files and .working_dir' <<<"$contract" >/dev/null
  running="$("$JQ_BIN" -r '.running' <<<"$contract")"
  if [ "$running" = "true" ]; then
    [ "$(container_health "$QWEN_CONTAINER")" = "healthy" ] || die "running Qwen is not healthy"
    "$CURL_BIN" -fsS --max-time 15 "$QWEN_BASE/health" >/dev/null
    model_ids="$("$CURL_BIN" -fsS --max-time 15 "$QWEN_BASE/v1/models" | "$JQ_BIN" -r '.data[].id')"
    grep -Fxq "$EXPECTED_QWEN_MODEL" <<<"$model_ids" || die "Qwen model identity mismatch"
  fi
  printf '%s\n' "$contract"
}

run_host_preflights() {
  "$SCRIPT_DIR/preflight.sh" "$COMMON_ENV" "$NODE_ENV" >/dev/null
  remote "cd '$WORKER_DEPLOY_ROOT' && bash execution/preflight.sh execution/env/common.env execution/env/node.env >/dev/null"
}

check_runtime_sources() {
  "$SCRIPT_DIR/build-runtime.sh" --check >/dev/null
  remote "cd '$WORKER_DEPLOY_ROOT' && bash execution/build-runtime.sh --check >/dev/null"
}

head_rendered_config() {
  NCCL_DEBUG=INFO "$DOCKER_BIN" compose --env-file "$COMMON_ENV" --env-file "$NODE_ENV" \
    -f "$SCRIPT_DIR/docker-compose.yml" -f "$COMPOSE_OVERRIDE_FILE" -p "$COMPOSE_PROJECT" config --format json
}

worker_rendered_config() {
  remote "cd '$WORKER_DEPLOY_ROOT' && NCCL_DEBUG=INFO docker compose --env-file execution/env/common.env --env-file execution/env/node.env -f execution/docker-compose.yml -f execution/docker-compose.f277b3d-timeout.yml -p '$COMPOSE_PROJECT' config --format json"
}

run_checks() {
  local head_host worker_host driver head_config worker_config
  for command in "$SSH_BIN" "$DOCKER_BIN" "$CURL_BIN" "$JQ_BIN" "$PYTHON_BIN" awk date find grep sha256sum ss timeout; do
    require_command "$command"
  done
  load_env
  log "check: host identity and aligned stack" >&2
  head_host="$(hostname -s)"
  worker_host="$(remote 'hostname -s')"
  if [ "$TEST_MODE" != "1" ]; then
    [ "$DEPLOY_ROOT" = "/home/chriswang/gb10-ds4" ] || die "must run from /home/chriswang/gb10-ds4"
    [ "$head_host" = "$EXPECTED_HEAD_HOST" ] || die "unexpected head host: $head_host"
    [ "$worker_host" = "$EXPECTED_WORKER_HOST" ] || die "unexpected worker host: $worker_host"
  fi
  [ "$(uname -r)" = "$EXPECTED_KERNEL" ] || die "head kernel mismatch"
  [ "$(remote 'uname -r')" = "$EXPECTED_KERNEL" ] || die "worker kernel mismatch"
  driver="$(nvidia-smi --query-gpu=driver_version --format=csv,noheader | head -1)"
  [ "$driver" = "$EXPECTED_DRIVER" ] || die "head driver mismatch"
  [ "$(remote "nvidia-smi --query-gpu=driver_version --format=csv,noheader | head -1")" = "$EXPECTED_DRIVER" ] || die "worker driver mismatch"
  run_host_preflights || die "two-host preflight failed"
  log "check: pinned runtime source and Patch 4" >&2
  check_runtime_sources || die "runtime source verification failed"
  log "check: prior full-manifest evidence plus light two-host identity samples" >&2
  check_manifest
  log "check: image revision and normalized fingerprint" >&2
  check_images
  log "check: exact NCCL INFO Compose render" >&2
  head_config="$(head_rendered_config)"
  worker_config="$(worker_rendered_config)"
  assert_rendered_config "$head_config" head || die "head Compose render contract mismatch"
  assert_rendered_config "$worker_config" worker || die "worker Compose render contract mismatch"
  log "check: free ports, stopped DeepSeek, Qwen and Lexdata contracts" >&2
  port_free 8890 || die "head port 8890 is occupied"
  port_free 29510 || die "head port 29510 is occupied"
  worker_port_free 29510 || die "worker port 29510 is occupied"
  ! head_compose ps --status running -q "$COMPOSE_SERVICE" | grep -q . || die "head DeepSeek service is already running"
  ! worker_compose ps --status running -q "$COMPOSE_SERVICE" | grep -q . || die "worker DeepSeek service is already running"
  check_qwen_contract >/dev/null
  [ "$(remote "docker inspect -f '{{if .State.Health}}{{.State.Health.Status}}{{else}}{{.State.Status}}{{end}}' '$LEXDATA_CONTAINER'")" = "healthy" ] || die "worker lexdata-ai is not healthy"
  "$JQ_BIN" -n \
    --arg mode check --arg head "$head_host" --arg worker "$worker_host" \
    --arg revision "$EXPECTED_REVISION" --arg image "$EXPECTED_IMAGE" \
    --arg fingerprint "$EXPECTED_FINGERPRINT" --arg model "$EXPECTED_API_MODEL" \
    '{status:"passed", mode:$mode, mutation:false, head:$head, worker:$worker,
      revision:$revision, image:$image, fingerprint:$fingerprint, model:$model,
      manifest_files:74, manifest_sha256:"50fe8ca783b4b394a357b0a3952fcedd71d4fca56ef49c5c159e10710b790faa",
      model_bytes:166898658872, manifest_strategy:"2026-08-10 full evidence + config/index + fixed shards 1/24/48",
      prior_full_evidence:{head:"/home/chriswang/gb10-ds4/artifacts/DeepSeek-V4-Flash-0731.sha256",worker:"/home/admin/gb10-ds4/artifacts/DeepSeek-V4-Flash-0731.sha256"},
      readiness_timeout_seconds:3600, formal_soak_minutes:40,
      planned_sequence:["capture-baseline","stop-qwen-if-running","worker-up","head-up","readiness-and-monitor","correctness","bench-full","soak","capture-final","stop-deepseek","restore-qwen"]}'
}

capture_host_snapshot() {
  local phase="$1" destination="$2"
  mkdir -p "$destination"
  "$DOCKER_BIN" ps -a --no-trunc >"$destination/docker-ps.txt"
  "$DOCKER_BIN" image inspect "$EXPECTED_IMAGE" >"$destination/image-inspect.json"
  free -b >"$destination/free.txt"
  grep -E '^(pswpin|pswpout) ' /proc/vmstat >"$destination/vmstat-swap.txt"
  nvidia-smi -q >"$destination/nvidia-smi-q.txt"
  journalctl -k --since '-2 hours' --no-pager 2>&1 | grep -Ei 'NVRM: Xid|oom-kill|Out of memory|mlx5.*(fatal|error)' >"$destination/journal-xid-oom.txt" || true
  ip -s link show dev "$FABRIC_IFNAME" >"$destination/fabric-link.txt"
  rdma link show >"$destination/rdma-link.txt"
  for counter in /sys/class/infiniband/"$NCCL_IB_HCA"/ports/1/counters/*; do
    [ -r "$counter" ] && printf '%s=%s\n' "$(basename "$counter")" "$(cat "$counter")"
  done >"$destination/fabric-counters.txt"
  find /etc/apt/sources.list /etc/apt/sources.list.d -maxdepth 1 -type f -print0 2>/dev/null | sort -z | xargs -0 -r sha256sum >"$destination/apt-source-sha256.txt"
  sha256sum "$SCRIPT_DIR/run-vllm-acceptance.sh" "$SCRIPT_DIR/docker-compose.yml" "$COMPOSE_OVERRIDE_FILE" "$SCRIPT_DIR/preflight.sh" "$COMMON_ENV" "$NODE_ENV" "$BENCHMARK_DIR"/*.py >"$destination/project-sha256.txt"
  sha256sum "$DEPLOY_ROOT/artifacts/$EXPECTED_MODEL_DIR.sha256" >"$destination/prior-full-manifest-reference.txt"
  printf 'phase=%s\ncaptured_at=%s\n' "$phase" "$(date -u +%Y-%m-%dT%H:%M:%SZ)" >"$destination/capture.txt"
}

capture_worker_snapshot() {
  local phase="$1" destination="$2"
  remote bash -s -- "$phase" "$destination" "$WORKER_DEPLOY_ROOT" "$EXPECTED_IMAGE" "$FABRIC_IFNAME" "$NCCL_IB_HCA" <<'REMOTE_CAPTURE'
set -euo pipefail
phase="$1"; destination="$2"; deploy_root="$3"; image="$4"; fabric="$5"; hca="$6"
mkdir -p "$destination"
docker ps -a --no-trunc >"$destination/docker-ps.txt"
docker image inspect "$image" >"$destination/image-inspect.json"
free -b >"$destination/free.txt"
grep -E '^(pswpin|pswpout) ' /proc/vmstat >"$destination/vmstat-swap.txt"
nvidia-smi -q >"$destination/nvidia-smi-q.txt"
journalctl -k --since '-2 hours' --no-pager 2>&1 | grep -Ei 'NVRM: Xid|oom-kill|Out of memory|mlx5.*(fatal|error)' >"$destination/journal-xid-oom.txt" || true
ip -s link show dev "$fabric" >"$destination/fabric-link.txt"
rdma link show >"$destination/rdma-link.txt"
for counter in /sys/class/infiniband/"$hca"/ports/1/counters/*; do
  [ -r "$counter" ] && printf '%s=%s\n' "$(basename "$counter")" "$(cat "$counter")"
done >"$destination/fabric-counters.txt"
find /etc/apt/sources.list /etc/apt/sources.list.d -maxdepth 1 -type f -print0 2>/dev/null | sort -z | xargs -0 -r sha256sum >"$destination/apt-source-sha256.txt"
sha256sum "$deploy_root/execution/run-vllm-acceptance.sh" "$deploy_root/execution/docker-compose.yml" "$deploy_root/execution/docker-compose.f277b3d-timeout.yml" "$deploy_root/execution/preflight.sh" "$deploy_root/execution/env/common.env" "$deploy_root/execution/env/node.env" "$deploy_root"/execution/benchmarks/*.py >"$destination/project-sha256.txt"
sha256sum "$deploy_root/artifacts/DeepSeek-V4-Flash-0731.sha256" >"$destination/prior-full-manifest-reference.txt"
printf 'phase=%s\ncaptured_at=%s\n' "$phase" "$(date -u +%Y-%m-%dT%H:%M:%SZ)" >"$destination/capture.txt"
REMOTE_CAPTURE
}

fabric_error_sum() {
  local sum=0 value counter
  for counter in port_rcv_errors port_xmit_discards link_downed link_error_recovery symbol_error; do
    value="$(cat "/sys/class/infiniband/$NCCL_IB_HCA/ports/1/counters/$counter" 2>/dev/null || printf 0)"
    sum=$((sum + value))
  done
  printf '%s\n' "$sum"
}

worker_fabric_error_sum() {
  remote "sum=0; for name in port_rcv_errors port_xmit_discards link_downed link_error_recovery symbol_error; do file='/sys/class/infiniband/$NCCL_IB_HCA/ports/1/counters/'\"\$name\"; value=0; [ ! -r \"\$file\" ] || value=\$(cat \"\$file\"); sum=\$((sum + value)); done; printf '%s\\n' \"\$sum\""
}

runtime_safety_check() {
  local head_errors worker_errors
  container_running "$HEAD_CONTAINER_ID" || { echo "runtime safety failed: head container is not running" >&2; return 1; }
  [ "$(remote "docker inspect -f '{{.State.Running}}' '$WORKER_CONTAINER_ID'")" = "true" ] || { echo "runtime safety failed: worker container is not running" >&2; return 1; }
  ! swapon --show --noheadings | grep -q . || { echo "runtime safety failed: head swap is active" >&2; return 1; }
  remote "! swapon --show --noheadings | grep -q ." || { echo "runtime safety failed: worker swap is active" >&2; return 1; }
  rdma link show | grep -F "$FABRIC_IFNAME" | grep -Fq 'state ACTIVE' || { echo "runtime safety failed: head RDMA is inactive" >&2; return 1; }
  remote "rdma link show | grep -F '$FABRIC_IFNAME' | grep -Fq 'state ACTIVE'" || { echo "runtime safety failed: worker RDMA is inactive" >&2; return 1; }
  head_errors="$(fabric_error_sum)"
  worker_errors="$(worker_fabric_error_sum)"
  [ "$head_errors" -le "$HEAD_FABRIC_ERRORS" ] || { echo "runtime safety failed: head fabric errors rose $HEAD_FABRIC_ERRORS->$head_errors" >&2; return 1; }
  [ "$worker_errors" -le "$WORKER_FABRIC_ERRORS" ] || { echo "runtime safety failed: worker fabric errors rose $WORKER_FABRIC_ERRORS->$worker_errors" >&2; return 1; }
  if [ "$NVRM_WARNING_REPORTED" -eq 0 ] && [ -n "$ARTIFACT_DIR" ]; then
    if journalctl -k --since "$RUN_START_ISO" --no-pager 2>/dev/null | grep -F 'NV_ERR_NO_MEMORY' >>"$ARTIFACT_DIR/head-nvrm-warnings.log"; then
      echo "runtime safety warning: head NVRM NV_ERR_NO_MEMORY observed; continuing while containers run" >&2
      NVRM_WARNING_REPORTED=1
    fi
    if remote "journalctl -k --since '$RUN_START_ISO' --no-pager 2>/dev/null | grep -F 'NV_ERR_NO_MEMORY'" >>"$ARTIFACT_DIR/worker-nvrm-warnings.log"; then
      echo "runtime safety warning: worker NVRM NV_ERR_NO_MEMORY observed; continuing while containers run" >&2
      NVRM_WARNING_REPORTED=1
    fi
  fi
  ! journalctl -k --since "$RUN_START_ISO" --no-pager 2>/dev/null | grep -Eiq 'NVRM: Xid|oom-kill|Out of memory: Killed process|mlx5.*(fatal|error)' || { echo "runtime safety failed: head kernel fatal pattern" >&2; return 1; }
  remote "! journalctl -k --since '$RUN_START_ISO' --no-pager 2>/dev/null | grep -Eiq 'NVRM: Xid|oom-kill|Out of memory: Killed process|mlx5.*(fatal|error)'" || { echo "runtime safety failed: worker kernel fatal pattern" >&2; return 1; }
}

monitor_loop() {
  while [ ! -e "$MONITOR_STOP_FILE" ]; do
    capture_runtime_log_tails
    if ! runtime_safety_check; then
      printf 'runtime safety monitor failed at %s\n' "$(date -u +%Y-%m-%dT%H:%M:%SZ)" >"$ARTIFACT_DIR/monitor.failure"
      kill -TERM "$MAIN_PID"
      return 1
    fi
    sleep "$POLL_SECONDS"
  done
}

start_monitor() {
  MONITOR_STOP_FILE="$ARTIFACT_DIR/monitor.stop"
  monitor_loop >>"$ARTIFACT_DIR/monitor.log" 2>&1 &
  MONITOR_PID="$!"
}

stop_monitor() {
  if [ -n "$MONITOR_PID" ]; then
    : >"$MONITOR_STOP_FILE"
    wait "$MONITOR_PID" 2>/dev/null || true
    MONITOR_PID=""
  fi
}

qwen_contract() {
  "$DOCKER_BIN" inspect "$QWEN_CONTAINER" | "$JQ_BIN" -c '.[0] | {
    name:(.Name|ltrimstr("/")), running:.State.Running,
    project:.Config.Labels["com.docker.compose.project"],
    service:.Config.Labels["com.docker.compose.service"],
    config_files:.Config.Labels["com.docker.compose.project.config_files"],
    working_dir:.Config.Labels["com.docker.compose.project.working_dir"]
  }'
}

qwen_compose() {
  local action="$1" contract project service working_dir config_files file
  local -a args files
  contract="$(cat "$ARTIFACT_DIR/qwen-contract.json")"
  project="$("$JQ_BIN" -r '.project' <<<"$contract")"
  service="$("$JQ_BIN" -r '.service' <<<"$contract")"
  working_dir="$("$JQ_BIN" -r '.working_dir' <<<"$contract")"
  config_files="$("$JQ_BIN" -r '.config_files' <<<"$contract")"
  args=(compose -p "$project")
  IFS=',' read -r -a files <<<"$config_files"
  for file in "${files[@]}"; do args+=(-f "$file"); done
  (cd "$working_dir" && "$DOCKER_BIN" "${args[@]}" "$action" "$service")
}

wait_port_free() {
  local port="$1" timeout_seconds="$2" deadline
  deadline=$((SECONDS + timeout_seconds))
  while [ "$SECONDS" -lt "$deadline" ]; do
    port_free "$port" && return 0
    sleep 1
  done
  return 1
}

wait_qwen() {
  local deadline=$((SECONDS + QWEN_TIMEOUT)) model_ids
  while [ "$SECONDS" -lt "$deadline" ]; do
    if [ "$(container_health "$QWEN_CONTAINER")" = "healthy" ] \
      && "$CURL_BIN" -fsS --max-time 10 "$QWEN_BASE/health" >/dev/null 2>&1; then
      model_ids="$("$CURL_BIN" -fsS --max-time 10 "$QWEN_BASE/v1/models" 2>/dev/null | "$JQ_BIN" -r '.data[].id' 2>/dev/null || true)"
      grep -Fxq "$EXPECTED_QWEN_MODEL" <<<"$model_ids" && return 0
    fi
    sleep 2
  done
  return 1
}

capture_runtime_log_tails() {
  "$DOCKER_BIN" logs --timestamps --tail 250 "$HEAD_CONTAINER_ID" >>"$ARTIFACT_DIR/head-vllm.live.log" 2>&1 || true
  remote "docker logs --timestamps --tail 250 '$WORKER_CONTAINER_ID'" >>"$ARTIFACT_DIR/worker-vllm.live.log" 2>&1 || true
}

start_runtime_log_capture() {
  capture_runtime_log_tails
}

stop_runtime_log_capture() {
  :
}

capture_runtime_diagnostics() {
  local ended_at
  [ "$RUNTIME_DIAGNOSTICS_CAPTURED" -eq 0 ] || return 0
  [ -n "$ARTIFACT_DIR" ] && [ -d "$ARTIFACT_DIR" ] || return 0
  ended_at="$(date -u +%Y-%m-%dT%H:%M:%SZ)"
  "$DOCKER_BIN" logs --timestamps "$HEAD_CONTAINER_ID" >"$ARTIFACT_DIR/head-vllm.final.log" 2>&1 || true
  "$DOCKER_BIN" inspect "$HEAD_CONTAINER_ID" >"$ARTIFACT_DIR/head-vllm.inspect.json" 2>&1 || true
  timeout --foreground 20 "$DOCKER_BIN" events --since "$RUN_START_ISO" --until "$ended_at" --filter "container=$HEAD_CONTAINER_ID" \
    >"$ARTIFACT_DIR/head-vllm.events.log" 2>&1 || true
  remote "docker logs --timestamps '$WORKER_CONTAINER_ID'" >"$ARTIFACT_DIR/worker-vllm.final.log" 2>&1 || true
  remote "docker inspect '$WORKER_CONTAINER_ID'" >"$ARTIFACT_DIR/worker-vllm.inspect.json" 2>&1 || true
  remote "timeout --foreground 20 docker events --since '$RUN_START_ISO' --until '$ended_at' --filter 'container=$WORKER_CONTAINER_ID'" \
    >"$ARTIFACT_DIR/worker-vllm.events.log" 2>&1 || true
  RUNTIME_DIAGNOSTICS_CAPTURED=1
}

stop_deepseek() {
  local failed=0
  if [ "$DEEPSEEK_TOUCHED" -eq 1 ]; then
    capture_runtime_diagnostics
    stop_runtime_log_capture
    head_compose stop "$COMPOSE_SERVICE" >/dev/null 2>&1 || failed=1
    worker_compose stop "$COMPOSE_SERVICE" >/dev/null 2>&1 || failed=1
    if [ "$PRESERVE_DEEPSEEK_CONTAINERS" = "0" ]; then
      head_compose rm -f "$COMPOSE_SERVICE" >/dev/null 2>&1 || failed=1
      worker_compose rm -f "$COMPOSE_SERVICE" >/dev/null 2>&1 || failed=1
    fi
    [ "$failed" -eq 0 ] && DEEPSEEK_STOPPED=1
  fi
  return "$failed"
}

restore_services() {
  local failed=0
  stop_deepseek || failed=1
  if [ "$QWEN_CONTRACT_CAPTURED" -eq 1 ] && [ "$KEEP_QWEN_STOPPED_ON_FAILURE" = "1" ] \
    && [ "$STATUS" != "passed" ] && ! container_running "$QWEN_CONTAINER"; then
    QWEN_RESTORE_DEFERRED=1
  elif [ "$QWEN_CONTRACT_CAPTURED" -eq 1 ] && [ "$STATUS" = "passed" ] \
    && [ "$RESTORE_QWEN_ON_SUCCESS" = "1" ] && ! container_running "$QWEN_CONTAINER"; then
    QWEN_RESTORE_ATTEMPTED=1
    if ! qwen_compose start >/dev/null 2>&1 || ! wait_qwen; then
      echo "!!! ROLLBACK FAILURE: Qwen failed to return healthy with $EXPECTED_QWEN_MODEL" >&2
      failed=1
    else
      QWEN_RESTORED=1
    fi
  elif [ "$QWEN_CONTRACT_CAPTURED" -eq 1 ] && [ "$QWEN_WAS_RUNNING" -eq 1 ] && [ "$QWEN_STOPPED" -eq 1 ]; then
    QWEN_RESTORE_ATTEMPTED=1
    if ! qwen_compose start >/dev/null 2>&1 || ! wait_qwen; then
      echo "!!! ROLLBACK FAILURE: Qwen failed to return healthy with $EXPECTED_QWEN_MODEL" >&2
      failed=1
    else
      QWEN_RESTORED=1
    fi
  elif [ "$QWEN_CONTRACT_CAPTURED" -eq 1 ] && [ "$QWEN_WAS_RUNNING" -eq 0 ] && container_running "$QWEN_CONTAINER"; then
    echo "!!! ROLLBACK FAILURE: Qwen was originally stopped but is now running" >&2
    failed=1
  fi
  if [ "$SERVICE_STATE_CAPTURED" -eq 1 ]; then
    PDF_STATUS_AFTER="$(container_running "$PDF_CONTAINER" && printf running || printf stopped)"
    TRADING_STATUS_AFTER="$(container_running "$TRADING_CONTAINER" && printf running || printf stopped)"
    LEXDATA_STATUS_AFTER="$(remote "docker inspect -f '{{if .State.Health}}{{.State.Health.Status}}{{else}}{{.State.Status}}{{end}}' '$LEXDATA_CONTAINER'")"
    [ "$( [ "$PDF_STATUS_AFTER" = running ] && printf 1 || printf 0)" = "$PDF_WAS_RUNNING" ] || { echo "!!! ROLLBACK FAILURE: pdf2md state changed" >&2; failed=1; }
    [ "$( [ "$TRADING_STATUS_AFTER" = running ] && printf 1 || printf 0)" = "$TRADING_WAS_RUNNING" ] || { echo "!!! ROLLBACK FAILURE: tradingagents state changed" >&2; failed=1; }
    [ "$LEXDATA_STATUS_AFTER" = "$LEXDATA_STATUS_BEFORE" ] || { echo "!!! ROLLBACK FAILURE: lexdata-ai state changed" >&2; failed=1; }
  fi
  return "$failed"
}

write_receipt() {
  local exit_code="$1" final_status="$2" ended_at receipt="$ARTIFACT_DIR/receipt.json"
  ended_at="$(date -u +%Y-%m-%dT%H:%M:%SZ)"
  "$JQ_BIN" -n \
    --arg status "$final_status" --arg failure "$FAILURE_REASON" \
    --arg run_id "$RUN_ID" --arg started "$RUN_START_ISO" --arg ended "$ended_at" \
    --arg revision "$EXPECTED_REVISION" --arg image "$EXPECTED_IMAGE" \
    --arg fingerprint "$EXPECTED_FINGERPRINT" --arg model "$EXPECTED_API_MODEL" \
    --arg head "$(hostname -s)" --arg worker "$EXPECTED_WORKER_HOST" \
    --arg artifact "$ARTIFACT_DIR" --arg worker_artifact "$WORKER_ARTIFACT_DIR" \
    --arg rollback "$ROLLBACK_STATUS" --argjson exit_code "$exit_code" \
    --argjson qwen_was_running "$QWEN_WAS_RUNNING" \
    --argjson qwen_stopped "$QWEN_STOPPED" --argjson qwen_restore_attempted "$QWEN_RESTORE_ATTEMPTED" --argjson qwen_restored "$QWEN_RESTORED" --argjson qwen_restore_deferred "$QWEN_RESTORE_DEFERRED" \
    --argjson deepseek_touched "$DEEPSEEK_TOUCHED" --argjson deepseek_stopped "$DEEPSEEK_STOPPED" --argjson runtime_diagnostics_captured "$RUNTIME_DIAGNOSTICS_CAPTURED" \
    --argjson service_state_captured "$SERVICE_STATE_CAPTURED" \
    --arg pdf_after "$PDF_STATUS_AFTER" --arg trading_after "$TRADING_STATUS_AFTER" --arg lexdata_before "$LEXDATA_STATUS_BEFORE" --arg lexdata_after "$LEXDATA_STATUS_AFTER" \
    '{schema_version:1,status:$status,failure_reason:$failure,run_id:$run_id,
      started_at:$started,ended_at:$ended,exit_code:$exit_code,
      release:{revision:$revision,image:$image,fingerprint:$fingerprint,model:$model,patch4:true},
      topology:{head:$head,worker:$worker,tp:2,nnodes:2},
      config:{max_model_len:1048576,max_num_seqs:6,max_num_batched_tokens:8192,gpu_memory_utilization:0.78,kv_cache_dtype:"nvfp4_ds_mla",mtp_tokens:5,nccl_debug:"INFO",nccl_gid_index:3},
      acceptance:{correctness:"correctness.json",agent_sanity:"agent-sanity.json",performance:"bench-full.json",soak:"soak.json",soak_minutes:40,soak_concurrency:4},
      cleanup:{rollback_status:$rollback,state_captured:($service_state_captured==1),qwen_was_running:($qwen_was_running==1),qwen_stopped:($qwen_stopped==1),qwen_restore_attempted:($qwen_restore_attempted==1),qwen_restored:($qwen_restored==1),qwen_restore_deferred:($qwen_restore_deferred==1),deepseek_stop_attempted:($deepseek_touched==1),deepseek_stopped:($deepseek_stopped==1),runtime_diagnostics_captured:($runtime_diagnostics_captured==1),pdf2md_final:$pdf_after,trading_final:$trading_after,lexdata_before:$lexdata_before,lexdata_final:$lexdata_after},
      evidence:{head:$artifact,worker:$worker_artifact,
        prior_full_manifest:{date:"2026-08-10",sha256:"50fe8ca783b4b394a357b0a3952fcedd71d4fca56ef49c5c159e10710b790faa",
          head:"/home/chriswang/gb10-ds4/artifacts/DeepSeek-V4-Flash-0731.sha256",
          worker:"/home/admin/gb10-ds4/artifacts/DeepSeek-V4-Flash-0731.sha256"}}}' >"$receipt"
  {
    printf '# Official 0731 + Patch 4 Acceptance\n\n'
    printf -- '- Status: `%s`\n' "$final_status"
    printf -- '- Run: `%s`\n' "$RUN_ID"
    printf -- '- Release: `%s` / `%s`\n' "$EXPECTED_REVISION" "$EXPECTED_FINGERPRINT"
    printf -- '- Rollback: `%s`\n' "$ROLLBACK_STATUS"
    printf -- '- Failure: `%s`\n' "${FAILURE_REASON:-none}"
    printf -- '- Head evidence: `%s`\n' "$ARTIFACT_DIR"
    printf -- '- Worker evidence: `%s`\n' "$WORKER_ARTIFACT_DIR"
  } >"$ARTIFACT_DIR/summary.md"
}

on_error() {
  local line="$1" code="$2"
  [ -n "$FAILURE_REASON" ] || FAILURE_REASON="command failed at line $line with exit $code"
  return "$code"
}

on_signal() {
  FAILURE_REASON="received signal $1"
  exit 130
}

on_exit() {
  local original_code=$? cleanup_code=0 final_code final_status
  trap - EXIT ERR INT TERM
  set +e
  stop_monitor
  if [ -n "$ARTIFACT_DIR" ] && [ -d "$ARTIFACT_DIR" ]; then
    capture_host_snapshot final "$ARTIFACT_DIR/final-head" || true
    capture_worker_snapshot final "$WORKER_ARTIFACT_DIR/final-worker" || true
  fi
  if ! restore_services; then
    cleanup_code=1
    ROLLBACK_STATUS="failed"
  elif [ "$QWEN_RESTORE_DEFERRED" -eq 1 ]; then
    ROLLBACK_STATUS="deepseek-cleaned-qwen-deferred"
  else
    ROLLBACK_STATUS="passed"
  fi
  if [ -n "$ARTIFACT_DIR" ] && [ -d "$ARTIFACT_DIR" ]; then
    capture_host_snapshot post-restore "$ARTIFACT_DIR/post-restore-head" || true
    capture_worker_snapshot post-restore "$WORKER_ARTIFACT_DIR/post-restore-worker" || true
  fi
  if [ "$original_code" -eq 0 ] && [ "$cleanup_code" -eq 0 ] && [ "$STATUS" = "passed" ]; then
    final_code=0; final_status=passed
  else
    final_code=1; final_status=failed
    [ -n "$FAILURE_REASON" ] || FAILURE_REASON="acceptance or rollback failed"
  fi
  [ -z "$ARTIFACT_DIR" ] || write_receipt "$final_code" "$final_status" || final_code=1
  CLEANUP_DONE=1
  exit "$final_code"
}

wait_ready() {
  local deadline=$((SECONDS + READINESS_TIMEOUT)) ids
  while [ "$SECONDS" -lt "$deadline" ]; do
    if ! runtime_safety_check; then
      FAILURE_REASON="runtime safety monitor check failed during readiness"
      return 1
    fi
    if "$CURL_BIN" -fsS --max-time 10 "$API_BASE/health" >/dev/null 2>&1; then
      ids="$("$CURL_BIN" -fsS --max-time 10 "$API_BASE/v1/models" 2>/dev/null | "$JQ_BIN" -r '.data[].id' 2>/dev/null || true)"
      grep -Fxq "$EXPECTED_API_MODEL" <<<"$ids" && return 0
    fi
    sleep "$POLL_SECONDS"
  done
  FAILURE_REASON="readiness timeout after ${READINESS_TIMEOUT}s"
  return 1
}

assert_runtime() {
  "$DOCKER_BIN" logs --since "$RUN_START_ISO" "$HEAD_CONTAINER_ID" >"$ARTIFACT_DIR/head-vllm.log" 2>&1
  remote "docker logs --since '$RUN_START_ISO' '$WORKER_CONTAINER_ID'" >"$ARTIFACT_DIR/worker-vllm.log" 2>&1
  grep -Eiq 'rank.?0|\[rank0\]|rank 0' "$ARTIFACT_DIR/head-vllm.log" || die "head rank 0 evidence missing"
  grep -Eiq 'rank.?1|\[rank1\]|rank 1' "$ARTIFACT_DIR/worker-vllm.log" || die "worker rank 1 evidence missing"
  grep -Eiq 'NET/IB' "$ARTIFACT_DIR/head-vllm.log" "$ARTIFACT_DIR/worker-vllm.log" || die "NCCL NET/IB evidence missing"
  ! grep -Eiq 'NET/Socket.*Using' "$ARTIFACT_DIR/head-vllm.log" "$ARTIFACT_DIR/worker-vllm.log" || die "NCCL socket fallback detected"
  if runtime_log_fatal_matches "$ARTIFACT_DIR/head-vllm.log" "$ARTIFACT_DIR/worker-vllm.log" \
    >"$ARTIFACT_DIR/runtime-fatal-matches.log"; then
    die "fatal runtime log detected"
  fi
  "$DOCKER_BIN" exec "$HEAD_CONTAINER_ID" /opt/env/bin/python -c \
    "import inspect; from vllm.v1.spec_decode import dspark; s=inspect.getsource(dspark); assert 'shared_experts.gate_up_proj' in s and '.shared_experts.w1' in s" \
    >"$ARTIFACT_DIR/patch4-head.txt"
  remote "docker exec '$WORKER_CONTAINER_ID' /opt/env/bin/python -c \"import inspect; from vllm.v1.spec_decode import dspark; s=inspect.getsource(dspark); assert 'shared_experts.gate_up_proj' in s and '.shared_experts.w1' in s\"" \
    >"$ARTIFACT_DIR/patch4-worker.txt"
}

runtime_log_fatal_matches() {
  grep -EinH 'NCCL.*(fatal|error)|CUDA.*(fatal|error)|out of memory|traceback' "$@" \
    | grep -Eiv 'ProcessGroupNCCL.*Failed to check the "should dump" flag on TCPStore'
}

run_acceptance_clients() {
  URL="$API_BASE/v1" MODEL="$EXPECTED_API_MODEL" RESULT_PATH="$ARTIFACT_DIR/correctness.json" \
    "$PYTHON_BIN" "$BENCHMARK_DIR/correctness.py" | tee "$ARTIFACT_DIR/correctness.log"
  DSPARK_BASE_URL="$API_BASE/v1" DSPARK_MODEL="$EXPECTED_API_MODEL" CONCURRENCY="1,2,4,6" \
    RESULT_PATH="$ARTIFACT_DIR/agent-sanity.json" "$PYTHON_BIN" "$BENCHMARK_DIR/agent_sanity_bench.py" \
    | tee "$ARTIFACT_DIR/agent-sanity.log"
  URL="$API_BASE/v1" MODEL="$EXPECTED_API_MODEL" TAG="$RUN_ID" RESULT_PATH="$ARTIFACT_DIR/bench-full.json" \
    "$PYTHON_BIN" "$BENCHMARK_DIR/bench_full.py" | tee "$ARTIFACT_DIR/bench-full.log"
  URL="$API_BASE/v1" MODEL="$EXPECTED_API_MODEL" TAG="$RUN_ID" CONC=4 MINUTES="$SOAK_MINUTES" \
    RESULT_PATH="$ARTIFACT_DIR/soak.json" ACCEPTANCE_TEST_MODE="$TEST_MODE" \
    "$PYTHON_BIN" "$BENCHMARK_DIR/soak.py" | tee "$ARTIFACT_DIR/soak.log"
}

run_acceptance() {
  local artifact_root contract
  if [ "$SKIP_PRESTART_CHECK" = "1" ]; then
    load_env
    log "run: prestart broad check explicitly skipped"
  else
    run_checks >/dev/null
  fi
  RUN_ID="$(date -u +%Y%m%dT%H%M%SZ)"
  RUN_START_ISO="$(date -u +%Y-%m-%dT%H:%M:%SZ)"
  artifact_root="${ACCEPTANCE_ARTIFACT_ROOT:-$DEPLOY_ROOT/artifacts/acceptance}"
  ARTIFACT_DIR="$artifact_root/$RUN_ID"
  WORKER_ARTIFACT_DIR="$WORKER_DEPLOY_ROOT/artifacts/acceptance/$RUN_ID"
  mkdir -p "$ARTIFACT_DIR"
  trap 'on_error "$LINENO" "$?"' ERR
  trap 'on_signal INT' INT
  trap 'on_signal TERM' TERM
  trap on_exit EXIT
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
    log "stopping only Qwen service"
    qwen_compose stop
    QWEN_STOPPED=1
    wait_port_free 8004 180 || die "Qwen port 8004 did not release"
  fi
  [ "$(container_running "$PDF_CONTAINER" && printf 1 || printf 0)" = "$PDF_WAS_RUNNING" ] || die "pdf2md state changed during Qwen stop"
  [ "$(container_running "$TRADING_CONTAINER" && printf 1 || printf 0)" = "$TRADING_WAS_RUNNING" ] || die "tradingagents state changed during Qwen stop"
  DEEPSEEK_TOUCHED=1
  log "starting worker DeepSeek"
  worker_compose up -d "$COMPOSE_SERVICE"
  WORKER_CONTAINER_ID="$(worker_compose ps -q "$COMPOSE_SERVICE")"
  [ -n "$WORKER_CONTAINER_ID" ] || die "worker container ID is empty"
  log "starting head DeepSeek"
  head_compose up -d "$COMPOSE_SERVICE"
  HEAD_CONTAINER_ID="$(head_compose ps -q "$COMPOSE_SERVICE")"
  [ -n "$HEAD_CONTAINER_ID" ] || die "head container ID is empty"
  start_runtime_log_capture
  HEAD_FABRIC_ERRORS="$(fabric_error_sum)"
  WORKER_FABRIC_ERRORS="$(worker_fabric_error_sum)"
  start_monitor
  wait_ready || die "$FAILURE_REASON"
  assert_runtime
  run_acceptance_clients
  STATUS=passed
  log "acceptance completed; cleanup and receipt follow"
}

main() {
  [ "$#" -eq 1 ] || { usage; return 64; }
  case "$1" in
    --check) MODE=check; run_checks ;;
    --run) MODE=run; run_acceptance ;;
    *) usage; return 64 ;;
  esac
}

if [ "${BASH_SOURCE[0]}" = "$0" ]; then
  main "$@"
fi
