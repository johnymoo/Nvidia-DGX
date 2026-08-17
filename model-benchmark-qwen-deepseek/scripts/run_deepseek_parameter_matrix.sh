#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)
PROJECT_DIR=$(cd -- "${SCRIPT_DIR}/.." && pwd)
ENV_FILE=${DEEPSEEK_MATRIX_ENV:-${PROJECT_DIR}/../../.env}
OUTPUT_DIR=${1:-${PROJECT_DIR}/data/lakehouse-parameter-matrix}
MATRIX_REPEATS=${DEEPSEEK_MATRIX_REPEATS:-3}

[[ -f "${ENV_FILE}" ]] || {
  echo "Missing environment file: ${ENV_FILE}" >&2
  exit 2
}

set -a
# shellcheck source=/dev/null
source "${ENV_FILE}"
set +a
mkdir -p "${OUTPUT_DIR}"

[[ "${MATRIX_REPEATS}" =~ ^[1-9][0-9]*$ ]] || {
  echo "DEEPSEEK_MATRIX_REPEATS must be a positive integer" >&2
  exit 2
}

run_treatment() {
  local endpoint_kind=$1 endpoint_label=$2 base_url=$3 model=$4 api_key_env=$5 contract=$6 sampling=$7 effort=$8 max_tokens=$9 repeat=${10} stream=${11}
  local name="${endpoint_kind}-${effort}-$((${max_tokens} / 1024))k-r${repeat}"
  local output="${OUTPUT_DIR}/${name}.json"
  if [[ -s "${output}" ]]; then
    if jq -e \
      --arg tag "${name}" \
      --arg model "${model}" \
      --arg effort "${effort}" \
      --arg contract "${contract}" \
      --arg sampling "${sampling}" \
      --argjson max_tokens "${max_tokens}" \
      --argjson repeat "${repeat}" \
      --argjson expected_runs "${MATRIX_REPEATS}" \
      --argjson stream "${stream}" \
      '.harness_id == "lakehouse-thinking-v2"
       and .status == "passed"
       and .tag == $tag
       and .model == $model
       and .mode == "deepseek-thinking"
       and .repeat == $repeat
       and .expected_runs == $expected_runs
       and .max_tokens == $max_tokens
       and .request_config.deepseek_effort == $effort
       and .request_config.deepseek_contract == $contract
       and .request_config.deepseek_sampling == $sampling
       and (.request_config.stream // false) == $stream' \
      "${output}" >/dev/null; then
      echo "skip validated ${name}"
      return
    fi
    echo "Refusing to reuse incompatible or incomplete evidence: ${output}" >&2
    exit 3
  fi
  local stream_args=()
  if [[ "${stream}" == "true" ]]; then
    stream_args+=(--stream)
  fi
  python3 "${SCRIPT_DIR}/lakehouse_thinking_benchmark.py" \
    --base-url "${base_url}" \
    --endpoint-label "${endpoint_label}" \
    --model "${model}" \
    --tag "${name}" \
    --treatment "${endpoint_kind} DS / ${effort} / $((${max_tokens} / 1024))K" \
    --mode deepseek-thinking \
    --api-key-env "${api_key_env}" \
    --deepseek-contract "${contract}" \
    --deepseek-sampling "${sampling}" \
    --deepseek-effort "${effort}" \
    --max-tokens "${max_tokens}" \
    --request-timeout 14400 \
    "${stream_args[@]}" \
    --repeat "${repeat}" \
    --expected-runs "${MATRIX_REPEATS}" \
    --max-response-chars 32768 \
    --max-reasoning-chars 32768 \
    --output "${output}"
}

for repeat in $(seq 1 "${MATRIX_REPEATS}"); do
  for setting in "low 32768" "high 262144" "max 393216"; do
    read -r effort max_tokens <<<"${setting}"
    run_treatment private private-dgx-spark "${OPENAI_BASE_URL%/}" "${MODEL}" OPENAI_API_KEY private-vllm official-local-general "${effort}" "${max_tokens}" "${repeat}" false
    run_treatment online online-gateway "${DS_BASE_URL%/}/v1" "${DS_MODEL}" DS_AUTH_TOKEN online-api official-api "${effort}" "${max_tokens}" "${repeat}" true
  done
done
