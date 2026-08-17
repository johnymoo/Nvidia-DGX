#!/usr/bin/env python3

import sqlite3
import subprocess
import sys
import tempfile
from pathlib import Path


def main():
    with tempfile.TemporaryDirectory() as temp:
        root = Path(temp)
        database = root / "comfyui.db"
        sqlite3.connect(database).close()
        runtime_log = root / "runtime.log"
        runtime_log.write_text(
            "CUDA error at /private/models; peer=198.51.100.42; "
            "privacy-canary=not-for-output\n")
        kernel_log = root / "kernel.log"
        kernel_log.write_text("normal kernel output\n")
        command = [
            sys.executable,
            str(Path(__file__).parent / "execution/minimax-h3/runtime-health.py"),
            "--database", str(database),
            "--runtime-log", str(runtime_log),
            "--kernel-log", str(kernel_log),
        ]
        result = subprocess.run(command, capture_output=True, text=True)
        assert result.returncode == 1
        assert "1 matching line(s) at 1" in result.stderr
        for sensitive_value in (
                str(runtime_log), "/private/models", "198.51.100.42",
                "privacy-canary=not-for-output"):
            assert sensitive_value not in result.stderr


if __name__ == "__main__":
    main()
