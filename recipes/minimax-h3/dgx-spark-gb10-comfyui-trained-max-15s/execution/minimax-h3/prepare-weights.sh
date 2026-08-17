#!/usr/bin/env bash

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=execution/minimax-h3/lib.sh
source "$SCRIPT_DIR/lib.sh"

root=""
manifest="$H3_DEFAULT_MANIFEST"
receipt=""
curl_bin="${CURL_BIN:-curl}"
hf_bin="${HF_BIN:-}"

usage() {
  cat <<'EOF'
Usage: prepare-weights.sh --root PATH [--manifest PATH] [--receipt PATH]

Downloads the immutable manifest set. Invalid final files are retained under
artifacts/incomplete; interrupted transfers remain as .partial files and resume.
EOF
}

while (( $# )); do
  case "$1" in
    --root) root="$2"; shift 2 ;;
    --manifest) manifest="$2"; shift 2 ;;
    --receipt) receipt="$2"; shift 2 ;;
    -h|--help) usage; exit 0 ;;
    *) h3_die "unknown argument: $1" ;;
  esac
done

[[ -n "$root" ]] || h3_die "--root is required"
receipt="${receipt:-$root/artifacts/verification/$(date -u +%Y%m%dT%H%M%SZ).json}"
h3_require_command "$curl_bin"
h3_require_command sha256sum
h3_require_command jq
if [[ -z "$hf_bin" ]]; then
  hf_bin="$(command -v hf || true)"
fi
if [[ -z "$hf_bin" && -x "$HOME/.local/bin/hf" ]]; then
  hf_bin="$HOME/.local/bin/hf"
fi
h3_validate_manifest "$manifest" >/dev/null
mkdir -p "$root/models" "$root/artifacts/incomplete" "$root/artifacts/progress"
run_id="$(date -u +%Y%m%dT%H%M%SZ)"
progress="$root/artifacts/progress/$run_id.tsv"
printf 'status\tbytes\tsha256\tpath\n' > "$progress"

while IFS=$'\t' read -r source repository revision bytes digest relpath; do
  [[ -n "$source" ]] || continue
  destination="$root/models/$relpath"
  partial="${destination}.partial"
  mkdir -p "$(dirname "$destination")"

  if h3_file_matches "$destination" "$bytes" "$digest"; then
    printf 'verified\t%s\t%s\t%s\n' "$bytes" "$digest" "$relpath" >> "$progress"
    h3_log "already verified: $relpath"
    continue
  fi
  h3_quarantine_file "$root" "$destination" "$relpath" "$run_id"

  if [[ -f "$partial" ]]; then
    partial_bytes="$(stat -c %s "$partial" 2>/dev/null || stat -f %z "$partial")"
    if (( partial_bytes > bytes )); then
      h3_quarantine_file "$root" "$partial" "${relpath}.partial" "$run_id"
    fi
  fi

  url="$(h3_source_url "$source" "$repository" "$revision" "$relpath")"
  h3_log "downloading: $relpath"
  if [[ "$source" == "hf" && -n "$hf_bin" ]]; then
    hf_stage_root="$root/.downloads/hf"
    hf_stage="$hf_stage_root/$relpath"
    if ! h3_file_matches "$hf_stage" "$bytes" "$digest"; then
      h3_quarantine_file "$root" "$hf_stage" "hf-stage/$relpath" "$run_id"
      "$hf_bin" download "$repository" "$relpath" \
        --revision "$revision" --local-dir "$hf_stage_root"
    fi
    h3_file_matches "$hf_stage" "$bytes" "$digest" ||
      h3_die "Hugging Face download failed verification for $relpath"
    mv "$hf_stage" "$destination"
  else
    "$curl_bin" -fL -C - \
      --retry 20 --retry-delay 5 --retry-all-errors \
      --connect-timeout 20 --speed-time 180 --speed-limit 1048576 \
      --progress-bar --output "$partial" "$url"

    actual_bytes="$(stat -c %s "$partial" 2>/dev/null || stat -f %z "$partial")"
    [[ "$actual_bytes" == "$bytes" ]] ||
      h3_die "downloaded size mismatch for $relpath: expected=$bytes actual=$actual_bytes"
    actual_sha="$(sha256sum "$partial" | awk '{print $1}')"
    [[ "$actual_sha" == "$digest" ]] || h3_die "downloaded SHA-256 mismatch for $relpath"
    mv "$partial" "$destination"
  fi
  printf 'verified\t%s\t%s\t%s\n' "$bytes" "$digest" "$relpath" >> "$progress"
  h3_log "completed: $relpath"
done < <(h3_manifest_rows "$manifest")

"$SCRIPT_DIR/verify-weights.sh" \
  --root "$root" --manifest "$manifest" --receipt "$receipt"
