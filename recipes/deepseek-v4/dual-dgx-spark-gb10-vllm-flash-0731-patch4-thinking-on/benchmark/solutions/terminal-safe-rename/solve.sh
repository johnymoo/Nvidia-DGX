#!/usr/bin/env bash
set -euo pipefail

root=${1:?"usage: solve.sh INPUT_DIR [--apply]"}
apply=${2:-}
[[ -d $root/media && ( -z $apply || $apply == --apply ) ]] || { printf '%s\n' "invalid input or option" >&2; exit 2; }
media=$root/media
tmp=$(mktemp "${TMPDIR:-/tmp}/terminal-rename.XXXXXX")
trap 'rm -f "$tmp" "$tmp.raw" "$tmp.used" "$tmp.plan" "$tmp.moves"' EXIT
: > "$tmp.raw"
: > "$tmp.used"
: > "$tmp.plan"

normalize() {
  local base=$1 stem ext slug
  stem=$base
  ext=
  if [[ $base == *.* && $base != .* ]]; then
    stem=${base%.*}
    ext=.${base##*.}
  fi
  slug=$(printf '%s' "$stem" | LC_ALL=C tr '[:upper:]' '[:lower:]' | sed -E 's/[^a-z0-9]+/-/g; s/^-+//; s/-+$//')
  [[ -n $slug ]] || slug=file
  ext=$(printf '%s' "$ext" | LC_ALL=C tr '[:upper:]' '[:lower:]')
  printf '%s%s' "$slug" "$ext"
}

while IFS= read -r -d '' file; do
  rel=${file#"$media"/}
  dir=${rel%/*}
  [[ $dir == "$rel" ]] && dir=
  base=${rel##*/}
  candidate=$(normalize "$base")
  [[ -z $dir ]] || candidate=$dir/$candidate
  printf '%s\t%s\n' "$rel" "$candidate" >> "$tmp.raw"
done < <(find "$media" -type f -print0 | LC_ALL=C sort -z 2>/dev/null || find "$media" -type f -print0)

while IFS=$'\t' read -r from candidate; do
  [[ $from == "$candidate" ]] && printf '%s\n' "$candidate" >> "$tmp.used"
done < "$tmp.raw"

while IFS=$'\t' read -r from candidate; do
  [[ $from == "$candidate" ]] && continue
  dest=$candidate
  number=2
  stem=${candidate%.*}
  ext=
  if [[ $candidate == *.* && ${candidate##*/} != .* ]]; then
    stem=${candidate%.*}
    ext=.${candidate##*.}
  fi
  while grep -Fqx -- "$dest" "$tmp.used"; do
    dest=${stem}-${number}${ext}
    number=$((number + 1))
  done
  printf '%s\n' "$dest" >> "$tmp.used"
  printf '%s\t%s\n' "$from" "$dest" >> "$tmp.plan"
done < <(LC_ALL=C sort "$tmp.raw")

json_escape() {
  awk -v value="$1" 'BEGIN { gsub(/\\/, "\\\\", value); gsub(/"/, "\\\"", value); gsub(/\t/, "\\t", value); printf "%s", value }'
}
{
  printf '{"operations":['
  first=1
  while IFS=$'\t' read -r from to; do
    [[ $first -eq 1 ]] || printf ','
    printf '{"from":"%s","to":"%s"}' "$(json_escape "$from")" "$(json_escape "$to")"
    first=0
  done < "$tmp.plan"
  printf ']}\n'
} > rename-plan.json
awk -F '\t' '{ print $2 "\\t" $1 }' "$tmp.plan" > rollback.tsv

[[ $apply == --apply ]] || exit 0
: > "$tmp.moves"
counter=0
while IFS=$'\t' read -r from to; do
  counter=$((counter + 1))
  staging=$media/.rename-staging-$$-$counter
  mv "$media/$from" "$staging"
  printf '%s\t%s\n' "$staging" "$to" >> "$tmp.moves"
done < "$tmp.plan"
while IFS=$'\t' read -r staging to; do
  mkdir -p "$(dirname "$media/$to")"
  [[ ! -e $media/$to ]] || { printf '%s\n' "destination collision: $to" >&2; exit 2; }
  mv "$staging" "$media/$to"
done < "$tmp.moves"
