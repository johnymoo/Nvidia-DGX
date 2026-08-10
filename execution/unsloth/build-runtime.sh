#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
IMAGE="${UNSLOTH_LLAMA_IMAGE:-gb10-unsloth-llama:f0c483c4-rpc}"

docker build \
  --network host \
  --build-arg LLAMA_COMMIT=f0c483c4df52f82cc5795433c9e9332fb3e8aa21 \
  --build-arg LLAMA_BRANCH=fix/rpc-multi-server-buffer-ownership \
  -f "$SCRIPT_DIR/Dockerfile" \
  -t "$IMAGE" \
  "$SCRIPT_DIR"

docker run --rm --gpus all --entrypoint llama-server "$IMAGE" --version
docker run --rm --gpus all --entrypoint ggml-rpc-server "$IMAGE" --help >/dev/null
docker image inspect "$IMAGE" --format \
  'image={{.RepoTags}} id={{.Id}} revision={{index .Config.Labels "org.opencontainers.image.revision"}}'
