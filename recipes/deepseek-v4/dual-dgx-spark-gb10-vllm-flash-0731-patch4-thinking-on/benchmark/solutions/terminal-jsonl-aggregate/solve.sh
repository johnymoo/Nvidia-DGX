#!/usr/bin/env bash
set -euo pipefail

root=${1:?"usage: solve.sh INPUT_DIR"}
input=$root/requests.jsonl
[[ -f $input ]] || { printf '%s\n' "requests.jsonl is missing" >&2; exit 2; }
tmp=$(mktemp "${TMPDIR:-/tmp}/terminal-jsonl.XXXXXX")
trap 'rm -f "$tmp"' EXIT
rm -f aggregate.json

if ! awk '
function invalid() { print "invalid JSONL row " NR > "/dev/stderr"; bad=1; exit 2 }
{
  compact=$0; gsub(/[ \t\r]/, "", compact)
  if (compact ~ /^\{"status":[0-9]+,"latency_ms":[0-9]+\}$/) {
    value=compact; sub(/^\{"status":/, "", value); split(value, part, /,"latency_ms":/); status=part[1]; latency=part[2]; sub(/\}$/, "", latency)
  } else if (compact ~ /^\{"latency_ms":[0-9]+,"status":[0-9]+\}$/) {
    value=compact; sub(/^\{"latency_ms":/, "", value); split(value, part, /,"status":/); latency=part[1]; status=part[2]; sub(/\}$/, "", status)
  } else invalid()
  if (status ~ /^0/ || latency !~ /^(0|[1-9][0-9]*)$/ || status < 100 || status > 599) invalid()
  rows++; status_count[int(status / 100) "xx"]++; latency_sum += latency
  if (latency < 100) latency_count["lt_100"]++
  else if (latency < 500) latency_count["100_499"]++
  else latency_count["500_plus"]++
}
END {
  if (!bad) printf "{\"rows\":%d,\"status_buckets\":{\"1xx\":%d,\"2xx\":%d,\"3xx\":%d,\"4xx\":%d,\"5xx\":%d},\"latency_buckets\":{\"lt_100\":%d,\"100_499\":%d,\"500_plus\":%d},\"latency_sum_ms\":%.0f}\n", rows, status_count["1xx"], status_count["2xx"], status_count["3xx"], status_count["4xx"], status_count["5xx"], latency_count["lt_100"], latency_count["100_499"], latency_count["500_plus"], latency_sum
}
' "$input" > "$tmp"; then
  rm -f "$tmp"
  exit 2
fi
mv "$tmp" aggregate.json
