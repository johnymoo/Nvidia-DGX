#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)
PROJECT_DIR=$(cd -- "${SCRIPT_DIR}/.." && pwd)
ENV_FILE=${QWEN38_ENV:-${PROJECT_DIR}/config/qwen38.env}

if [[ ! -f "${ENV_FILE}" ]]; then
  echo "Missing ${ENV_FILE}; copy config/qwen38.env.example first" >&2
  exit 2
fi

# shellcheck source=/dev/null
source "${ENV_FILE}"

required=(MODEL_ROOT STATE_ROOT MODEL_REPO MODEL_REVISION MODELSCOPE_REVISION MODEL_FILE MODEL_BYTES MODEL_SHA256 MMPROJ_FILE MMPROJ_BYTES MMPROJ_SHA256 MODEL_ALIAS LLAMA_IMAGE CONTAINER_NAME PUBLISH_HOST PORT CTX_SIZE PARALLEL GPU_HEADROOM_MIB)
for name in "${required[@]}"; do
  [[ -n "${!name:-}" ]] || { echo "Missing configuration: ${name}" >&2; exit 2; }
done

PROFILE_LABEL=io.shili.qwen38-rtx3090.profile
PROFILE_ID=qwen38-rtx3090-v1
RUNTIME_ARGS=(
  --model "/models/${MODEL_FILE}"
  --mmproj "/models/${MMPROJ_FILE}"
  --alias "${MODEL_ALIAS}"
  --host 0.0.0.0 --port "${PORT}"
  --ctx-size "${CTX_SIZE}" --n-gpu-layers 999 --parallel "${PARALLEL}"
  --flash-attn on --cache-type-k q4_0 --cache-type-v q4_0
  --temp 0.7 --top-p 0.8 --top-k 20 --min-p 0.0 --presence-penalty 1.5
  --chat-template-kwargs '{"enable_thinking":false}' --metrics
)

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
  [[ ${count} -eq 1 ]] || {
    echo "This profile requires exactly one visible GPU" >&2
    return 1
  }
  compact=${rows// /}
  [[ ${compact} == NVIDIAGeForceRTX3090,24576 ]] || {
    echo "This profile requires one 24 GiB NVIDIA GeForce RTX 3090" >&2
    return 1
  }
}

verify_container() {
  local inspect expected_cmd expected_image_id model_root state_logs
  inspect=$(docker inspect "${CONTAINER_NAME}")
  expected_cmd=$(printf '%s\n' "${RUNTIME_ARGS[@]}" | jq -R . | jq -s .)
  expected_image_id=$(docker image inspect "${LLAMA_IMAGE}" --format '{{.Id}}')
  model_root=$(realpath "${MODEL_ROOT}")
  state_logs=$(realpath "${STATE_ROOT}/logs")
  jq -e \
    --arg image "${LLAMA_IMAGE}" --arg image_id "${expected_image_id}" \
    --arg label "${PROFILE_LABEL}" --arg profile "${PROFILE_ID}" \
    --arg model_root "${model_root}" --arg state_logs "${state_logs}" \
    --arg port "${PORT}" --arg host "${PUBLISH_HOST}" \
    --argjson expected_cmd "${expected_cmd}" '
      .[0] as $c |
      $c.Config.Image == $image and $c.Image == $image_id and
      $c.Config.Labels[$label] == $profile and $c.Config.Cmd == $expected_cmd and
      any($c.Mounts[]?; .Source == $model_root and .Destination == "/models" and .RW == false) and
      any($c.Mounts[]?; .Source == $state_logs and .Destination == "/logs") and
      $c.HostConfig.PortBindings[($port + "/tcp")] == [{"HostIp":$host,"HostPort":$port}] and
      any($c.HostConfig.DeviceRequests[]?; .Driver == "nvidia" and .DeviceIDs == ["0"])
    ' <<<"${inspect}" >/dev/null || {
      echo "Container identity or runtime configuration does not match this profile" >&2
      return 1
    }
}
