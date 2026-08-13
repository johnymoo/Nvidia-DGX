#!/usr/bin/env bash
set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "$SCRIPT_DIR/report-lib.sh"
ROOT="${H3_BENCH_ROOT:-$HOME/minimax-h3-benchmark}"
PORT="${H3_REPORT_PORT:-8890}"
PYTHON="${H3_REPORT_PYTHON:-python3}"
mkdir -p "$ROOT/run" "$ROOT/logs"
[[ -f "$ROOT/site/index.html" && -f "$ROOT/site/evidence.html" ]] || { echo 'site is not rendered' >&2; exit 1; }
if [[ -f "$ROOT/run/report-process.json" ]]; then
  state="$(report_observe "$ROOT" "$PORT")"
  jq -e '.running and .identity_match and .listener_match and .http_code == "200"' <<<"$state" >/dev/null && { jq . <<<"$state"; exit 0; }
  jq -e '.running' <<<"$state" >/dev/null && { echo 'existing report identity mismatch' >&2; exit 1; }
fi
ss -H -ltn "sport = :$PORT" | grep -q . && { echo "port $PORT is already in use" >&2; exit 1; }
python_path="$(command -v "$PYTHON")"
nohup "$python_path" -m http.server "$PORT" --bind 0.0.0.0 --directory "$ROOT/site" \
  >> "$ROOT/logs/report.log" 2>&1 &
pid=$!
for _ in $(seq 1 50); do
  [[ -r "/proc/$pid/stat" ]] || { echo 'report process exited' >&2; exit 1; }
  code="$(curl -sS -o /dev/null -w '%{http_code}' --max-time 2 "http://127.0.0.1:$PORT/" || true)"
  [[ "$code" == 200 ]] && break
  sleep .2
done
start_ticks="$(python3 - "$pid" <<'PY'
from pathlib import Path
import sys
s=Path(f'/proc/{sys.argv[1]}/stat').read_text(); print(s[s.rfind(')')+2:].split()[19])
PY
)"
jq -n --argjson pid "$pid" --argjson start_ticks "$start_ticks" \
  --arg boot_id "$(cat /proc/sys/kernel/random/boot_id)" --arg python "$python_path" \
  --arg root "$ROOT" --argjson port "$PORT" --arg started_at "$(date -u +%FT%TZ)" \
  '{pid:$pid,start_ticks:$start_ticks,boot_id:$boot_id,python:$python,root:$root,port:$port,started_at:$started_at}' \
  > "$ROOT/run/report-process.json.tmp"
mv "$ROOT/run/report-process.json.tmp" "$ROOT/run/report-process.json"
state="$(report_observe "$ROOT" "$PORT")"
jq -e '.running and .identity_match and .listener_match and .http_code == "200"' <<<"$state" >/dev/null
jq . <<<"$state"
