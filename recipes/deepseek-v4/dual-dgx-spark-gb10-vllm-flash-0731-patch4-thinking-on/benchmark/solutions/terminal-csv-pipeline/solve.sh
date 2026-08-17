#!/usr/bin/env bash
set -euo pipefail

root=${1:?"usage: solve.sh INPUT_DIR"}
input=$root/records.csv
[[ -f $input ]] || { printf '%s\n' "records.csv is missing" >&2; exit 2; }
tmp=$(mktemp "${TMPDIR:-/tmp}/terminal-csv.XXXXXX")
trap 'rm -f "$tmp" "$tmp.rows"' EXIT
rm -f summary.csv

if ! awk '
function parse(line, out,    i,c,nextc,field,n,quoted,j) {
  for (j in out) delete out[j]
  field=""; n=0; quoted=0
  for (i=1; i<=length(line); i++) {
    c=substr(line,i,1)
    if (quoted) {
      if (c == "\"") {
        nextc=substr(line,i+1,1)
        if (nextc == "\"") { field=field "\""; i++ }
        else quoted=0
      } else field=field c
    } else if (c == "\"") {
      if (field != "") return -1
      quoted=1
    } else if (c == ",") { out[++n]=field; field="" }
    else field=field c
  }
  if (quoted) return -1
  out[++n]=field
  return n
}
function invalid(message) { print message > "/dev/stderr"; bad=1; exit 2 }
{
  sub(/\r$/, "", $0)
  count=parse($0, field)
  if (count != 4) invalid("malformed CSV row")
  if (NR == 1) {
    if (field[1] != "account" || field[2] != "team" || field[3] != "amount_cents" || field[4] != "status") invalid("wrong CSV header")
    next
  }
  if (field[1] == "" || field[2] == "" || field[3] !~ /^(0|[1-9][0-9]*)$/ || field[4] == "") invalid("invalid CSV value")
  if (field[4] == "approved") { total[field[2]] += field[3]; rows[field[2]]++ }
}
END { if (!bad) for (team in total) printf "%s\t%.0f\t%d\n", team, total[team], rows[team] }
' "$input" > "$tmp.rows"; then
  rm -f "$tmp.rows"
  exit 2
fi

{
  printf 'team,total_cents,rows\n'
  LC_ALL=C sort -t $'\t' -k1,1 "$tmp.rows" | awk -F '\t' '
    function csv(value, copy) { copy=value; gsub(/"/, "\"\"", copy); return copy ~ /[,\"]/ ? "\"" copy "\"" : copy }
    { printf "%s,%s,%s\n", csv($1), $2, $3 }
  '
} > "$tmp"
mv "$tmp" summary.csv
