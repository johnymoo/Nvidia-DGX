#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)
PROJECT_DIR=$(cd -- "${SCRIPT_DIR}/.." && pwd)
REPO_DIR=$(cd -- "${PROJECT_DIR}/.." && pwd)
HARNESS=${REPO_DIR}/model-benchmark-qwen-deepseek/scripts/lakehouse_thinking_benchmark.py
LATENCY_HARNESS=${REPO_DIR}/model-benchmark-qwen-deepseek/scripts/inference_latency_benchmark.py
OUTPUT_DIR=${1:-${PROJECT_DIR}/data/online-pro-matrix}
BASE_URL=${ONLINE_DS_BASE_URL:-https://coding.onlyservice.io/v1}
API_KEY_ENV=${ONLINE_DS_API_KEY_ENV:-CLAUDE_DS_TOKEN}
MODEL=${ONLINE_DS_PRO_MODEL:-deepseek-v4-pro}
REPEATS=${ONLINE_DS_PRO_REPEATS:-2}
PARALLEL_QUALITY=${ONLINE_DS_PRO_PARALLEL_QUALITY:-false}

[[ -f "${HARNESS}" && -f "${LATENCY_HARNESS}" ]] || {
  echo "Benchmark harnesses are missing" >&2
  exit 2
}
[[ "${REPEATS}" =~ ^[1-9][0-9]*$ ]] || {
  echo "ONLINE_DS_PRO_REPEATS must be a positive integer" >&2
  exit 2
}
[[ "${PARALLEL_QUALITY}" == false || "${PARALLEL_QUALITY}" == true ]] || {
  echo "ONLINE_DS_PRO_PARALLEL_QUALITY must be true or false" >&2
  exit 2
}
[[ -n "${!API_KEY_ENV:-}" ]] || {
  echo "Environment variable ${API_KEY_ENV} is empty" >&2
  exit 2
}
mkdir -p "${OUTPUT_DIR}" "${OUTPUT_DIR}/latency"

run_quality() {
  local effort=$1 max_tokens=$2 repeat=$3
  local tag="online-pro-${effort}-$((${max_tokens} / 1024))k-r${repeat}"
  local output="${OUTPUT_DIR}/${tag}.json"
  if [[ -s "${output}" ]] && jq -e \
    --arg tag "${tag}" --arg model "${MODEL}" --arg effort "${effort}" \
    --argjson max_tokens "${max_tokens}" --argjson repeat "${repeat}" \
    --argjson expected_runs "${REPEATS}" \
    '.harness_id == "lakehouse-thinking-v2" and .status == "passed"
     and .tag == $tag and .model == $model and .repeat == $repeat
     and .expected_runs == $expected_runs and .max_tokens == $max_tokens
     and .request_config.deepseek_contract == "online-api"
     and .request_config.deepseek_effort == $effort
     and .request_config.deepseek_sampling == "official-api"
     and .request_config.stream == true' "${output}" >/dev/null; then
    echo "skip validated ${tag}"
    return
  fi
  [[ ! -e "${output}" ]] || {
    echo "Refusing incompatible evidence: ${output}" >&2
    exit 3
  }
  python3 "${HARNESS}" \
    --base-url "${BASE_URL}" --endpoint-label online-gateway \
    --model "${MODEL}" --tag "${tag}" \
    --treatment "online Pro / ${effort} / $((${max_tokens} / 1024))K" \
    --mode deepseek-thinking --api-key-env "${API_KEY_ENV}" \
    --deepseek-contract online-api --deepseek-sampling official-api \
    --deepseek-effort "${effort}" --max-tokens "${max_tokens}" \
    --request-timeout 14400 --stream --repeat "${repeat}" \
    --expected-runs "${REPEATS}" --max-response-chars 32768 \
    --max-reasoning-chars 32768 --output "${output}"
}

if [[ "${PARALLEL_QUALITY}" == true ]]; then
  pids=()
  for repeat in $(seq 1 "${REPEATS}"); do
    run_quality low 32768 "${repeat}" & pids+=("$!")
    run_quality high 262144 "${repeat}" & pids+=("$!")
    run_quality max 393216 "${repeat}" & pids+=("$!")
  done
  failed=0
  for pid in "${pids[@]}"; do
    wait "${pid}" || failed=1
  done
  [[ "${failed}" == 0 ]] || exit 4
else
  for repeat in $(seq 1 "${REPEATS}"); do
    run_quality low 32768 "${repeat}"
    run_quality high 262144 "${repeat}"
    run_quality max 393216 "${repeat}"
  done
fi

for effort in low high max; do
  output="${OUTPUT_DIR}/latency/online-pro-${effort}.json"
  [[ ! -e "${output}" ]] || continue
  python3 "${LATENCY_HARNESS}" \
    --base-url "${BASE_URL}" --endpoint-label online-gateway \
    --model "${MODEL}" --profile "deepseek-online-${effort}" \
    --api-key-env "${API_KEY_ENV}" --max-tokens 2048 \
    --warmup 1 --runs 3 --timeout 3600 --output "${output}"
done
