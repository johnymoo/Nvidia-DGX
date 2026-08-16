#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)
# shellcheck source=common.sh
source "${SCRIPT_DIR}/common.sh"

"${SCRIPT_DIR}/status.sh" >/dev/null
verify_artifacts
run_id=$(date -u +%Y%m%dT%H%M%SZ)
receipt_dir="${STATE_ROOT}/receipts/acceptance-${run_id}"
mkdir -p "${receipt_dir}"
monitor_pid=

cleanup() {
  if [[ -n "${monitor_pid}" ]]; then
    kill "${monitor_pid}" 2>/dev/null || true
    wait "${monitor_pid}" 2>/dev/null || true
  fi
}
trap cleanup EXIT INT TERM

docker inspect "${CONTAINER_NAME}" >"${receipt_dir}/container-inspect.json"
inspect_sha=$(sha256sum "${receipt_dir}/container-inspect.json" | awk '{print $1}')
nvidia-smi --query-gpu=timestamp,name,driver_version,memory.total,memory.used,memory.free --format=csv,noheader,nounits >"${receipt_dir}/gpu-before.csv"
(
  while true; do
    nvidia-smi --query-gpu=timestamp,memory.total,memory.used,memory.free --format=csv,noheader,nounits
    sleep 1
  done
) >"${receipt_dir}/gpu-monitor.csv" &
monitor_pid=$!

python3 "${SCRIPT_DIR}/acceptance.py" \
  --base-url "http://127.0.0.1:${PORT}" --model "${MODEL_ALIAS}" \
  --output "${receipt_dir}/acceptance.json"
cleanup
monitor_pid=
docker logs "${CONTAINER_NAME}" >"${receipt_dir}/container.log" 2>&1
if grep -Eiq 'CUDA error|out of memory|oom-kill|fatal|assertion|segmentation fault' "${receipt_dir}/container.log"; then
  echo "Fatal runtime pattern found in logs" >&2
  exit 1
fi
min_free=$(awk -F, '{gsub(/ /,"",$4); if ($4 ~ /^[0-9]+$/ && (min == "" || $4 < min)) min=$4} END {print min}' "${receipt_dir}/gpu-monitor.csv")
[[ -n "${min_free}" && ${min_free} -ge ${GPU_HEADROOM_MIB} ]]
image_id=$(docker image inspect "${LLAMA_IMAGE}" --format '{{.Id}}')
acceptance_sha=$(sha256sum "${receipt_dir}/acceptance.json" | awk '{print $1}')
gpu_name=$(nvidia-smi --query-gpu=name --format=csv,noheader | head -1)
gpu_memory=$(nvidia-smi --query-gpu=memory.total --format=csv,noheader,nounits | head -1 | tr -d ' ')

jq -n \
  --arg id "acceptance-${run_id}" --arg gpu "${gpu_name}" --argjson gpu_memory "${gpu_memory}" \
  --arg model_sha "${MODEL_SHA256}" --arg mmproj_sha "${MMPROJ_SHA256}" \
  --arg image "${LLAMA_IMAGE}" --arg image_id "${image_id}" --arg acceptance_sha "${acceptance_sha}" --arg inspect_sha "${inspect_sha}" \
  --argjson ctx "${CTX_SIZE}" --argjson parallel "${PARALLEL}" --argjson min_free "${min_free}" --argjson floor "${GPU_HEADROOM_MIB}" \
  --slurpfile acceptance "${receipt_dir}/acceptance.json" \
  '{schema_version:1,receipt_id:$id,status:"passed",hardware:{gpu:$gpu,gpu_memory_mib:$gpu_memory},artifacts:{model_sha256:$model_sha,mmproj_sha256:$mmproj_sha,image_ref:$image,image_id:$image_id},runtime:{ctx_size:$ctx,parallel:$parallel,flash_attention:true,kv_cache:{key:"q4_0",value:"q4_0"}},acceptance:$acceptance[0],safety:{minimum_free_gpu_mib:$min_free,required_free_gpu_mib:$floor,fatal_log_patterns_found:false},source_evidence:{acceptance_sha256:$acceptance_sha,container_inspect_sha256:$inspect_sha},current_state_claim:"service remained running after this acceptance"}' \
  >"${receipt_dir}/deployment-receipt.json"

python3 "${SCRIPT_DIR}/validate_receipt.py" "${receipt_dir}/deployment-receipt.json"
echo "PASS ${receipt_dir}/deployment-receipt.json"
