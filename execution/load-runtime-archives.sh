#!/usr/bin/env bash
set -euo pipefail

if [ "$#" -ne 1 ]; then
  echo "Usage: $0 ARCHIVE_DIR" >&2
  exit 1
fi

archive_dir="$(cd "$1" && pwd)"
vllm_archive="$archive_dir/gb10-ds4-vllm-f277b3d-nvfp4.tar.zst"
unsloth_archive="$archive_dir/gb10-unsloth-llama-f0c483c4-rpc.tar.zst"

vllm_archive_sha="d712fb1c6ccb549aadd59c9faddd408018a19bf8d06c2821ec7875201973915e"
unsloth_archive_sha="2ade8cbffd08c6452ab17d1e726470f3154d828d13674c339eccd43ae2164e5a"
vllm_image="gb10-ds4-vllm:f277b3d-nvfp4"
unsloth_image="gb10-unsloth-llama:f0c483c4-rpc"
vllm_fingerprint="36adbf92fe8cdd5c57609b2c5ccfa8e2fc32a340c9ee3d727be538143dda74db"
unsloth_fingerprint="0f9879dbe8c5c6bf8cffbe9128149a555bf84f6ef77452b3b8614b63ad0e5f72"

command -v zstd >/dev/null || {
  echo "zstd is required" >&2
  exit 1
}
command -v jq >/dev/null || {
  echo "jq is required" >&2
  exit 1
}
docker info >/dev/null || {
  echo "Docker daemon is not accessible to $(id -un)" >&2
  exit 1
}

image_fingerprint() {
  local image="$1"
  local fingerprint
  fingerprint="$(
    docker image inspect "$image" \
      | jq -S -c '.[0] | {Architecture,Os,Created,Author,Config,RootFS,History}' \
      | sha256sum
  )"
  printf '%s\n' "${fingerprint%% *}"
}

printf '%s  %s\n' "$vllm_archive_sha" "$vllm_archive" | sha256sum --check
printf '%s  %s\n' "$unsloth_archive_sha" "$unsloth_archive" | sha256sum --check

images_ready=0
if docker image inspect "$vllm_image" "$unsloth_image" >/dev/null 2>&1; then
  current_vllm_fingerprint="$(image_fingerprint "$vllm_image")"
  current_unsloth_fingerprint="$(image_fingerprint "$unsloth_image")"
  if [ "$current_vllm_fingerprint" = "$vllm_fingerprint" ] \
    && [ "$current_unsloth_fingerprint" = "$unsloth_fingerprint" ]; then
    images_ready=1
    echo "Runtime image content is already present; skipping reload."
  fi
fi

if [ "$images_ready" = "0" ]; then
  zstd --decompress --stdout "$vllm_archive" | docker image load
  zstd --decompress --stdout "$unsloth_archive" | docker image load
fi

actual_vllm_id="$(docker image inspect "$vllm_image" --format '{{.Id}}')"
actual_unsloth_id="$(docker image inspect "$unsloth_image" --format '{{.Id}}')"
actual_vllm_fingerprint="$(image_fingerprint "$vllm_image")"
actual_unsloth_fingerprint="$(image_fingerprint "$unsloth_image")"

if [ "$actual_vllm_fingerprint" != "$vllm_fingerprint" ]; then
  echo "vLLM image content mismatch: expected=$vllm_fingerprint actual=$actual_vllm_fingerprint" >&2
  exit 1
fi
if [ "$actual_unsloth_fingerprint" != "$unsloth_fingerprint" ]; then
  echo "Unsloth image content mismatch: expected=$unsloth_fingerprint actual=$actual_unsloth_fingerprint" >&2
  exit 1
fi

echo "Runtime images ready:"
echo "  $vllm_image id=$actual_vllm_id fingerprint=$actual_vllm_fingerprint"
echo "  $unsloth_image id=$actual_unsloth_id fingerprint=$actual_unsloth_fingerprint"
