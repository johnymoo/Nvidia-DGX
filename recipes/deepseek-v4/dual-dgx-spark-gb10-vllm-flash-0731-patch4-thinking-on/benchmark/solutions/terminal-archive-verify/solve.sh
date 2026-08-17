#!/usr/bin/env bash
set -euo pipefail

root=${1:?"usage: solve.sh INPUT_DIR"}
archive=$root/bundle.tar
manifest=$root/manifest.tsv
[[ -f $archive && -f $manifest ]] || { printf '%s\n' "bundle.tar or manifest.tsv is missing" >&2; exit 2; }
tmp=$(mktemp "${TMPDIR:-/tmp}/terminal-archive.XXXXXX")
trap 'rm -f "$tmp" "$tmp.entries" "$tmp.manifest" "$tmp.results" "$tmp.member"' EXIT
rm -rf extracted
mkdir extracted
tar -tf "$archive" > "$tmp.entries"
: > "$tmp.manifest"; : > "$tmp.results"
errors=0

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
record() { printf '%s\t%s\t%s\n' "$1" "$2" "$3" >> "$tmp.results"; }

while IFS= read -r line || [[ -n $line ]]; do
  if [[ $line != *$'\t'* ]]; then record R "$line" malformed-manifest; errors=1; continue; fi
  expected=${line%%$'\t'*}
  path=${line#*$'\t'}
  if [[ ! $expected =~ ^[0-9a-f]{64}$ ]] || ! safe_path "$path" || grep -Fqx -- "$path" "$tmp.manifest"; then
    record R "$path" unsafe-manifest; errors=1; continue
  fi
  printf '%s\n' "$path" >> "$tmp.manifest"
  if ! grep -Fqx -- "$path" "$tmp.entries"; then record R "$path" missing-member; errors=1; continue; fi
  type=$(tar -tvf "$archive" "$path" | awk 'NR == 1 { print substr($0, 1, 1) }')
  if [[ $type != - ]]; then record R "$path" unsupported-member; errors=1; continue; fi
  if ! tar -xOf "$archive" "$path" > "$tmp.member"; then record R "$path" extract-failed; errors=1; continue; fi
  if [[ $(sha256 "$tmp.member") != "$expected" ]]; then record R "$path" checksum-mismatch; errors=1; continue; fi
  mkdir -p "extracted/$(dirname "$path")"
  cat "$tmp.member" > "extracted/$path"
  record V "$path" verified
done < "$manifest"

while IFS= read -r path; do
  if ! safe_path "$path"; then record R "$path" unsafe-member; errors=1
  elif ! grep -Fqx -- "$path" "$tmp.manifest"; then record R "$path" unapproved-member
  fi
done < "$tmp.entries"

json_escape() { awk -v value="$1" 'BEGIN { gsub(/\\/, "\\\\", value); gsub(/"/, "\\\"", value); gsub(/\t/, "\\t", value); printf "%s", value }'; }
array_for() {
  local tag=$1 first=1 path reason
  printf '['
  while IFS=$'\t' read -r _ path reason; do
    [[ $first -eq 1 ]] || printf ','
    printf '{"path":"%s","reason":"%s"}' "$(json_escape "$path")" "$(json_escape "$reason")"
    first=0
  done < <(awk -F '\t' -v tag="$tag" '$1 == tag { print }' "$tmp.results" | LC_ALL=C sort -t $'\t' -k2,2 -k3,3)
  printf ']'
}
{
  printf '{"verified":'; array_for V
  printf ',"rejected":'; array_for R
  printf '}\n'
} > verification.json
[[ $errors -eq 0 ]]
