#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)
# shellcheck source=common.sh
source "${SCRIPT_DIR}/common.sh"

command -v docker >/dev/null
command -v nvidia-smi >/dev/null
verify_artifacts
nvidia-smi --query-gpu=name,memory.total --format=csv,noheader | grep -F 'RTX 3090' >/dev/null

if ss -H -ltn "sport = :${PORT}" | grep -q .; then
  echo "Refusing start: port ${PORT} is occupied" >&2
  exit 1
fi
if docker container inspect "${CONTAINER_NAME}" >/dev/null 2>&1; then
  echo "Refusing start: container ${CONTAINER_NAME} already exists" >&2
  exit 1
fi

mkdir -p "${STATE_ROOT}/logs" "${STATE_ROOT}/receipts"
docker image inspect "${LLAMA_IMAGE}" >/dev/null 2>&1 || docker pull "${LLAMA_IMAGE}"
docker run --detach \
  --name "${CONTAINER_NAME}" \
  --gpus all \
  --restart unless-stopped \
  --publish "${PUBLISH_HOST}:${PORT}:${PORT}" \
  --health-cmd "curl --fail --silent http://127.0.0.1:${PORT}/health || exit 1" \
  --health-interval 10s --health-timeout 5s --health-retries 12 --health-start-period 600s \
  --volume "${MODEL_ROOT}:/models:ro" \
  --volume "${STATE_ROOT}/logs:/logs" \
  "${LLAMA_IMAGE}" \
  --model "/models/${MODEL_FILE}" \
  --mmproj "/models/${MMPROJ_FILE}" \
  --alias "${MODEL_ALIAS}" \
  --host 0.0.0.0 --port "${PORT}" \
  --ctx-size "${CTX_SIZE}" --n-gpu-layers 999 --parallel "${PARALLEL}" \
  --flash-attn on --cache-type-k q4_0 --cache-type-v q4_0 \
  --temp 0.7 --top-p 0.8 --top-k 20 --min-p 0.0 --presence-penalty 1.5 \
  --chat-template-kwargs '{"enable_thinking":false}' --metrics

for _ in $(seq 1 180); do
  if curl -fsS "http://127.0.0.1:${PORT}/health" >/dev/null 2>&1; then
    "${SCRIPT_DIR}/status.sh"
    exit 0
  fi
  [[ $(docker inspect -f '{{.State.Running}}' "${CONTAINER_NAME}" 2>/dev/null || true) == true ]] || break
  sleep 5
done

docker logs --tail 200 "${CONTAINER_NAME}" >&2 || true
docker rm -f "${CONTAINER_NAME}" >/dev/null 2>&1 || true
exit 1
