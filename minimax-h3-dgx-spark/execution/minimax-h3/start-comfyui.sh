#!/usr/bin/env bash

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=execution/minimax-h3/runtime-lib.sh
source "$SCRIPT_DIR/runtime-lib.sh"

root=""
listen="${H3_LISTEN:-0.0.0.0}"
port="${H3_PORT:-8188}"
reserve_vram="${H3_RESERVE_VRAM:-8}"

while (( $# )); do
  case "$1" in
    --root) root="$2"; shift 2 ;;
    --listen) listen="$2"; shift 2 ;;
    --port) port="$2"; shift 2 ;;
    *) printf 'unknown argument: %s\n' "$1" >&2; exit 1 ;;
  esac
done

[[ -n "$root" ]] || { printf '%s\n' '--root is required' >&2; exit 1; }

comfy="$root/comfy/ComfyUI"
python="$root/venv/bin/python"
pidfile="$root/run/comfyui.pid"
log="$root/logs/comfyui.log"
receipt="$root/artifacts/verification/latest.json"
manifest="$root/execution/minimax-h3/weights-manifest.tsv"
manifest_sha="$(sha256sum "$manifest" | awk '{print $1}')"

jq -e --arg manifest "$manifest_sha" \
  '.status == "passed" and .file_count == 11 and
   .total_bytes == 176195310067 and .manifest_sha256 == $manifest' \
  "$receipt" >/dev/null
h3_assert_weight_fingerprints "$root" "$receipt" "$manifest"
[[ -x "$python" && -f "$comfy/main.py" && -f "$root/extra_model_paths.yaml" ]]
h3_assert_protected "${H3_PROTECTED_BASELINE:-}"

mkdir -p "$root/run" "$root/logs" "$root/output" "$root/input" "$root/user"

argv=(
  "$python" "$comfy/main.py"
  --listen "$listen" --port "$port" --reserve-vram "$reserve_vram"
  --extra-model-paths-config "$root/extra_model_paths.yaml"
  --input-directory "$root/input"
  --output-directory "$root/output"
  --user-directory "$root/user"
  --database-url "sqlite:///$root/user/comfyui.db"
)

observation="$(h3_process_observation "$root" "$port")"
if [[ "$(jq -r .running <<<"$observation")" == true ]]; then
  printf 'already running pid=%s\n' "$(jq -r .pid <<<"$observation")"
  exit 0
fi

# Adopt the exact pre-receipt launcher once without touching its active log.
legacy_pid="$(cat "$pidfile" 2>/dev/null || true)"
if [[ ! -f "$root/run/comfyui-process.json" && "$legacy_pid" =~ ^[0-9]+$ ]]; then
  if h3_capture_process_receipt "$root" "$legacy_pid" "$log" "" "${argv[@]}" >/dev/null 2>&1; then
    printf 'adopted running pid=%s\n' "$legacy_pid"
    exit 0
  fi
fi

if ss -ltn "sport = :$port" | tail -n +2 | grep -q .; then
  printf 'port %s is already occupied by a non-matching process\n' "$port" >&2
  exit 1
fi

export PATH="/usr/local/cuda-13.0/bin:$root/venv/bin:$PATH"
export CUDA_HOME="/usr/local/cuda-13.0"
export HF_XET_HIGH_PERFORMANCE=1
export VHS_USE_IMAGEIO_FFMPEG=1

archived_log=""
if [[ -s "$log" ]]; then
  archived_log="$(h3_archive_stopped_log "$root" "$log" "${legacy_pid:-none}")"
fi

cd "$comfy"
nohup "${argv[@]}" > "$log" 2>&1 < /dev/null &
pid=$!
start_ticks="$(python3 - "$pid" <<'PY'
import sys
from pathlib import Path
value = Path(f"/proc/{sys.argv[1]}/stat").read_text()
print(value[value.rfind(")") + 2:].split()[19])
PY
)"
receipt_captured=false
cleanup_unreceipted() {
  [[ "$receipt_captured" == true ]] && return 0
  python3 - "$pid" "$start_ticks" <<'PY'
import os
import signal
import sys
import time
from pathlib import Path
pid, expected = int(sys.argv[1]), int(sys.argv[2])
path = Path(f"/proc/{pid}/stat")
def same_process():
    try:
        value = path.read_text()
        return int(value[value.rfind(")") + 2:].split()[19]) == expected
    except OSError:
        return False
if not same_process():
    raise SystemExit(0)
os.kill(pid, signal.SIGTERM)
for _ in range(40):
    if not same_process():
        raise SystemExit(0)
    time.sleep(0.25)
if same_process():
    os.kill(pid, signal.SIGKILL)
for _ in range(40):
    if not same_process():
        raise SystemExit(0)
    time.sleep(0.25)
raise SystemExit("unreceipted process retained after exact-identity SIGKILL")
PY
}
trap cleanup_unreceipted EXIT
printf '%s\n' "$pid" > "$pidfile"
for _ in $(seq 1 60); do
  if curl -fsS --max-time 2 "http://127.0.0.1:$port/" >/dev/null 2>&1; then
    break
  fi
  kill -0 "$pid" 2>/dev/null || break
  sleep 1
done
h3_capture_process_receipt "$root" "$pid" "$log" "$archived_log" "${argv[@]}" >/dev/null || {
  tail -n 100 "$log" >&2 || true
  exit 1
}
receipt_captured=true
trap - EXIT
printf 'started pid=%s listen=%s port=%s\n' "$pid" "$listen" "$port"
