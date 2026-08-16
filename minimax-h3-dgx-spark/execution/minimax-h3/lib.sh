#!/usr/bin/env bash

set -euo pipefail

H3_SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
H3_DEFAULT_MANIFEST="$H3_SCRIPT_DIR/weights-manifest.tsv"

h3_log() {
  printf '[minimax-h3] %s\n' "$*" >&2
}

h3_die() {
  h3_log "ERROR: $*"
  exit 1
}

h3_require_command() {
  command -v "$1" >/dev/null 2>&1 || h3_die "required command is missing: $1"
}

h3_manifest_sha() {
  sha256sum "$1" | awk '{print $1}'
}

h3_manifest_rows() {
  awk -F '\t' 'NR > 1 && NF {print}' "$1"
}

h3_validate_manifest() {
  local manifest="$1"
  local header source repository revision bytes digest relpath count total

  [[ -f "$manifest" ]] || h3_die "manifest is missing: $manifest"
  IFS= read -r header < "$manifest"
  [[ "$header" == $'source\trepository\trevision\tbytes\tsha256\tpath' ]] ||
    h3_die "invalid manifest header: $manifest"

  count=0
  total=0
  while IFS=$'\t' read -r source repository revision bytes digest relpath; do
    [[ -n "$source" ]] || continue
    case "$source" in
      hf|modelscope|file) ;;
      *) h3_die "unsupported manifest source: $source" ;;
    esac
    [[ -n "$repository" && -n "$revision" ]] || h3_die "manifest source identity is incomplete"
    [[ "$bytes" =~ ^[0-9]+$ ]] || h3_die "invalid byte count for $relpath: $bytes"
    [[ "$digest" =~ ^[0-9a-f]{64}$ ]] || h3_die "invalid SHA-256 for $relpath"
    [[ -n "$relpath" && "$relpath" != /* && "$relpath" != *".."* ]] ||
      h3_die "unsafe manifest path: $relpath"
    count=$((count + 1))
    total=$((total + bytes))
  done < <(h3_manifest_rows "$manifest")

  (( count > 0 )) || h3_die "manifest contains no files"
  printf '%s\t%s\n' "$count" "$total"
}

h3_source_url() {
  local source="$1" repository="$2" revision="$3" relpath="$4"
  case "$source" in
    hf)
      printf 'https://huggingface.co/%s/resolve/%s/%s?download=true\n' \
        "$repository" "$revision" "$relpath"
      ;;
    modelscope)
      printf 'https://modelscope.cn/models/%s/resolve/%s/%s\n' \
        "$repository" "$revision" "$relpath"
      ;;
    file)
      printf '%s/%s\n' "${repository%/}" "$relpath"
      ;;
    *)
      h3_die "unsupported source: $source"
      ;;
  esac
}

h3_file_matches() {
  local path="$1" expected_bytes="$2" expected_sha="$3" actual_bytes actual_sha
  [[ -f "$path" ]] || return 1
  actual_bytes="$(stat -c %s "$path" 2>/dev/null || stat -f %z "$path")"
  [[ "$actual_bytes" == "$expected_bytes" ]] || return 1
  actual_sha="$(sha256sum "$path" | awk '{print $1}')"
  [[ "$actual_sha" == "$expected_sha" ]]
}

h3_quarantine_file() {
  local root="$1" path="$2" relpath="$3" run_id="$4" target
  [[ -e "$path" ]] || return 0
  target="$root/artifacts/incomplete/$run_id/$relpath"
  mkdir -p "$(dirname "$target")"
  mv "$path" "$target"
  h3_log "quarantined incomplete file: $relpath"
}
