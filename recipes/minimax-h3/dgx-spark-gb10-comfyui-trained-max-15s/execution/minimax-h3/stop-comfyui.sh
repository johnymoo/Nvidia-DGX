#!/usr/bin/env bash

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=execution/minimax-h3/runtime-lib.sh
source "$SCRIPT_DIR/runtime-lib.sh"

root=""
port="${H3_PORT:-8188}"

while (( $# )); do
  case "$1" in
    --root) root="$2"; shift 2 ;;
    --port) port="$2"; shift 2 ;;
    *) printf 'unknown argument: %s\n' "$1" >&2; exit 1 ;;
  esac
done

[[ -n "$root" ]] || { printf '%s\n' '--root is required' >&2; exit 1; }

pidfile="$root/run/comfyui.pid"
process_file="$root/run/comfyui-process.json"
observation="$(h3_process_observation "$root" "$port")"
if [[ "$(jq -r .process_exists <<<"$observation")" == false &&
      "$(jq -r '.listener_pids | length' <<<"$observation")" == 0 ]]; then
  rm -f "$pidfile" "$process_file"
  printf '%s\n' 'not running'
  exit 0
fi
[[ "$(jq -r .running <<<"$observation")" == true ]] || {
  jq . <<<"$observation" >&2
  printf '%s\n' 'refusing to stop an unverified process or listener' >&2
  exit 1
}
pid="$(jq -r .pid <<<"$observation")"
start_ticks="$(jq -r .start_ticks <<<"$observation")"

kill -TERM "$pid"
for _ in $(seq 1 60); do
  current_ticks="$(python3 - "$H3_PROC_ROOT" "$pid" <<'PY'
import sys
from pathlib import Path
try:
    value = Path(sys.argv[1], sys.argv[2], "stat").read_text()
    print(value[value.rfind(")") + 2:].split()[19])
except OSError:
    print("")
PY
  )"
  [[ "$current_ticks" == "$start_ticks" ]] || break
  sleep 1
done
if [[ -r "$H3_PROC_ROOT/$pid/stat" ]] && [[ "$(python3 - "$H3_PROC_ROOT" "$pid" <<'PY'
import sys
from pathlib import Path
value = Path(sys.argv[1], sys.argv[2], "stat").read_text()
print(value[value.rfind(")") + 2:].split()[19])
PY
)" == "$start_ticks" ]]; then
  printf 'pid %s did not stop after SIGTERM\n' "$pid" >&2
  exit 1
fi
if "$H3_SS_BIN" -H -ltnp "sport = :$port" | grep -q .; then
  printf 'port %s remains occupied after stopping pid %s\n' "$port" "$pid" >&2
  exit 1
fi
rm -f "$pidfile" "$process_file"
printf 'stopped pid=%s\n' "$pid"
protected="$(h3_protected_status "${H3_PROTECTED_BASELINE:-}")"
if [[ "$(jq -r .matches <<<"$protected")" != true ]]; then
  jq . <<<"$protected" >&2
  printf '%s\n' 'protected service baseline mismatch after safe H3 shutdown' >&2
  exit 1
fi
