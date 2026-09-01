#!/usr/bin/env bash
set -euo pipefail
SCRIPT_DIR=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)
# shellcheck source=common.sh
source "${SCRIPT_DIR}/common.sh"
OUTPUT_ROOT=${1:-${STATE_ROOT}/receipts/benchmark-$(date -u +%Y%m%dT%H%M%SZ)}
HARNESS_ROOT=${PROJECT_DIR}/../../../benchmarks/legacy/qwen-deepseek-cross-model
mkdir -p "${OUTPUT_ROOT}"
python3 "${HARNESS_ROOT}/scripts/inference_latency_benchmark.py" \
  --base-url "http://127.0.0.1:${PORT}/v1" --endpoint-label localhost-a6000-llamacpp \
  --model "${MODEL_ALIAS}" --profile qwen38-low --max-tokens 2048 --warmup 1 --runs 3 \
  --output "${OUTPUT_ROOT}/performance.json"
