#!/usr/bin/env bash
set -euo pipefail

root=${1:?"usage: solve.sh INPUT_DIR"}
input=$root/requests.jsonl
[[ -f $input ]] || { printf '%s\n' "requests.jsonl is missing" >&2; exit 2; }
tmp=$(mktemp "${TMPDIR:-/tmp}/terminal-jsonl.XXXXXX")
trap 'rm -f "$tmp"' EXIT
rm -f aggregate.json

rows=0 s1=0 s2=0 s3=0 s4=0 s5=0 lt100=0 from100=0 from500=0 latency_sum=0
while IFS= read -r line || [[ -n $line ]]; do
  compact=${line//$'\r'/}
  compact=${compact//$'\t'/}
  compact=${compact// /}
  if [[ $compact =~ ^\{\"status\":([0-9]+),\"latency_ms\":([0-9]+)\}$ ]]; then
    status=${BASH_REMATCH[1]}; latency=${BASH_REMATCH[2]}
  elif [[ $compact =~ ^\{\"latency_ms\":([0-9]+),\"status\":([0-9]+)\}$ ]]; then
    latency=${BASH_REMATCH[1]}; status=${BASH_REMATCH[2]}
  else
    printf 'invalid JSONL row %d\n' "$((rows + 1))" >&2
    exit 2
  fi
  [[ $status =~ ^(0|[1-9][0-9]*)$ && $latency =~ ^(0|[1-9][0-9]*)$ ]] || exit 2
  (( status >= 100 && status <= 599 )) || exit 2
  ((rows += 1)); ((latency_sum += latency))
  case $((status / 100)) in
    1) ((s1 += 1));; 2) ((s2 += 1));; 3) ((s3 += 1));; 4) ((s4 += 1));; 5) ((s5 += 1));;
  esac
  if ((latency < 100)); then ((lt100 += 1))
  elif ((latency < 500)); then ((from100 += 1))
  else ((from500 += 1))
  fi
done < "$input"
printf '{"rows":%d,"status_buckets":{"1xx":%d,"2xx":%d,"3xx":%d,"4xx":%d,"5xx":%d},"latency_buckets":{"lt_100":%d,"100_499":%d,"500_plus":%d},"latency_sum_ms":%d}\n' \
  "$rows" "$s1" "$s2" "$s3" "$s4" "$s5" "$lt100" "$from100" "$from500" "$latency_sum" > "$tmp"
mv "$tmp" aggregate.json
