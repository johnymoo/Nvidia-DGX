#!/usr/bin/env python3

import os
import signal
import subprocess
import tempfile
import time
from pathlib import Path


def start_ticks(pid):
    value = Path(f"/proc/{pid}/stat").read_text()
    return value[value.rfind(")") + 2:].split()[19]


def main():
    if not Path("/proc/self/stat").is_file():
        print("skipped: Linux /proc is required")
        return
    with tempfile.TemporaryDirectory() as temp:
        root = Path(temp)
        fake_python = root / "venv/bin/python"
        fake_comfy = root / "comfy/ComfyUI"
        fake_python.parent.mkdir(parents=True)
        fake_comfy.mkdir(parents=True)
        fake_python.symlink_to(Path("/bin/sh"))
        (fake_comfy / "main.py").write_text("# fixture\n")

        # Ignore SIGTERM so the startup cleanup must exercise its exact-PID
        # SIGKILL branch after receipt capture fails.
        process = subprocess.Popen(
            ["/bin/sh", "-c", "trap '' TERM; while :; do sleep 1; done"],
            start_new_session=True,
        )
        try:
            ticks = start_ticks(process.pid)
            cleanup = f'''set -euo pipefail
pid={process.pid}
start_ticks={ticks}
receipt_captured=false
{Path(__file__).parent.joinpath("execution/minimax-h3/start-comfyui.sh").read_text().split("cleanup_unreceipted() {", 1)[1].split("trap cleanup_unreceipted EXIT", 1)[0].join(["cleanup_unreceipted() {", "trap cleanup_unreceipted EXIT"])}
exit 1
'''
            result = subprocess.run(["bash", "-c", cleanup], capture_output=True, text=True)
            assert result.returncode != 0
            for _ in range(100):
                if process.poll() is not None:
                    break
                time.sleep(0.05)
            assert process.poll() is not None, "unreceipted fixture process survived cleanup"
        finally:
            if process.poll() is None:
                os.killpg(process.pid, signal.SIGKILL)


if __name__ == "__main__":
    main()
