#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)
# shellcheck source=common.sh
source "${SCRIPT_DIR}/common.sh"

mkdir -p "${MODEL_ROOT}" "${STATE_ROOT}/receipts"
download_file() {
  local name=$1 expected_size=$2 expected_sha=$3 output partial url
  output="${MODEL_ROOT}/${name}"
  partial="${output}.partial"
  url="https://modelscope.cn/models/${MODEL_REPO}/resolve/${MODELSCOPE_REVISION}/${name}"
  if [[ ! -f "${output}" ]]; then
    curl --fail --location --retry 12 --retry-all-errors --continue-at - --output "${partial}" "${url}"
    mv "${partial}" "${output}"
  fi
  [[ $(stat -c %s "${output}") == "${expected_size}" ]]
  echo "${expected_sha}  ${output}" | sha256sum --check --status
  echo "Verified ${output}"
}

download_file "${MODEL_FILE}" "${MODEL_BYTES}" "${MODEL_SHA256}"
download_file "${MMPROJ_FILE}" "${MMPROJ_BYTES}" "${MMPROJ_SHA256}"
