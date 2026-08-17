#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)
# shellcheck source=common.sh
source "${SCRIPT_DIR}/common.sh"

mkdir -p "${MODEL_ROOT}" "${STATE_ROOT}/receipts"

download_file() {
  local name=$1 expected_size=$2 expected_sha=$3
  local output="${MODEL_ROOT}/${name}"
  local partial="${output}.partial"
  local marker="${partial}.source"
  local url="https://modelscope.cn/models/${MODEL_REPO}/resolve/${MODELSCOPE_REVISION}/${name}"

  if [[ -f "${output}" ]]; then
    [[ $(stat -c %s "${output}") == "${expected_size}" ]]
    echo "${expected_sha}  ${output}" | sha256sum --check --status
    echo "Verified existing artifact: ${output}"
    return
  fi

  if [[ -f "${partial}" ]]; then
    [[ -f "${marker}" && $(<"${marker}") == "${url}" ]] || {
      echo "Refusing to resume an unbound partial download: ${partial}" >&2
      exit 1
    }
    (( $(stat -c %s "${partial}") <= expected_size )) || exit 1
  else
    printf '%s\n' "${url}" >"${marker}"
  fi

  curl --fail --location --retry 12 --retry-all-errors --continue-at - \
    --output "${partial}" "${url}"
  [[ $(stat -c %s "${partial}") == "${expected_size}" ]]
  echo "${expected_sha}  ${partial}" | sha256sum --check --status
  mv "${partial}" "${output}"
  rm -f "${marker}"
}

download_file "${MODEL_FILE}" "${MODEL_BYTES}" "${MODEL_SHA256}"
download_file "${MMPROJ_FILE}" "${MMPROJ_BYTES}" "${MMPROJ_SHA256}"

jq -n \
  --arg repo "${MODEL_REPO}" --arg revision "${MODEL_REVISION}" \
  --arg source "ModelScope ${MODELSCOPE_REVISION}; verified against frozen object SHA-256" \
  --arg model "${MODEL_FILE}" --arg model_sha256 "${MODEL_SHA256}" --argjson model_bytes "${MODEL_BYTES}" \
  --arg mmproj "${MMPROJ_FILE}" --arg mmproj_sha256 "${MMPROJ_SHA256}" --argjson mmproj_bytes "${MMPROJ_BYTES}" \
  '{status:"verified",repo:$repo,revision:$revision,source:$source,files:[{name:$model,bytes:$model_bytes,sha256:$model_sha256},{name:$mmproj,bytes:$mmproj_bytes,sha256:$mmproj_sha256}]}' \
  >"${STATE_ROOT}/receipts/artifact-manifest.json"

echo "Artifacts downloaded and verified under ${MODEL_ROOT}"
