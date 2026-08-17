#!/usr/bin/env bash
set -euo pipefail
SCRIPT_DIR=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)
# shellcheck source=common.sh
source "${SCRIPT_DIR}/common.sh"

verify_model
verify_gpu
mkdir -p "${VLLM_CACHE_ROOT}"
compose config >/dev/null
compose up -d
for _ in $(seq 1 180); do
  if curl -fsS "http://127.0.0.1:${PORT}/health" >/dev/null 2>&1; then
    exec "${SCRIPT_DIR}/status.sh"
  fi
  sleep 5
done
compose logs --tail 200 qwen38 >&2 || true
exit 1
