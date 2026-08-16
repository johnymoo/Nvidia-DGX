#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)
# shellcheck source=common.sh
source "${SCRIPT_DIR}/common.sh"

verify_single_gpu
verify_container
container_status=$(docker inspect -f 'container={{.Name}} running={{.State.Running}} health={{.State.Health.Status}} image={{.Image}}' "${CONTAINER_NAME}")
grep -E 'running=true health=healthy' <<<"${container_status}" >/dev/null
printf '%s\n' "${container_status}"
nvidia-smi --query-gpu=name,driver_version,memory.total,memory.used,memory.free --format=csv,noheader,nounits
curl -fsS "http://127.0.0.1:${PORT}/health"
echo
curl -fsS "http://127.0.0.1:${PORT}/v1/models" | \
  jq -e --arg model "${MODEL_ALIAS}" '.data | any(.id == $model and .meta.n_params >= 26000000000 and .meta.n_params <= 28500000000)'
