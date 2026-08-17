#!/usr/bin/env bash

set -euo pipefail

H3_RUNTIME_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
H3_DOCKER_BIN="${H3_DOCKER_BIN:-docker}"
H3_PROC_ROOT="${H3_PROC_ROOT:-/proc}"
H3_BOOT_ID_FILE="${H3_BOOT_ID_FILE:-/proc/sys/kernel/random/boot_id}"
H3_SS_BIN="${H3_SS_BIN:-ss}"

h3_deployment_receipt_path() {
  local root="$1" require_running="$2"
  if [[ "$require_running" == true ]]; then
    printf '%s/artifacts/deployment/receipt.json\n' "$root"
  else
    printf '%s/artifacts/deployment/preflight-receipt.json\n' "$root"
  fi
}

h3_archive_stopped_log() {
  local root="$1" log="$2" prior_pid="${3:-none}" stamp archive
  [[ -s "$log" ]] || return 0
  mkdir -p "$root/artifacts/deployment/logs"
  stamp="${H3_ARCHIVE_STAMP:-$(date -u +%Y%m%dT%H%M%S.%NZ)}"
  archive="$root/artifacts/deployment/logs/comfyui-$stamp-${prior_pid:-none}.log"
  [[ ! -e "$archive" ]] || {
    printf 'refusing to overwrite archived log: %s\n' "$archive" >&2
    return 1
  }
  mv "$log" "$archive"
  printf '%s\n' "$archive"
}

