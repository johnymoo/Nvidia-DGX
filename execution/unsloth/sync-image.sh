#!/usr/bin/env bash
set -euo pipefail

if [ "$#" -ne 2 ]; then
  echo "Usage: $0 COMMON_ENV HEAD_ENV" >&2
  exit 1
fi

for env_file in "$1" "$2"; do
  set -a
  # shellcheck disable=SC1090
  source "$env_file"
  set +a
done

: "${UNSLOTH_LLAMA_IMAGE:?set UNSLOTH_LLAMA_IMAGE in common env}"
: "${WORKER_SSH:?set WORKER_SSH in head env}"

docker image inspect "$UNSLOTH_LLAMA_IMAGE" >/dev/null
docker image save "$UNSLOTH_LLAMA_IMAGE" | ssh "$WORKER_SSH" docker image load

head_id="$(docker image inspect "$UNSLOTH_LLAMA_IMAGE" --format '{{.Id}}')"
worker_id="$(ssh "$WORKER_SSH" docker image inspect "$UNSLOTH_LLAMA_IMAGE" --format '{{.Id}}')"

if [ "$head_id" != "$worker_id" ]; then
  echo "Image ID mismatch: head=$head_id worker=$worker_id" >&2
  exit 1
fi

echo "Unsloth image synchronized: $head_id"
