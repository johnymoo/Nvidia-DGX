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

verify_artifacts() {
  [[ $(stat -c %s "${MODEL_ROOT}/${MODEL_FILE}") == "${MODEL_BYTES}" ]]
  [[ $(stat -c %s "${MODEL_ROOT}/${MMPROJ_FILE}") == "${MMPROJ_BYTES}" ]]
  echo "${MODEL_SHA256}  ${MODEL_ROOT}/${MODEL_FILE}" | sha256sum --check --status
  echo "${MMPROJ_SHA256}  ${MODEL_ROOT}/${MMPROJ_FILE}" | sha256sum --check --status
}
