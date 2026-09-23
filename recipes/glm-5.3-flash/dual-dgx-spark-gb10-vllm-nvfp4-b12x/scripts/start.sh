#!/usr/bin/env bash
# GLM-5.3-Flash-NVFP4 dual-GB10 serving stack — canonical start (2026-09-24 hardened)
# vLLM ignores SIGTERM (docker stop always escalates to SIGKILL, journal-proven);
# the kernel then needs seconds to reap the 89G-mmap process with live RoCE QPs.
# Launching before that reaping finishes makes rank0's RDMA writes hit a not-yet-
# ready rank1 QP -> "transport retry counter exceeded" (vendor_err 0x81).
# Hence: stop -> WAIT until both ranks' VLLM processes are gone -> launch.
set -euo pipefail
cd ~/glm53-nvfp4-eval/spark-vllm-docker

HF_HOME=/home/chriswang/models/hf-nvfp4
HF_CACHE_DIR_WORKER=/home/admin/models/hf-nvfp4
RECIPE=recipes/glm-5.3-flash.yaml

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

if docker ps --format "{{.Names}}" | grep -q "^vllm_node$"; then
  docker stop vllm_node >/dev/null || docker kill vllm_node >/dev/null || true
fi
if ssh -n admin@192.168.192.198 "docker ps --format '{{.Names}}' | grep -q '^vllm_node$'"; then
  ssh -n admin@192.168.192.198 "docker stop vllm_node >/dev/null || docker kill vllm_node >/dev/null" || true
fi

# wait until no VLLM process remains on either rank (kernel reaping done)
for i in $(seq 1 30); do pgrep -f "VLLM::" >/dev/null 2>&1 || break; sleep 3; done
pgrep -f "VLLM::" >/dev/null 2>&1 && echo "WARN: head VLLM still up" || echo "head ranks gone"
ssh -n admin@192.168.192.198 'for i in $(seq 1 30); do pgrep -f "VLLM::" >/dev/null 2>&1 || { echo "worker ranks gone"; exit 0; }; sleep 3; done; echo "WARN: worker VLLM still up"' || true
sleep 3

HF_HOME="$HF_HOME" HF_CACHE_DIR_WORKER="$HF_CACHE_DIR_WORKER" \
  nohup ./run-recipe.sh "$RECIPE" --port 8890 \
  > /tmp/nvfp4-serve.log 2>&1 &
echo "launched pid $! — log /tmp/nvfp4-serve.log"
echo "wait ~2-3min, then: grep -E 'KV cache size|startup complete' /tmp/nvfp4-serve.log"
