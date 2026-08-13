#!/usr/bin/env python3

from __future__ import annotations

import argparse
import json
import re
import sqlite3
import sys
from pathlib import Path


RUNTIME_FATAL = re.compile(
    r"Failed to initialize database|Traceback|ImportError|ModuleNotFoundError|"
    r"Failed to import|Cannot import|CUDA error|out of memory|Killed",
    re.IGNORECASE,
)
KERNEL_FATAL = re.compile(
    r"NVRM: Xid|oom-kill|Out of memory: Killed process|mlx5.*fatal|CUDA.*fatal",
    re.IGNORECASE,
)


def database_checks(path: Path) -> dict:
    connection = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
    try:
        result = {}
        for pragma in ("quick_check", "integrity_check"):
            rows = [row[0] for row in connection.execute(f"PRAGMA {pragma}")]
            if rows != ["ok"]:
                raise RuntimeError(f"SQLite {pragma} failed: {rows}")
            result[pragma] = "ok"
        return result
    finally:
        connection.close()


def scan(path: Path, pattern: re.Pattern) -> dict:
    matches = []
    for number, line in enumerate(path.read_text(errors="replace").splitlines(), 1):
        if pattern.search(line):
            matches.append({"line": number, "text": line})
    if matches:
        raise RuntimeError(f"fatal pattern found in {path}: {matches[:5]}")
    return {"path": str(path), "fatal_matches": 0}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--database", required=True, type=Path)
    parser.add_argument("--runtime-log", required=True, type=Path)
    parser.add_argument("--kernel-log", required=True, type=Path)
    args = parser.parse_args()
    for path in (args.database, args.runtime_log, args.kernel_log):
        if not path.is_file():
            raise RuntimeError(f"required health evidence is missing: {path}")
    result = {
        "status": "passed",
        "database": {"path": str(args.database),
                     "checks": database_checks(args.database)},
        "runtime_log": scan(args.runtime_log, RUNTIME_FATAL),
        "kernel_log": scan(args.kernel_log, KERNEL_FATAL),
    }
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (OSError, RuntimeError, sqlite3.DatabaseError) as error:
        print(f"runtime health failed: {error}", file=sys.stderr)
        raise SystemExit(1)
