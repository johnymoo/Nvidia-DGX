#!/usr/bin/env bash

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
tmp="$(mktemp -d)"
trap 'rm -rf "$tmp"' EXIT
scripts="$tmp/scripts"
root="$tmp/root"
fake_ss="$tmp/fake-ss"
calls="$tmp/ss-calls"

mkdir -p "$scripts" "$root/artifacts/verification" \
  "$root/comfy/ComfyUI" "$root/execution/minimax-h3" "$root/venv/bin"
cp "$SCRIPT_DIR/execution/minimax-h3/start-comfyui.sh" "$scripts/start-comfyui.sh"
printf '%s\n' \
  'H3_SS_BIN="${H3_SS_BIN:-ss}"' \
  'sha256sum() { printf "fixture  %s\\n" "$1"; }' \
  'h3_assert_weight_fingerprints() { :; }' \
  'h3_assert_protected() { :; }' \
  'h3_process_observation() { printf "{\\\"running\\\":false}\\n"; }' \
  > "$scripts/runtime-lib.sh"
printf '%s\n' '# fixture' > "$root/comfy/ComfyUI/main.py"
printf '%s\n' '# fixture' > "$root/extra_model_paths.yaml"
printf '%s\n' 'fixture' > "$root/execution/minimax-h3/weights-manifest.tsv"
printf '%s\n' \
  '{"status":"passed","file_count":11,"total_bytes":176195310067,"manifest_sha256":"fixture"}' \
  > "$root/artifacts/verification/latest.json"
ln -s /bin/sh "$root/venv/bin/python"
printf '%s\n' \
  '#!/usr/bin/env bash' \
  'printf "%s\\n" "$*" > "$H3_SS_LOG"' \
  'printf "State Recv-Q Send-Q Local Address:Port Peer Address:Port\\n"' \
  'printf "LISTEN 0 4096 *:12345 *:*\\n"' \
  > "$fake_ss"
chmod +x "$fake_ss"

if output="$(H3_SS_BIN="$fake_ss" H3_SS_LOG="$calls" \
  "$scripts/start-comfyui.sh" --root "$root" --port 12345 2>&1)"; then
  printf '%s\n' 'expected occupied test port to fail' >&2
  exit 1
fi
[[ "$output" == *'port 12345 is already occupied by a non-matching process'* ]]
[[ "$(<"$calls")" == '-ltn sport = :12345' ]]
