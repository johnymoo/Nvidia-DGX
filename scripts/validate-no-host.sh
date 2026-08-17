#!/usr/bin/env bash
set -euo pipefail

ROOT=$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)
cd "$ROOT"

for name in PRIVATE_DS_BASE_URL QWEN_LOCAL_BASE_URL MODEL_ENDPOINT OPENAI_BASE_URL; do
  if [[ -n "${!name:-}" ]]; then
    echo "Refusing no-host validation with $name set" >&2
    exit 2
  fi
done

python3 -m unittest discover -s tests -v
python3 -m unittest discover -s benchmarks/legacy/qwen-deepseek-cross-model/tests -v
python3 -m unittest discover -s recipes/qwen3.6/rtx4090-48gb-ollama-27b-q4-k-m-128k -p 'test*.py' -v
python3 -m unittest discover -s recipes/qwen3.6/rtx4090-48gb-vllm-35b-a3b-fp8-32k-p2/tests -v
python3 -m unittest discover -s recipes/qwen3.8/rtx3090-24gb-llamacpp-27b-q3-k-s-128k-p2/tests -v
python3 -m unittest discover -s recipes/qwen3.8/rtx4090-48gb-llamacpp-27b-ud-q4-k-xl-mtp2-256k/tests -v
python3 -m unittest discover -s recipes/qwen3.8/rtx4090-48gb-vllm-27b-fp8-64k-p4/tests -v

(
  cd recipes/deepseek-v4/dual-dgx-spark-gb10-vllm-flash-0731-patch4-thinking-on/benchmark
  ./run.sh test
)
(
  cd recipes/minimax-h3/dgx-spark-gb10-comfyui-trained-max-15s
  ./test-recipe.sh
)

python3 benchmarks/runner/validate_submission.py --all

docker compose -f examples/apps/pdf-to-markdown/docker-compose.yml config --quiet
docker compose \
  --env-file recipes/deepseek-v4/dual-dgx-spark-gb10-vllm-flash-0731-patch4-thinking-on/.env.example \
  -f recipes/deepseek-v4/dual-dgx-spark-gb10-vllm-flash-0731-patch4-thinking-on/docker-compose.yml config --quiet
docker compose -f recipes/qwen3.6/rtx4090-48gb-ollama-27b-q4-k-m-128k/compose.yaml config --quiet
docker compose \
  --env-file recipes/qwen3.6/rtx4090-48gb-vllm-35b-a3b-fp8-32k-p2/config/qwen36.env.example \
  -f recipes/qwen3.6/rtx4090-48gb-vllm-35b-a3b-fp8-32k-p2/compose.yaml config --quiet
docker compose \
  --env-file recipes/qwen3.8/rtx4090-48gb-vllm-27b-fp8-64k-p4/config/qwen38.env.example \
  -f recipes/qwen3.8/rtx4090-48gb-vllm-27b-fp8-64k-p4/compose.yaml config --quiet

find . -path './.git' -prune -o -path './execution' -prune -o -path '*/benchmark/fixtures/*' -prune -o -name '*.py' -type f -print0 | xargs -0 python3 -m py_compile
find . -path './.git' -prune -o -path './execution' -prune -o -name '*.sh' -type f -print0 | xargs -0 -n 1 bash -n

./lab generate --check
./lab validate
git diff --check

echo "no-host validation passed; no lifecycle command, endpoint, SSH, Docker workload, or inference was run"
