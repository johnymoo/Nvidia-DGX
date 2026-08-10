#!/usr/bin/env bash
set -euo pipefail

if [ "$#" -ne 3 ]; then
  echo "Usage: $0 COMMON_ENV HEAD_ENV UNSLOTH_COMMON_ENV" >&2
  exit 1
fi

for env_file in "$1" "$2" "$3"; do
  set -a
  # shellcheck disable=SC1090
  source "$env_file"
  set +a
done

: "${WORKER_SSH:?set WORKER_SSH in head env}"
: "${WORKER_MODEL_ROOT:?set WORKER_MODEL_ROOT in head env}"
: "${WORKER_DEPLOY_ROOT:?set WORKER_DEPLOY_ROOT in head env}"
: "${MODEL_ROOT:?set MODEL_ROOT in head env}"
: "${DSPARK_MODEL:?set DSPARK_MODEL in common env}"
: "${GGUF_MODEL_ROOT:?set GGUF_MODEL_ROOT in Unsloth common env}"

script_dir="$(cd "$(dirname "$0")" && pwd)"
deploy_root="$(cd "$script_dir/.." && pwd)"
artifact_dir="$deploy_root/artifacts"
model_name="$(basename "$DSPARK_MODEL")"
manifest_name="${model_name}.sha256"
manifest="$artifact_dir/$manifest_name"

wait_for_tmux() {
  local session="$1"
  while tmux has-session -t "$session" 2>/dev/null; do
    echo "Waiting for tmux session: $session"
    sleep 30
  done
}

mkdir -p "$artifact_dir"

wait_for_tmux gb10-image-archive-sync
ssh "$WORKER_SSH" \
  "$WORKER_DEPLOY_ROOT/execution/load-runtime-archives.sh '$WORKER_DEPLOY_ROOT/artifacts'"

wait_for_tmux gb10-vllm-model-sync
"$script_dir/model-manifest.sh" create \
  "$MODEL_ROOT/$model_name" "$manifest"
rsync -a "$manifest" "$WORKER_SSH:$WORKER_DEPLOY_ROOT/artifacts/$manifest_name"
ssh "$WORKER_SSH" \
  "$WORKER_DEPLOY_ROOT/execution/model-manifest.sh verify '$WORKER_MODEL_ROOT/$model_name' '$WORKER_DEPLOY_ROOT/artifacts/$manifest_name'"

wait_for_tmux gb10-unsloth-download
source_marker="$GGUF_MODEL_ROOT/SOURCE"
if [ ! -s "$source_marker" ]; then
  echo "Missing Unsloth completion marker: $source_marker" >&2
  exit 1
fi
grep -Fxq 'revision=fbbb5b93fb787c21338159b0af3318bb3f4d9768' "$source_marker"

head_vllm_id="$(docker image inspect gb10-ds4-vllm:f277b3d-nvfp4 --format '{{.Id}}')"
head_unsloth_id="$(docker image inspect gb10-unsloth-llama:f0c483c4-rpc --format '{{.Id}}')"
worker_vllm_id="$(ssh "$WORKER_SSH" docker image inspect gb10-ds4-vllm:f277b3d-nvfp4 --format '{{.Id}}')"
worker_unsloth_id="$(ssh "$WORKER_SSH" docker image inspect gb10-unsloth-llama:f0c483c4-rpc --format '{{.Id}}')"
head_vllm_fingerprint="$(
  docker image inspect gb10-ds4-vllm:f277b3d-nvfp4 \
    | jq -S -c '.[0] | {Architecture,Os,Created,Author,Config,RootFS,History}' \
    | sha256sum
)"
head_vllm_fingerprint="${head_vllm_fingerprint%% *}"
head_unsloth_fingerprint="$(
  docker image inspect gb10-unsloth-llama:f0c483c4-rpc \
    | jq -S -c '.[0] | {Architecture,Os,Created,Author,Config,RootFS,History}' \
    | sha256sum
)"
head_unsloth_fingerprint="${head_unsloth_fingerprint%% *}"
worker_vllm_fingerprint="$(
  ssh "$WORKER_SSH" docker image inspect gb10-ds4-vllm:f277b3d-nvfp4 \
    | jq -S -c '.[0] | {Architecture,Os,Created,Author,Config,RootFS,History}' \
    | sha256sum
)"
worker_vllm_fingerprint="${worker_vllm_fingerprint%% *}"
worker_unsloth_fingerprint="$(
  ssh "$WORKER_SSH" docker image inspect gb10-unsloth-llama:f0c483c4-rpc \
    | jq -S -c '.[0] | {Architecture,Os,Created,Author,Config,RootFS,History}' \
    | sha256sum
)"
worker_unsloth_fingerprint="${worker_unsloth_fingerprint%% *}"

[ "$head_vllm_fingerprint" = "$worker_vllm_fingerprint" ] || {
  echo "vLLM image content mismatch: head=$head_vllm_fingerprint worker=$worker_vllm_fingerprint" >&2
  exit 1
}
[ "$head_unsloth_fingerprint" = "$worker_unsloth_fingerprint" ] || {
  echo "Unsloth image content mismatch: head=$head_unsloth_fingerprint worker=$worker_unsloth_fingerprint" >&2
  exit 1
}

echo "Pre-link assets are ready and verified."
echo "  official_model_manifest=$manifest"
echo "  unsloth_source=$source_marker"
echo "  vllm_head_id=$head_vllm_id"
echo "  vllm_worker_id=$worker_vllm_id"
echo "  vllm_fingerprint=$head_vllm_fingerprint"
echo "  unsloth_head_id=$head_unsloth_id"
echo "  unsloth_worker_id=$worker_unsloth_id"
echo "  unsloth_fingerprint=$head_unsloth_fingerprint"
