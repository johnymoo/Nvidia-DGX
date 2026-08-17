#!/usr/bin/env bash
set -euo pipefail

root=${1:?"usage: solve.sh INPUT_DIR"}
tree=$root/tree
manifest=$root/checksums.txt
[[ -d $tree && -f $manifest ]] || { printf '%s\n' "tree or checksums.txt is missing" >&2; exit 2; }
tmp=$(mktemp "${TMPDIR:-/tmp}/terminal-checksum.XXXXXX")
trap 'rm -f "$tmp" "$tmp.seen" "$tmp.matching" "$tmp.missing" "$tmp.changed" "$tmp.unexpected"' EXIT
: > "$tmp.seen"; : > "$tmp.matching"; : > "$tmp.missing"; : > "$tmp.changed"; : > "$tmp.unexpected"
rm -f audit.json

sha256() {
  if command -v sha256sum >/dev/null 2>&1; then sha256sum "$1" | awk '{print $1}'
  else shasum -a 256 "$1" | awk '{print $1}'
  fi
}
safe_path() {
  local path=$1 part
  [[ -n $path && $path != /* && $path != -* && $path != *'//' ]] || return 1
  IFS=/ read -r -a parts <<< "$path"
  for part in "${parts[@]}"; do [[ -n $part && $part != . && $part != .. && $part != -* ]] || return 1; done
}

while IFS= read -r line || [[ -n $line ]]; do
  [[ $line == *"  "* ]] || { printf '%s\n' "malformed checksum line" >&2; exit 2; }
  expected=${line%%  *}
  path=${line#*  }
  [[ $expected =~ ^[0-9a-f]{64}$ ]] && safe_path "$path" || { printf '%s\n' "unsafe checksum line" >&2; exit 2; }
  grep -Fqx -- "$path" "$tmp.seen" && { printf '%s\n' "duplicate checksum path" >&2; exit 2; }
  printf '%s\n' "$path" >> "$tmp.seen"
  if [[ ! -f $tree/$path || -L $tree/$path ]]; then
    printf '%s\n' "$path" >> "$tmp.missing"
  elif [[ $(sha256 "$tree/$path") == "$expected" ]]; then
    printf '%s\n' "$path" >> "$tmp.matching"
  else
    printf '%s\n' "$path" >> "$tmp.changed"
  fi
done < "$manifest"

while IFS= read -r -d '' file; do
  rel=${file#"$tree"/}
  grep -Fqx -- "$rel" "$tmp.seen" || printf '%s\n' "$rel" >> "$tmp.unexpected"
done < <(find "$tree" -type f -print0)

json_escape() { awk -v value="$1" 'BEGIN { gsub(/\\/, "\\\\", value); gsub(/"/, "\\\"", value); gsub(/\t/, "\\t", value); gsub(/\r/, "\\r", value); printf "%s", value }'; }
json_array() {
  local file=$1 value first=1
  printf '['
  while IFS= read -r value; do
    [[ $first -eq 1 ]] || printf ','
    printf '"%s"' "$(json_escape "$value")"
    first=0
  done < <(LC_ALL=C sort "$file")
  printf ']'
}
{
  printf '{"matching":'; json_array "$tmp.matching"
  printf ',"missing":'; json_array "$tmp.missing"
  printf ',"changed":'; json_array "$tmp.changed"
  printf ',"unexpected":'; json_array "$tmp.unexpected"
  printf '}\n'
} > audit.json
