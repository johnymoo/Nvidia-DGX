#!/usr/bin/env bash
set -euo pipefail
SCRIPT_DIR=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)
# shellcheck source=common.sh
source "${SCRIPT_DIR}/common.sh"

verify_model
verify_gpu
compose ps
curl -fsS "http://127.0.0.1:${PORT}/v1/models"
docker inspect "${CONTAINER_NAME}" --format 'memory={{.HostConfig.Memory}} swap={{.HostConfig.MemorySwap}} restart={{.HostConfig.RestartPolicy.Name}} devices={{json .HostConfig.DeviceRequests}}'
nvidia-smi --query-gpu=name,memory.total,memory.used,memory.free,utilization.gpu --format=csv,noheader

