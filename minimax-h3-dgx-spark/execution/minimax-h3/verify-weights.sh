#!/usr/bin/env bash

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=execution/minimax-h3/lib.sh
source "$SCRIPT_DIR/lib.sh"

root=""
manifest="$H3_DEFAULT_MANIFEST"
receipt=""

usage() {
  cat <<'EOF'
Usage: verify-weights.sh --root PATH [--manifest PATH] [--receipt PATH]

Without --receipt this command is read-only. Verification always checks every
file's exact byte size and SHA-256 digest.
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
h3_require_command sha256sum
h3_require_command jq
summary="$(h3_validate_manifest "$manifest")"
expected_count="${summary%%$'\t'*}"
expected_total="${summary#*$'\t'}"
manifest_sha="$(h3_manifest_sha "$manifest")"
run_id="$(date -u +%Y%m%dT%H%M%SZ)"
actual_file="$(mktemp)"
trap 'rm -f "$actual_file"' EXIT
failures=0

while IFS=$'\t' read -r source repository revision bytes digest relpath; do
  [[ -n "$source" ]] || continue
  path="$root/models/$relpath"
  if [[ ! -f "$path" ]]; then
    h3_log "missing: $relpath"
    failures=$((failures + 1))
    continue
  fi
  actual_bytes="$(stat -c %s "$path" 2>/dev/null || stat -f %z "$path")"
  if [[ "$actual_bytes" != "$bytes" ]]; then
    h3_log "size mismatch: $relpath expected=$bytes actual=$actual_bytes"
    failures=$((failures + 1))
    continue
  fi
  actual_sha="$(sha256sum "$path" | awk '{print $1}')"
  if [[ "$actual_sha" != "$digest" ]]; then
    h3_log "SHA-256 mismatch: $relpath"
    failures=$((failures + 1))
    continue
  fi
  read -r device inode mtime_ns ctime_ns < <(
    python3 - "$path" <<'PY'
import os
import sys
stat = os.stat(sys.argv[1])
print(stat.st_dev, stat.st_ino, stat.st_mtime_ns, stat.st_ctime_ns)
PY
  )
  printf '%s\t%s\t%s\t%s\t%s\t%s\t%s\n' \
    "$relpath" "$bytes" "$digest" "$device" "$inode" "$mtime_ns" "$ctime_ns" \
    >> "$actual_file"
  h3_log "verified: $relpath"
done < <(h3_manifest_rows "$manifest")

if (( failures > 0 )); then
  h3_die "verification failed for $failures file(s)"
fi

actual_count="$(wc -l < "$actual_file" | tr -d ' ')"
actual_total="$(awk -F '\t' '{sum += $2} END {printf "%.0f", sum}' "$actual_file")"
[[ "$actual_count" == "$expected_count" ]] || h3_die "verified file count mismatch"
[[ "$actual_total" == "$expected_total" ]] || h3_die "verified byte total mismatch"

if [[ -n "$receipt" ]]; then
  mkdir -p "$(dirname "$receipt")"
    files_json="$(jq -Rn '[inputs | split("\t") | {path: .[0],
      bytes: (.[1] | tonumber), sha256: .[2], device: (.[3] | tonumber),
      inode: (.[4] | tonumber), mtime_ns: (.[5] | tonumber),
      ctime_ns: (.[6] | tonumber)}]' < "$actual_file")"
  tmp_receipt="${receipt}.tmp.$$"
  jq -n \
    --arg status passed \
    --arg host "$(hostname)" \
    --arg verified_at "$(date -u +%Y-%m-%dT%H:%M:%SZ)" \
    --arg root "$root" \
    --arg manifest_sha256 "$manifest_sha" \
    --argjson file_count "$actual_count" \
    --argjson total_bytes "$actual_total" \
    --argjson files "$files_json" \
    '{status: $status, host: $host, verified_at: $verified_at, root: $root,
      manifest_sha256: $manifest_sha256, file_count: $file_count,
      total_bytes: $total_bytes, files: $files}' > "$tmp_receipt"
  mv "$tmp_receipt" "$receipt"
  h3_log "wrote receipt: $receipt"
fi

printf 'passed\t%s\t%s\t%s\n' "$manifest_sha" "$actual_count" "$actual_total"
