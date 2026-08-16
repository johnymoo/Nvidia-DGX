#!/usr/bin/env bash
set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "$SCRIPT_DIR/report-lib.sh"
ROOT="${H3_BENCH_ROOT:-$HOME/minimax-h3-benchmark}"
PORT="${H3_REPORT_PORT:-8890}"
state="$(report_observe "$ROOT" "$PORT")"
jq -e '.running == false' <<<"$state" >/dev/null && { rm -f "$ROOT/run/report-process.json"; jq . <<<"$state"; exit 0; }
jq -e '.identity_match and .listener_match' <<<"$state" >/dev/null || { echo 'refusing to stop mismatched process' >&2; exit 1; }
pid="$(jq -r .pid <<<"$state")"
ticks="$(jq -r .start_ticks <<<"$state")"
kill -TERM "$pid"
for _ in $(seq 1 100); do
  [[ ! -r "/proc/$pid/stat" ]] && break
  current="$(python3 - "$pid" <<'PY'
from pathlib import Path
import sys
p=Path(f'/proc/{sys.argv[1]}/stat')
if p.exists():
 s=p.read_text(); print(s[s.rfind(')')+2:].split()[19])
PY
)"
  [[ "$current" != "$ticks" ]] && break
  sleep .1
done
[[ ! -r "/proc/$pid/stat" ]] || { echo 'report did not stop' >&2; exit 1; }
rm -f "$ROOT/run/report-process.json"
report_observe "$ROOT" "$PORT"
