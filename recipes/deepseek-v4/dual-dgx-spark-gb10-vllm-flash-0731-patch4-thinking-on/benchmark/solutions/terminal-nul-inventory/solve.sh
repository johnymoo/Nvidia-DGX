#!/usr/bin/env bash
set -euo pipefail

root=${1:?"usage: solve.sh INPUT_DIR"}
tree=$root/tree
[[ -d $tree ]] || { printf '%s\n' "input/tree is missing" >&2; exit 2; }
tmp=$(mktemp "${TMPDIR:-/tmp}/terminal-inventory.XXXXXX")
trap 'rm -f "$tmp"' EXIT

json_escape() {
  awk -v value="$1" 'BEGIN { gsub(/\\/, "\\\\", value); gsub(/"/, "\\\"", value); gsub(/\t/, "\\t", value); gsub(/\r/, "\\r", value); printf "%s", value }'
}

while IFS= read -r -d '' file; do
  rel=${file#"$tree"/}
  bytes=$(wc -c < "$file" | tr -d '[:space:]')
  printf '%s\t%s\n' "$(json_escape "$rel")" "$bytes"
done < <(find "$tree" -type f -print0) | LC_ALL=C sort > "$tmp"

{
  printf '{"files":['
  first=1
  while IFS=$'\t' read -r path bytes; do
    [[ $first -eq 1 ]] || printf ','
    printf '{"path":"%s","bytes":%s}' "$path" "$bytes"
    first=0
  done < "$tmp"
  printf ']}\n'
} > inventory.json
