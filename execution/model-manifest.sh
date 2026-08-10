#!/usr/bin/env bash
set -euo pipefail

usage() {
  echo "Usage: $0 create MODEL_DIR MANIFEST | verify MODEL_DIR MANIFEST" >&2
}

if [ "$#" -ne 3 ]; then
  usage
  exit 1
fi

mode="$1"
model_dir="$(cd "$2" && pwd)"
manifest="$3"

case "$mode" in
  create)
    manifest_dir="$(cd "$(dirname "$manifest")" && pwd)"
    manifest_path="$manifest_dir/$(basename "$manifest")"
    temp="${manifest_path}.tmp.$$"
    (
      cd "$model_dir"
      find . -type f \
        ! -name '.msc' \
        ! -name '.mv' \
        -print0 \
        | sort -z \
        | xargs -0 sha256sum
    ) >"$temp"
    mv "$temp" "$manifest_path"
    echo "Created $manifest_path with $(wc -l <"$manifest_path") files."
    ;;
  verify)
    if [ ! -s "$manifest" ]; then
      echo "Missing manifest: $manifest" >&2
      exit 1
    fi
    (cd "$model_dir" && sha256sum --check "$manifest")
    ;;
  *)
    usage
    exit 1
    ;;
esac
