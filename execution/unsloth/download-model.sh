#!/usr/bin/env bash
set -euo pipefail

trap 'exit 130' INT
trap 'exit 143' TERM

if [ "$#" -ne 1 ]; then
  echo "Usage: $0 DESTINATION_ROOT" >&2
  exit 1
fi

destination="$1"
endpoint="${HF_ENDPOINT:-https://huggingface.co}"
repository="unsloth/DeepSeek-V4-Flash-0731-GGUF"
revision="fbbb5b93fb787c21338159b0af3318bb3f4d9768"

mkdir -p "$destination/UD-Q4_K_XL"

files=(
  "d13ce8f90855547bdaebe7312f531a1f2c4f822178d3103951f27fe884395cfa 5257408 UD-Q4_K_XL/DeepSeek-V4-Flash-0731-UD-Q4_K_XL-00001-of-00005.gguf"
  "d5b61668950f4743aacd677675d7fcf7507dbe1db6d304e8ff97ed1f00827bee 48935523072 UD-Q4_K_XL/DeepSeek-V4-Flash-0731-UD-Q4_K_XL-00002-of-00005.gguf"
  "9705db7e589f360685ca7bd48100b270d78d228d4f5aa980508f3b2778af5494 48980787136 UD-Q4_K_XL/DeepSeek-V4-Flash-0731-UD-Q4_K_XL-00003-of-00005.gguf"
  "7f13a68e3ca64208454c4ba32cc2757c0cbe78e3e5576c3142bf7007ca97da42 49999168416 UD-Q4_K_XL/DeepSeek-V4-Flash-0731-UD-Q4_K_XL-00004-of-00005.gguf"
  "ed0d93164d3784968d6ce40d6d201ba98337f16e7db1b31fe495b2b0f334cc09 7174505088 UD-Q4_K_XL/DeepSeek-V4-Flash-0731-UD-Q4_K_XL-00005-of-00005.gguf"
  "2c7ac54b0b64a99df1f139a9f1371a00198265e1d6a614b77597d20a655a4249 10896057440 dspark-DeepSeek-V4-Flash-0731-Q8_0.gguf"
)

backend="${DOWNLOAD_BACKEND:-auto}"
case "$backend" in
  auto|hf|curl) ;;
  *)
    echo "DOWNLOAD_BACKEND must be auto, hf, or curl, got: $backend" >&2
    exit 1
    ;;
esac

hf_cli="${HF_CLI:-}"
if [ -z "$hf_cli" ]; then
  hf_cli="$(command -v hf 2>/dev/null || true)"
fi
if [ -z "$hf_cli" ] && [ -x "$HOME/.local/bin/hf" ]; then
  hf_cli="$HOME/.local/bin/hf"
fi

if [ "$backend" != "curl" ] && [ -n "$hf_cli" ]; then
  paths=()
  for record in "${files[@]}"; do
    read -r _ _ relative <<<"$record"
    paths+=("$relative")
  done

  echo "Downloading pinned snapshot with huggingface_hub/Xet"
  if ! "$hf_cli" download "$repository" "${paths[@]}" \
    --revision "$revision" \
    --local-dir "$destination" \
    --max-workers "${HF_MAX_WORKERS:-6}"; then
    if [ "$backend" = "hf" ]; then
      echo "huggingface_hub download failed" >&2
      exit 1
    fi
    echo "huggingface_hub download failed; falling back to curl" >&2
  fi
elif [ "$backend" = "hf" ]; then
  echo "DOWNLOAD_BACKEND=hf but no hf CLI was found" >&2
  exit 1
fi

for record in "${files[@]}"; do
  read -r expected_sha expected_size relative <<<"$record"
  target="$destination/$relative"
  mkdir -p "$(dirname "$target")"

  if [ -f "$target" ] \
    && [ "$(stat -c %s "$target")" = "$expected_size" ] \
    && printf '%s  %s\n' "$expected_sha" "$target" | sha256sum --check --status; then
    echo "verified: $relative"
    continue
  fi

  url="$endpoint/$repository/resolve/$revision/$relative"
  echo "downloading: $relative"
  curl -fL -C - --retry 8 --retry-all-errors --connect-timeout 20 \
    --output "$target" "$url"

  actual_size="$(stat -c %s "$target")"
  if [ "$actual_size" != "$expected_size" ]; then
    echo "Size mismatch for $relative: expected $expected_size, got $actual_size" >&2
    exit 1
  fi
  printf '%s  %s\n' "$expected_sha" "$target" | sha256sum --check
done

printf '%s\n' \
  "repository=$repository" \
  "revision=$revision" \
  "variant=UD-Q4_K_XL" \
  "draft=dspark-DeepSeek-V4-Flash-0731-Q8_0.gguf" \
  >"$destination/SOURCE"

echo "Model snapshot ready: $destination"
