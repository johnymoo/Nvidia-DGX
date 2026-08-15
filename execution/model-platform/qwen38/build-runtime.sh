#!/usr/bin/env bash
set -euo pipefail
umask 077

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
IMAGE="${QWEN38_VLLM_IMAGE:-gb10-qwen38-vllm:0.25.0}"
STATE_ROOT="${QWEN38_STATE_ROOT:-/home/admin/.local/state/model-platform/qwen38}"

docker build \
  --network host \
  --build-arg VLLM_VERSION=0.25.0 \
  -t "$IMAGE" \
  -f "$SCRIPT_DIR/Dockerfile" \
  "$SCRIPT_DIR"

docker run --rm --gpus all "$IMAGE" vllm --version
mkdir -p "$STATE_ROOT"
chmod 700 "$STATE_ROOT"
image_id="$(docker image inspect "$IMAGE" --format '{{.Id}}')"
recipe_sha256="$(sha256sum "$SCRIPT_DIR/Dockerfile" | awk '{print $1}')"
requirements="$(docker run --rm "$IMAGE" cat /usr/local/share/qwen38-runtime-requirements.txt)"
jq -n --arg image "$IMAGE" --arg image_id "$image_id" --arg recipe_sha256 "$recipe_sha256" \
  --arg requirements "$requirements" --arg built_at "$(date -u +%Y-%m-%dT%H:%M:%SZ)" \
  '{image:$image,image_id:$image_id,recipe_sha256:$recipe_sha256,built_at:$built_at,requirements:$requirements}' \
  >"$STATE_ROOT/runtime-image.json.tmp"
chmod 600 "$STATE_ROOT/runtime-image.json.tmp"
mv "$STATE_ROOT/runtime-image.json.tmp" "$STATE_ROOT/runtime-image.json"
jq . "$STATE_ROOT/runtime-image.json"
