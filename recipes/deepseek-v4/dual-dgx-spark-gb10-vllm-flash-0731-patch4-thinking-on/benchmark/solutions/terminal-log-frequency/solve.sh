#!/usr/bin/env bash
set -euo pipefail

root=${1:?"usage: solve.sh INPUT_DIR"}
[[ -d $root ]] || { printf '%s\n' "input directory is missing" >&2; exit 2; }
tmp=$(mktemp "${TMPDIR:-/tmp}/terminal-log.XXXXXX")
trap 'rm -f "$tmp" "$tmp.sorted"' EXIT

while IFS= read -r -d '' file; do
  while IFS= read -r line || [[ -n $line ]]; do
    [[ $line == *"ERROR "* ]] || continue
    signature=${line#*ERROR }
    signature=$(printf '%s' "$signature" | sed -E \
      -e 's/(user_id|request_id|trace_id)=[^[:space:]]+/\1=?/g' \
      -e 's/latency_ms=[0-9]+/latency_ms=?/g')
    printf '%s\n' "$signature"
  done < "$file"
done < <(find "$root" -type f -name 'app.log*' -print0) > "$tmp"

LC_ALL=C sort "$tmp" | uniq -c | LC_ALL=C sort -k1,1nr -k2,2 > "$tmp.sorted"
{
  printf '{"errors":['
  first=1
  while IFS= read -r line; do
    line=${line#"${line%%[![:space:]]*}"}
    count=${line%% *}
    signature=$(printf '%s' "$line" | sed 's/^ *[0-9][0-9]* //')
    escaped=$(awk -v value="$signature" 'BEGIN { gsub(/\\/, "\\\\", value); gsub(/"/, "\\\"", value); gsub(/\t/, "\\t", value); gsub(/\r/, "\\r", value); printf "%s", value }')
    [[ $first -eq 1 ]] || printf ','
    printf '{"signature":"%s","count":%s}' "$escaped" "$count"
    first=0
  done < "$tmp.sorted"
  printf ']}\n'
} > report.json
