#!/usr/bin/env bash
set -euo pipefail

root=${1:?"usage: solve.sh INPUT_DIR"}
tree=$root/tree
[[ -d $tree ]] || { printf '%s\n' "input/tree is missing" >&2; exit 2; }
tmp=$(mktemp "${TMPDIR:-/tmp}/terminal-mode.XXXXXX")
trap 'rm -f "$tmp"' EXIT
mode_of() { stat -c '%a' "$1" 2>/dev/null || stat -f '%Lp' "$1"; }

while IFS= read -r -d '' path; do
  rel=${path#"$tree"}
  [[ -n $rel ]] || rel=.
  rel=${rel#/}
  if [[ -d $path ]]; then kind=directory; target=0750
  else kind=file; [[ $path == *.sh ]] && target=0750 || target=0640
  fi
  raw=$(mode_of "$path")
  before=$(printf '%04o' "$((8#$raw))")
  if [[ $before == "$target" ]]; then action=ok
  else chmod "$target" "$path"; action=fixed
  fi
  printf '%s\t%s\t%s\t%s\t%s\n' "$rel" "$kind" "$before" "$target" "$action"
done < <(find "$tree" \( -type d -o -type f \) -print0) | LC_ALL=C sort > "$tmp"
{
  printf 'path\tkind\tbefore\tafter\taction\n'
  cat "$tmp"
} > permission-report.tsv
