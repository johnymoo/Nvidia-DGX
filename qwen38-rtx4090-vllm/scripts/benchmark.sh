#!/usr/bin/env bash
set -euo pipefail
SCRIPT_DIR=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)
# shellcheck source=common.sh
source "${SCRIPT_DIR}/common.sh"

OUTPUT_ROOT=${1:-${PROJECT_DIR}/receipts/generated}
mkdir -p "${OUTPUT_ROOT}"
python3 "${PROJECT_DIR}/../model-benchmark-qwen-deepseek/scripts/quality_benchmark.py" \
  --base-url "http://127.0.0.1:${PORT}/v1" --model "${MODEL_ALIAS}" \
  --tag qwen38-rtx4090-fp8-instruct --thinking off \
  --output "${OUTPUT_ROOT}/quality-instruct.json"
python3 "${PROJECT_DIR}/../model-benchmark-qwen-deepseek/scripts/quality_benchmark.py" \
  --base-url "http://127.0.0.1:${PORT}/v1" --model "${MODEL_ALIAS}" \
  --tag qwen38-rtx4090-fp8-thinking-low --thinking low --max-token-multiplier 4 \
  --output "${OUTPUT_ROOT}/quality-thinking-low.json"
