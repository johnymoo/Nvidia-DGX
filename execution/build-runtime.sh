#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
WORKSPACE="$(cd "$SCRIPT_DIR/.." && pwd)"
if [ -d "$WORKSPACE/upstream/.git" ]; then
  DEFAULT_UPSTREAM_DIR="$WORKSPACE/upstream"
else
  DEFAULT_UPSTREAM_DIR="$WORKSPACE/planning/01-raw/upstream-dspark"
fi
UPSTREAM_DIR="${UPSTREAM_DIR:-$DEFAULT_UPSTREAM_DIR}"
UPSTREAM_REV="f277b3dfa718a5962bed64e69e7e640a5384ec2f"
BASE_IMAGE="${BASE_IMAGE:-gb10-ds4-vllm:base-f277b3d}"
STAGE_A_IMAGE="${STAGE_A_IMAGE:-gb10-ds4-vllm:stage-a-f277b3d}"
STAGE_B_IMAGE="${STAGE_B_IMAGE:-gb10-ds4-vllm:stage-b-f277b3d}"
STAGE_C_IMAGE="${STAGE_C_IMAGE:-gb10-ds4-vllm:stage-c-f277b3d}"
FINAL_IMAGE="${DSPARK_VLLM_IMAGE:-gb10-ds4-vllm:f277b3d-nvfp4}"
mode="${1:---build}"

if [ "$mode" != "--build" ] && [ "$mode" != "--check" ]; then
  echo "Usage: $0 [--check|--build]" >&2
  exit 1
fi

if [ ! -d "$UPSTREAM_DIR/.git" ]; then
  echo "Missing upstream checkout: $UPSTREAM_DIR" >&2
  exit 1
fi

actual_rev="$(git -C "$UPSTREAM_DIR" rev-parse HEAD)"
if [ "$actual_rev" != "$UPSTREAM_REV" ]; then
  echo "Expected upstream $UPSTREAM_REV, found $actual_rev" >&2
  exit 1
fi

if ! grep -q 'shared_experts.gate_up_proj.*shared_experts.w1' \
  "$UPSTREAM_DIR/recipe/overlay/vllm/v1/spec_decode/dspark.py"; then
  echo "Upstream checkout does not contain the required 0731 Patch 4 loader fix" >&2
  exit 1
fi

if [ "$mode" = "--check" ]; then
  echo "Runtime inputs verified: upstream=$actual_rev Patch4=present"
  exit 0
fi

docker build \
  -f "$SCRIPT_DIR/runtime/Dockerfile.overlay" \
  -t "$BASE_IMAGE" \
  "$UPSTREAM_DIR/recipe/overlay"

docker build \
  --build-arg "BASE_IMAGE=$BASE_IMAGE" \
  -f "$UPSTREAM_DIR/recipe/nvfp4/Dockerfile.stage-a" \
  -t "$STAGE_A_IMAGE" \
  "$UPSTREAM_DIR"

docker build \
  --build-arg "BASE_IMAGE=$STAGE_A_IMAGE" \
  -f "$UPSTREAM_DIR/recipe/nvfp4/Dockerfile.stage-b" \
  -t "$STAGE_B_IMAGE" \
  "$UPSTREAM_DIR"

docker build \
  --build-arg "BASE_IMAGE=$STAGE_B_IMAGE" \
  -f "$UPSTREAM_DIR/recipe/nvfp4/Dockerfile.stage-c" \
  -t "$STAGE_C_IMAGE" \
  "$UPSTREAM_DIR"

docker build \
  --build-arg "BASE_IMAGE=$STAGE_C_IMAGE" \
  -f "$SCRIPT_DIR/runtime/Dockerfile.final" \
  -t "$FINAL_IMAGE" \
  "$SCRIPT_DIR/runtime"

docker run --rm --entrypoint /opt/env/bin/python "$FINAL_IMAGE" -c \
  "import inspect, vllm; from vllm.v1.spec_decode import dspark; source=inspect.getsource(dspark); assert 'shared_experts.gate_up_proj' in source; print('runtime-ok', vllm.__version__)"

docker image inspect "$FINAL_IMAGE" --format \
  'image={{.RepoTags}} id={{.Id}} source={{index .Config.Labels "org.opencontainers.image.revision"}}'
