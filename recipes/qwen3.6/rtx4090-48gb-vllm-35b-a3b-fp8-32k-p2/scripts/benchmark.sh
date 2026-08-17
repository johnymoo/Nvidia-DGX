#!/usr/bin/env bash
set -euo pipefail
SCRIPT_DIR=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)
# shellcheck source=common.sh
source "${SCRIPT_DIR}/common.sh"
OUTPUT_ROOT=${1:-${PROJECT_DIR}/receipts/generated}
mkdir -p "${OUTPUT_ROOT}"
python3 "${PROJECT_DIR}/../model-benchmark-qwen-deepseek/scripts/lakehouse_thinking_benchmark.py" --base-url "http://127.0.0.1:${PORT}/v1" --model "${MODEL_ALIAS}" --tag qwen36-fp8-off --mode off --output "${OUTPUT_ROOT}/lakehouse-off.json"
python3 "${PROJECT_DIR}/../model-benchmark-qwen-deepseek/scripts/lakehouse_thinking_benchmark.py" --base-url "http://127.0.0.1:${PORT}/v1" --model "${MODEL_ALIAS}" --tag qwen36-fp8-thinking --mode qwen36-thinking --output "${OUTPUT_ROOT}/lakehouse-thinking.json"
