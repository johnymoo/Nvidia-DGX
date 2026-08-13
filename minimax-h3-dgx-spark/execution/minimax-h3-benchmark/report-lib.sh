#!/usr/bin/env bash

set -euo pipefail

report_observe() {
  local root="$1" port="$2" receipt
  receipt="$root/run/report-process.json"
  python3 - "$root" "$port" "$receipt" <<'PY'
import json, os, socket, sys
from pathlib import Path
root, port, receipt_path = Path(sys.argv[1]).resolve(), int(sys.argv[2]), Path(sys.argv[3])
receipt = json.loads(receipt_path.read_text()) if receipt_path.is_file() else None
observed = {"running": False, "identity_match": False, "listener_match": False,
            "http_code": "000", "receipt": str(receipt_path)}
if receipt:
    pid = int(receipt["pid"])
    proc = Path(f"/proc/{pid}")
    if proc.exists():
        stat = (proc / "stat").read_text()
        ticks = int(stat[stat.rfind(")") + 2:].split()[19])
        boot = Path("/proc/sys/kernel/random/boot_id").read_text().strip()
        argv = (proc / "cmdline").read_bytes().rstrip(b"\0").split(b"\0")
        argv = [item.decode(errors="replace") for item in argv]
        expected = [receipt["python"], "-m", "http.server", str(port),
                    "--bind", "0.0.0.0", "--directory", str(root / "site")]
        observed.update(pid=pid, start_ticks=ticks, boot_id=boot, argv=argv,
                        running=True, identity_match=(ticks == receipt["start_ticks"] and
                        boot == receipt["boot_id"] and argv == expected))
try:
    import urllib.request
    with urllib.request.urlopen(f"http://127.0.0.1:{port}/", timeout=3) as response:
        observed["http_code"] = str(response.status)
except Exception:
    pass
try:
    lines = Path("/proc/net/tcp").read_text().splitlines()[1:]
    inode = next(row.split()[9] for row in lines
                 if int(row.split()[1].split(":")[1], 16) == port and row.split()[3] == "0A")
    if observed.get("pid"):
        observed["listener_match"] = any(
            os.readlink(fd) == f"socket:[{inode}]"
            for fd in Path(f"/proc/{observed['pid']}/fd").iterdir()
            if fd.exists())
except (StopIteration, OSError, FileNotFoundError):
    pass
print(json.dumps(observed, indent=2))
PY
}
