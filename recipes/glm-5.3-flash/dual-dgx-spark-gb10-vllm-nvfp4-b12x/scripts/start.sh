#!/usr/bin/env bash
# GLM-5.3-Flash-NVFP4 dual-GB10 serving stack — canonical start (2026-09-21)
# Upstream-params config: KV 8G pinned (1,061,538 tok) / 500k ctx / MNBT 4096 / util 0.87
set -euo pipefail
cd ~/glm53-nvfp4-eval/spark-vllm-docker

HF_HOME=/home/chriswang/models/hf-nvfp4
HF_CACHE_DIR_WORKER=/home/admin/models/hf-nvfp4
RECIPE=recipes/glm-5.3-flash.yaml

# sanity: revision pinned + weights present on both nodes
REV=$(python3 - <<PY
import re
print(re.search(r'model_revision: "([0-9a-f]+)"', open("$RECIPE").read()).group(1))
PY
)
N_HEAD=$(find "$HF_HOME/hub" -name "*.safetensors" 2>/dev/null | wc -l)
N_WORKER=$(ssh -n admin@192.168.192.198 "find $HF_CACHE_DIR_WORKER/hub -name '*.safetensors' 2>/dev/null | wc -l")
echo "revision=$REV head_shards=$N_HEAD worker_shards=$N_WORKER"
[[ "$N_HEAD" -ge 46 && "$N_WORKER" -ge 46 ]] || { echo "FATAL: weights incomplete"; exit 1; }
grep -q "$REV" "$HF_HOME/hub/models--local-inference-lab--GLM-5.3-Flash-NVFP4-Spark/refs/main" || {
  echo "FATAL: refs/main mismatch"; exit 1; }

docker stop vllm_node >/dev/null 2>&1 || true
ssh -n admin@192.168.192.198 "docker stop vllm_node" >/dev/null 2>&1 || true

HF_HOME="$HF_HOME" HF_CACHE_DIR_WORKER="$HF_CACHE_DIR_WORKER" \
  nohup ./run-recipe.sh "$RECIPE" --port 8890 \
  > /tmp/nvfp4-serve.log 2>&1 &
echo "launched pid $! — log /tmp/nvfp4-serve.log"
echo "wait ~5min, then: grep -E 'KV cache size|startup complete' /tmp/nvfp4-serve.log"
