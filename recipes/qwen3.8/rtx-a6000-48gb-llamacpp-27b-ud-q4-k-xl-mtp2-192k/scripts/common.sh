#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)
PROJECT_DIR=$(cd -- "${SCRIPT_DIR}/.." && pwd)
ENV_FILE=${QWEN38_ENV:-${PROJECT_DIR}/config/qwen38.env}
[[ -f "${ENV_FILE}" ]] || { echo "Missing ${ENV_FILE}; copy config/qwen38.env.example first" >&2; exit 2; }
# shellcheck source=/dev/null
source "${ENV_FILE}"
required=(MODEL_ROOT STATE_ROOT MODEL_REPO MODEL_REVISION MODELSCOPE_REVISION MODEL_FILE MODEL_BYTES MODEL_SHA256 MMPROJ_FILE MMPROJ_BYTES MMPROJ_SHA256 MODEL_ALIAS MODEL_VARIANT_ALIAS LLAMA_IMAGE CONTAINER_NAME PUBLISH_HOST ALLOW_UNAUTHENTICATED_LAN PORT CTX_SIZE PARALLEL SPEC_TYPE SPEC_DRAFT_N_MAX SPEC_DRAFT_P_MIN HOST_MEMORY_LIMIT GPU_HEADROOM_MIB)
for name in "${required[@]}"; do [[ -n "${!name:-}" ]] || { echo "Missing configuration: ${name}" >&2; exit 2; }; done
if [[ "${PUBLISH_HOST}" != 127.0.0.1 && "${PUBLISH_HOST}" != localhost && "${ALLOW_UNAUTHENTICATED_LAN}" != true ]]; then
  echo "Non-loopback API binding requires ALLOW_UNAUTHENTICATED_LAN=true" >&2; exit 2
fi

PROFILE_LABEL=io.nvidia-dgx.qwen38-rtx-a6000.profile
PROFILE_ID=qwen38-rtx-a6000-ud-q4-k-xl-mtp2-192k-v1
RUNTIME_ARGS=(--model "/models/${MODEL_FILE}" --mmproj "/models/${MMPROJ_FILE}" --alias "${MODEL_ALIAS},${MODEL_VARIANT_ALIAS}" --host 0.0.0.0 --port "${PORT}" --ctx-size "${CTX_SIZE}" --n-gpu-layers 999 --parallel "${PARALLEL}" --flash-attn on --reasoning auto --reasoning-format deepseek --metrics --spec-type "${SPEC_TYPE}" --spec-draft-n-max "${SPEC_DRAFT_N_MAX}" --spec-draft-p-min "${SPEC_DRAFT_P_MIN}")

verify_artifacts() {
  [[ $(stat -c %s "${MODEL_ROOT}/${MODEL_FILE}") == "${MODEL_BYTES}" ]]
  [[ $(stat -c %s "${MODEL_ROOT}/${MMPROJ_FILE}") == "${MMPROJ_BYTES}" ]]
  echo "${MODEL_SHA256}  ${MODEL_ROOT}/${MODEL_FILE}" | sha256sum --check --status
  echo "${MMPROJ_SHA256}  ${MODEL_ROOT}/${MMPROJ_FILE}" | sha256sum --check --status
}

verify_single_gpu() {
  local rows count compact
  rows=$(nvidia-smi --query-gpu=name,memory.total --format=csv,noheader,nounits)
  count=$(printf '%s\n' "${rows}" | awk 'NF { count++ } END { print count + 0 }')
  [[ ${count} -eq 1 ]] || { echo "This profile requires exactly one visible GPU" >&2; return 1; }
  compact=${rows// /}
  [[ ${compact} == NVIDIARTXA6000,49140 ]] || { echo "This profile requires NVIDIA RTX A6000 with 49,140 MiB" >&2; return 1; }
}

verify_container() {
  local inspect expected_cmd expected_image_id model_root state_logs expected_memory_bytes
  inspect=$(docker inspect "${CONTAINER_NAME}")
  expected_cmd=$(printf '%s\n' "${RUNTIME_ARGS[@]}" | jq -R . | jq -s .)
  expected_image_id=$(docker image inspect "${LLAMA_IMAGE}" --format '{{.Id}}')
  model_root=$(realpath "${MODEL_ROOT}"); state_logs=$(realpath "${STATE_ROOT}/logs")
  expected_memory_bytes=$(numfmt --from=iec "${HOST_MEMORY_LIMIT^^}")
  jq -e --arg image "${LLAMA_IMAGE}" --arg image_id "${expected_image_id}" --arg label "${PROFILE_LABEL}" --arg profile "${PROFILE_ID}" --arg model_root "${model_root}" --arg state_logs "${state_logs}" --arg port "${PORT}" --arg host "${PUBLISH_HOST}" --argjson memory "${expected_memory_bytes}" --argjson expected_cmd "${expected_cmd}" '
    .[0] as $c | $c.Config.Image == $image and $c.Image == $image_id and
    $c.Config.Labels[$label] == $profile and $c.Config.Cmd == $expected_cmd and
    any($c.Mounts[]?; .Source == $model_root and .Destination == "/models" and .RW == false) and
    any($c.Mounts[]?; .Source == $state_logs and .Destination == "/logs") and
    $c.HostConfig.PortBindings[($port + "/tcp")] == [{"HostIp":$host,"HostPort":$port}] and
    $c.HostConfig.Memory == $memory and $c.HostConfig.MemorySwap == $memory and
    any($c.HostConfig.DeviceRequests[]?; (.Driver == "" or .Driver == "nvidia") and .DeviceIDs == ["0"] and any(.Capabilities[]?; index("gpu")))
  ' <<<"${inspect}" >/dev/null || { echo "Container identity or runtime configuration does not match this profile" >&2; return 1; }
}
