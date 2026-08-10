#!/usr/bin/env bash
set -euo pipefail

if [ "$#" -lt 3 ]; then
  echo "Usage: $0 COMMON_ENV HEAD_ENV {model|image|source|all}" >&2
  exit 1
fi

for env_file in "$1" "$2"; do
  set -a
  # shellcheck disable=SC1090
  source "$env_file"
  set +a
done
mode="$3"

: "${WORKER_SSH:?set WORKER_SSH in head env}"
: "${WORKER_MODEL_ROOT:?set WORKER_MODEL_ROOT in head env}"
: "${WORKER_DEPLOY_ROOT:?set WORKER_DEPLOY_ROOT in head env}"
: "${MODEL_ROOT:?set MODEL_ROOT in head env}"
: "${DSPARK_MODEL:?set DSPARK_MODEL in common env}"
: "${DSPARK_VLLM_IMAGE:?set DSPARK_VLLM_IMAGE in common env}"

model_name="$(basename "$DSPARK_MODEL")"
script_dir="$(cd "$(dirname "$0")" && pwd)"
workspace="$(cd "$script_dir/.." && pwd)"
if [ -d "$workspace/upstream/.git" ]; then
  upstream="$workspace/upstream"
else
  upstream="$workspace/planning/01-raw/upstream-dspark"
fi

sync_model() {
  ssh "$WORKER_SSH" "mkdir -p '$WORKER_MODEL_ROOT/$model_name'"
  rsync -aH --partial --info=progress2 \
    "$MODEL_ROOT/$model_name/" \
    "$WORKER_SSH:$WORKER_MODEL_ROOT/$model_name/"
}

sync_image() {
  docker image inspect "$DSPARK_VLLM_IMAGE" >/dev/null
  docker image save "$DSPARK_VLLM_IMAGE" | ssh "$WORKER_SSH" docker image load
  head_id="$(docker image inspect "$DSPARK_VLLM_IMAGE" --format '{{.Id}}')"
  worker_id="$(ssh "$WORKER_SSH" docker image inspect "$DSPARK_VLLM_IMAGE" --format '{{.Id}}')"
  [ "$head_id" = "$worker_id" ] || {
    echo "Image ID mismatch: head=$head_id worker=$worker_id" >&2
    exit 1
  }
  echo "Image synchronized: $head_id"
}

sync_source() {
  if [ ! -d "$upstream/.git" ]; then
    echo "Missing upstream checkout: $upstream" >&2
    exit 1
  fi
  revision="$(git -C "$upstream" rev-parse HEAD)"
  ssh "$WORKER_SSH" "mkdir -p '$WORKER_DEPLOY_ROOT'"
  rsync -az --delete --exclude 'env/*.env' \
    "$script_dir/" "$WORKER_SSH:$WORKER_DEPLOY_ROOT/execution/"
  if ssh "$WORKER_SSH" "test -d '$WORKER_DEPLOY_ROOT/upstream/.git'"; then
    ssh "$WORKER_SSH" "git -C '$WORKER_DEPLOY_ROOT/upstream' fetch --prune origin && git -C '$WORKER_DEPLOY_ROOT/upstream' checkout --detach '$revision'"
  else
    ssh "$WORKER_SSH" "git clone https://github.com/tonyd2wild/DeepSeek-v4-Flash-0731-DSpark-1M-NVFP4-KV-2x-DGX-Spark.git '$WORKER_DEPLOY_ROOT/upstream' && git -C '$WORKER_DEPLOY_ROOT/upstream' checkout --detach '$revision'"
  fi
}

case "$mode" in
  model) sync_model ;;
  image) sync_image ;;
  source) sync_source ;;
  all) sync_source; sync_model; sync_image ;;
  *) echo "Unknown mode: $mode" >&2; exit 1 ;;
esac
