#!/usr/bin/env bash

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=execution/minimax-h3/runtime-lib.sh
source "$SCRIPT_DIR/runtime-lib.sh"

root=""
port="${H3_PORT:-8188}"
timeout_seconds="${H3_SMOKE_TIMEOUT:-1800}"

while (( $# )); do
  case "$1" in
    --root) root="$2"; shift 2 ;;
    --port) port="$2"; shift 2 ;;
    --timeout) timeout_seconds="$2"; shift 2 ;;
    *) printf 'unknown argument: %s\n' "$1" >&2; exit 1 ;;
  esac
done

[[ -n "$root" ]] || { printf '%s\n' '--root is required' >&2; exit 1; }

workflow="$root/workflows/h3-dense-baseline.json"
artifact="$root/artifacts/deployment/smoke"
output_dir="$root/output/smoke"
mkdir -p "$artifact" "$output_dir"
prompt="$artifact/prompt.json"
response="$artifact/queue-response.json"
before="$artifact/output-before.txt"
find "$output_dir" -type f -print | sort > "$before"
manifest="$root/execution/minimax-h3/weights-manifest.tsv"
manifest_sha="$(sha256sum "$manifest" | awk '{print $1}')"
runtime="$($root/execution/minimax-h3/status-comfyui.sh --root "$root" --port "$port")"
jq -e '.running == true and .http_code == "200" and .protected.matches == true' \
  <<<"$runtime" >/dev/null
runtime_identity="$(jq '{pid, start_ticks, boot_id, started_at}' <<<"$runtime")"

jq '
  .["104"].inputs.width = 320 |
  .["104"].inputs.height = 192 |
  .["104"].inputs.length = 5 |
  .["104"].inputs.prompt = "A red cube on a plain white table. Camera: static. Audio: silence." |
  .["9"].inputs.steps = 1 |
  .["15"].inputs.noise_seed = 20260812 |
  .["92"].inputs.filename_prefix = "smoke/minimax_h3_single_dgx_spark"
' "$workflow" > "$prompt"

jq -n --slurpfile prompt "$prompt" \
  --arg client_id "h3-smoke-$(date -u +%s)" \
  '{prompt: $prompt[0], client_id: $client_id}' |
  curl -fsS -H 'Content-Type: application/json' \
    --data-binary @- "http://127.0.0.1:$port/prompt" > "$response"

prompt_id="$(jq -er '.prompt_id' "$response")"
prompt_sha="$(sha256sum "$prompt" | awk '{print $1}')"
deadline=$(( $(date +%s) + timeout_seconds ))
while (( $(date +%s) < deadline )); do
  history="$artifact/history-$prompt_id.json"
  curl -fsS "http://127.0.0.1:$port/history/$prompt_id" > "$history"
  completed="$(jq -r --arg id "$prompt_id" '.[$id].status.completed // false' "$history")"
  status="$(jq -r --arg id "$prompt_id" '.[$id].status.status_str // "pending"' "$history")"
  [[ "$status" != error ]] || { jq . "$history" >&2; exit 1; }
  if [[ "$completed" == true ]]; then
    [[ "$status" == success ]]
    output_count="$(jq -er --arg id "$prompt_id" '
      [.[$id].outputs["92"].images[] | select(.type == "output")] | length
    ' "$history")"
    [[ "$output_count" == 1 ]]
    output_row="$(jq -er --arg id "$prompt_id" '
      [.[$id].outputs["92"].images[] | select(.type == "output")][0] |
      [.subfolder, .filename] | @tsv
    ' "$history")"
    IFS=$'\t' read -r output_subfolder output_filename <<<"$output_row"
    [[ "$output_subfolder" == smoke && -n "$output_filename" &&
       "$output_filename" != */* && "$output_filename" != *".."* ]]
    output_path="$root/output/$output_subfolder/$output_filename"
    [[ -s "$output_path" ]]
    ! grep -Fxq "$output_path" "$before"
    resolved_output="$(python3 - "$output_path" "$output_dir" <<'PY'
import sys
from pathlib import Path
path = Path(sys.argv[1]).resolve(strict=True)
root = Path(sys.argv[2]).resolve(strict=True)
if path.parent != root:
    raise SystemExit("smoke output escaped the accepted directory")
print(path)
PY
    )"
    ffmpeg="${H3_FFMPEG_BIN:-$($root/venv/bin/python -c \
      'import imageio_ffmpeg; print(imageio_ffmpeg.get_ffmpeg_exe())')}"
    [[ -x "$ffmpeg" ]]
    "$ffmpeg" -v error -i "$resolved_output" -f null -
    history_sha="$(sha256sum "$history" | awk '{print $1}')"
    output_sha="$(sha256sum "$resolved_output" | awk '{print $1}')"
    output_bytes="$(stat -c %s "$resolved_output" 2>/dev/null ||
      stat -f %z "$resolved_output")"
    jq -n \
      --arg status passed \
      --arg prompt_id "$prompt_id" \
      --arg completed_at "$(date -u +%FT%TZ)" \
      --arg manifest_sha256 "$manifest_sha" \
      --arg prompt_sha256 "$prompt_sha" \
      --arg history "$history" --arg history_sha256 "$history_sha" \
      --arg output_path "$resolved_output" --arg output_sha256 "$output_sha" \
      --argjson output_bytes "$output_bytes" \
      --argjson runtime "$runtime_identity" \
      '{status: $status, prompt_id: $prompt_id,
        completed_at: $completed_at, manifest_sha256: $manifest_sha256,
        prompt_sha256: $prompt_sha256,
        history: {path: $history, sha256: $history_sha256,
          status: "success", completed: true},
        runtime: $runtime,
        output: {path: $output_path, bytes: $output_bytes,
          sha256: $output_sha256, ffmpeg_decode: "passed"}}' |
      tee "$artifact/receipt.json"
    exit 0
  fi
  h3_assert_protected "${H3_PROTECTED_BASELINE:-}"
  sleep 5
done

printf 'smoke timed out after %s seconds, prompt_id=%s\n' "$timeout_seconds" "$prompt_id" >&2
exit 1
