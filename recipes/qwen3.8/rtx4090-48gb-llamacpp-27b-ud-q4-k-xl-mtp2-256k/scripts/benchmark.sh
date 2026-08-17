#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)
# shellcheck source=common.sh
source "${SCRIPT_DIR}/common.sh"
OUTPUT_ROOT=${1:-${STATE_ROOT}/receipts/benchmark-$(date -u +%Y%m%dT%H%M%SZ)}
HARNESS_ROOT=${PROJECT_DIR}/../model-benchmark-qwen-deepseek
mkdir -p "${OUTPUT_ROOT}"

python3 "${HARNESS_ROOT}/scripts/lakehouse_thinking_benchmark.py" \
  --base-url "http://127.0.0.1:${PORT}/v1" --endpoint-label rtx4090-llamacpp-q4 \
  --model "${MODEL_ALIAS}" --tag qwen38-q4-v2-low --treatment "Qwen3.8 UD-Q4_K_XL / llama.cpp / low" \
  --mode qwen38-low --max-tokens 32768 --request-timeout 3600 --stream \
  --repeat 1 --expected-runs 1 --max-response-chars 32768 --max-reasoning-chars 32768 \
  --output "${OUTPUT_ROOT}/quality.json"
python3 "${HARNESS_ROOT}/scripts/inference_latency_benchmark.py" \
  --base-url "http://127.0.0.1:${PORT}/v1" --endpoint-label rtx4090-llamacpp-q4 \
  --model "${MODEL_ALIAS}" --profile qwen38-low --max-tokens 2048 --warmup 1 --runs 3 \
  --output "${OUTPUT_ROOT}/performance.json"
python3 "${HARNESS_ROOT}/scripts/vision_quantization_benchmark.py" \
  --base-url "http://127.0.0.1:${PORT}/v1" --model "${MODEL_ALIAS}" \
  --tag qwen38-q4-vision --runtime llama.cpp --quantization UD-Q4_K_XL --thinking off \
  --output "${OUTPUT_ROOT}/vision.json"