h3_protected_status() {
  local baseline="${1:-${H3_PROTECTED_BASELINE:-}}"
  local name expected_id expected_health expected_restarts observed
  if [[ -z "$baseline" ]]; then
    jq -n '{enabled: false, matches: true, observed: {}, expected: {}}'
    return 0
  fi
  name="$(jq -er .name "$baseline")"
  expected_id="$(jq -er .container_id "$baseline")"
  expected_health="$(jq -er .health "$baseline")"
  expected_restarts="$(jq -er .restart_count "$baseline")"
  observed="$($H3_DOCKER_BIN inspect "$name" 2>/dev/null || printf '[]')"
  jq -n \
    --arg name "$name" \
    --arg expected_id "$expected_id" \
    --arg expected_health "$expected_health" \
    --argjson expected_restart_count "$expected_restarts" \
    --argjson observed "$observed" \
    '{enabled: true, name: $name, expected: {container_id: $expected_id,
       health: $expected_health, restart_count: $expected_restart_count},
      observed: {container_id: ($observed[0].Id // ""),
        state: ($observed[0].State.Status // ""),
        health: ($observed[0].State.Health.Status // ""),
        restart_count: ($observed[0].RestartCount // null)},
      matches: (($observed[0].Id // "") == $expected_id and
        ($observed[0].State.Status // "") == "running" and
        ($observed[0].State.Health.Status // "") == $expected_health and
        ($observed[0].RestartCount // null) == $expected_restart_count)}'
}

h3_assert_protected() {
  local status
  status="$(h3_protected_status "${1:-${H3_PROTECTED_BASELINE:-}}")"
  jq -e '.matches == true' <<<"$status" >/dev/null || {
    jq . <<<"$status" >&2
    return 1
  }
}

h3_process_observation() {
  local root="$1" port="$2" process_file
  process_file="$root/run/comfyui-process.json"
  H3_ROOT="$root" H3_PORT_VALUE="$port" H3_PROCESS_FILE="$process_file" \
    H3_PROC_ROOT="$H3_PROC_ROOT" H3_BOOT_ID_FILE="$H3_BOOT_ID_FILE" \
    H3_SS_BIN="$H3_SS_BIN" python3 - <<'PY'
import json
import os
import re
import subprocess
from pathlib import Path

root = os.environ["H3_ROOT"]
port = os.environ["H3_PORT_VALUE"]
process_file = Path(os.environ["H3_PROCESS_FILE"])
receipt = {}
if process_file.is_file():
    try:
        receipt = json.loads(process_file.read_text())
    except Exception:
        receipt = {}

proc_root = Path(os.environ["H3_PROC_ROOT"])
boot_file = Path(os.environ["H3_BOOT_ID_FILE"])
ss_bin = os.environ["H3_SS_BIN"]
pid = receipt.get("pid")
observed_argv = []
observed_ticks = None
observed_boot = None
exists = False
if isinstance(pid, int):
    proc = proc_root / str(pid)
    try:
        observed_argv = proc.joinpath("cmdline").read_bytes().rstrip(b"\0").decode().split("\0")
        stat = proc.joinpath("stat").read_text()
        observed_ticks = int(stat[stat.rfind(")") + 2:].split()[19])
        observed_boot = boot_file.read_text().strip()
        exists = True
    except (OSError, ValueError, UnicodeDecodeError):
        pass

listener_pids = []
try:
    output = subprocess.check_output(
        [ss_bin, "-H", "-ltnp", f"sport = :{port}"], text=True,
        stderr=subprocess.DEVNULL,
    )
    listener_pids = sorted({int(item) for item in re.findall(r"pid=(\d+)", output)})
except (OSError, subprocess.CalledProcessError):
    output = ""

identity_match = bool(
    exists
    and observed_ticks == receipt.get("start_ticks")
    and observed_boot == receipt.get("boot_id")
    and observed_argv == receipt.get("argv")
)
listener_match = identity_match and listener_pids == [pid]
print(json.dumps({
    "running": bool(identity_match and listener_match),
    "process_exists": exists,
    "identity_match": identity_match,
    "listener_match": listener_match,
    "pid": pid,
    "start_ticks": observed_ticks,
    "boot_id": observed_boot,
    "argv": observed_argv,
    "listener_pids": listener_pids,
    "listener": output.strip(),
    "started_at": receipt.get("started_at"),
    "active_log": receipt.get("active_log"),
    "archived_log": receipt.get("archived_log"),
    "process_receipt": str(process_file),
}, sort_keys=True))
PY
}

h3_capture_process_receipt() {
  local root="$1" pid="$2" active_log="$3" archived_log="$4"
  shift 4
  H3_ROOT="$root" H3_PID="$pid" H3_ACTIVE_LOG="$active_log" \
    H3_ARCHIVED_LOG="$archived_log" H3_PROC_ROOT="$H3_PROC_ROOT" \
    H3_BOOT_ID_FILE="$H3_BOOT_ID_FILE" H3_SS_BIN="$H3_SS_BIN" \
    python3 - "$@" <<'PY'
import datetime
import json
import os
import re
import subprocess
import sys
from pathlib import Path

root = Path(os.environ["H3_ROOT"])
proc_root = Path(os.environ["H3_PROC_ROOT"])
boot_file = Path(os.environ["H3_BOOT_ID_FILE"])
ss_bin = os.environ["H3_SS_BIN"]
pid = int(os.environ["H3_PID"])
expected_argv = sys.argv[1:]
proc = proc_root / str(pid)
argv = proc.joinpath("cmdline").read_bytes().rstrip(b"\0").decode().split("\0")
if argv != expected_argv:
    raise SystemExit("process argv does not match the exact launcher argv")
stat = proc.joinpath("stat").read_text()
start_ticks = int(stat[stat.rfind(")") + 2:].split()[19])
boot_id = boot_file.read_text().strip()
btime = next(int(line.split()[1]) for line in proc_root.joinpath("stat").read_text().splitlines()
             if line.startswith("btime "))
started_epoch = btime + start_ticks / os.sysconf(os.sysconf_names["SC_CLK_TCK"])
started_at = datetime.datetime.fromtimestamp(
    started_epoch, datetime.timezone.utc).isoformat().replace("+00:00", "Z")
output = subprocess.check_output(
    [ss_bin, "-H", "-ltnp", f"sport = :{expected_argv[expected_argv.index('--port') + 1]}"],
    text=True,
)
listener_pids = sorted({int(item) for item in re.findall(r"pid=(\d+)", output)})
if listener_pids != [pid]:
    raise SystemExit("process does not exclusively own the configured listener")
receipt = {
    "pid": pid,
    "start_ticks": start_ticks,
    "boot_id": boot_id,
    "argv": argv,
    "started_at": started_at,
    "active_log": os.environ["H3_ACTIVE_LOG"],
    "archived_log": os.environ["H3_ARCHIVED_LOG"] or None,
    "listener_pid": pid,
}
target = root / "run" / "comfyui-process.json"
temporary = target.with_name(target.name + f".tmp.{os.getpid()}")
temporary.write_text(json.dumps(receipt, indent=2, sort_keys=True) + "\n")
temporary.replace(target)
print(json.dumps(receipt, sort_keys=True))
PY
}

h3_assert_weight_fingerprints() {
  local root="$1" receipt="$2" manifest="$3"
  H3_ROOT="$root" H3_RECEIPT="$receipt" H3_MANIFEST="$manifest" python3 - <<'PY'
import csv
import hashlib
import json
import os
from pathlib import Path

root = Path(os.environ["H3_ROOT"])
receipt_path = Path(os.environ["H3_RECEIPT"])
manifest_path = Path(os.environ["H3_MANIFEST"])
receipt = json.loads(receipt_path.read_text())
if receipt.get("status") != "passed":
    raise SystemExit("weight receipt did not pass")
manifest_sha = hashlib.sha256(manifest_path.read_bytes()).hexdigest()
if receipt.get("manifest_sha256") != manifest_sha:
    raise SystemExit("weight receipt manifest mismatch")
files = {item["path"]: item for item in receipt.get("files", [])}
with manifest_path.open(newline="") as handle:
    rows = list(csv.DictReader(handle, delimiter="\t"))
if len(rows) != len(files):
    raise SystemExit("weight receipt file count mismatch")
for row in rows:
    rel = row["path"]
    item = files.get(rel)
    if not item or item.get("sha256") != row["sha256"] or item.get("bytes") != int(row["bytes"]):
        raise SystemExit(f"weight receipt identity mismatch: {rel}")
    stat = (root / "models" / rel).stat()
    expected = (item.get("device"), item.get("inode"), item.get("bytes"),
                item.get("mtime_ns"), item.get("ctime_ns"))
    actual = (stat.st_dev, stat.st_ino, stat.st_size, stat.st_mtime_ns, stat.st_ctime_ns)
    if expected != actual:
        raise SystemExit(f"weight changed after full verification: {rel}")
PY
}
